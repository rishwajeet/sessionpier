"""Read subscription limits through official local clients. No token extraction."""
from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import claude_profile as profiles


class UsageError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def percent(value):
    return value if type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 100 else None


def strip_terminal(value):
    value = re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)', '', value)
    value = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', value)
    value = re.sub(r'\x1b[@-_]', '', value)
    return value.replace('\r\n', '\n').replace('\r', '\n')


def reset_time(description, now):
    """Resolve an explicitly reported reset; retain its original text in the UI."""
    match = re.fullmatch(r'Resets (.+?) \(([^)]+)\)', description.strip(), re.I)
    if not match:
        return None
    try:
        zone = ZoneInfo(match[2])
    except ZoneInfoNotFoundError:
        return None
    local = dt.datetime.fromtimestamp(now, zone)
    text = re.sub(r'\s+', ' ', match[1]).strip()
    try:
        # The CLI reports either a dated reset or the next time of day.
        if ' at ' in text:
            date_part, time_part = text.split(' at ', 1)
            parsed = dt.datetime.strptime(f'{local.year} {date_part} {time_part}', '%Y %b %d %I:%M%p')
            value = parsed.replace(tzinfo=zone)
            if value < local - dt.timedelta(days=1):
                value = value.replace(year=value.year + 1)
        else:
            clock = dt.datetime.strptime(text, '%I:%M%p').time()
            value = dt.datetime.combine(local.date(), clock, zone)
            if value < local - dt.timedelta(minutes=2):
                value += dt.timedelta(days=1)
        # Dated quota windows longer than a month are not a plausible parsed reset.
        if not -120 <= value.timestamp() - now <= 32 * 86400:
            return None
        return value.timestamp()
    except (ValueError, OverflowError):
        return None


def parse_claude_usage(raw, now=None):
    current = time.time() if now is None else now
    text = strip_terminal(raw)
    meters = {}
    active = None
    for line in text.splitlines():
        line = line.strip()
        if line == 'Current session':
            active = 'five_hour'
            meters[active] = {'id': active, 'label': 'Session', 'usedPercent': None,
                             'windowMinutes': 300, 'resetsAt': None, 'resetDescription': None}
        elif re.fullmatch(r'Current week(?: \(.+\))?', line):
            model = re.search(r'\((.+)\)', line)
            title = model[1] if model else 'all models'
            active = 'seven_day' if title.lower() == 'all models' else 'seven_day_' + re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
            meters[active] = {'id': active, 'label': 'Weekly' if active == 'seven_day' else f'{title} weekly',
                             'usedPercent': None, 'windowMinutes': 10080, 'resetsAt': None, 'resetDescription': None}
        elif line.startswith(("What's contributing", 'Usage credits', 'Extra usage', 'Session cost', 'Settings ')):
            active = None
        elif active:
            values = re.findall(r'(\d+(?:\.\d+)?)%\s*(used|remaining)', line)
            if values:
                number, kind = values[-1]
                value = percent(float(number))
                meters[active]['usedPercent'] = (100 - value if kind == 'remaining' else value) if value is not None else None
            elif line.startswith('Resets '):
                meters[active]['resetDescription'] = line
                meters[active]['resetsAt'] = reset_time(line, current)
    return [meter for meter in meters.values() if meter['usedPercent'] is not None]


def claude_identity(profile):
    desk, cli = profiles.paths(profile)
    meta_file = profiles.HOME / '.claude.json' if profile['default'] else cli / '.claude.json'
    meta = profiles.read_json(meta_file).get('oauthAccount') or {}
    account = profiles.read_json(desk / 'config.json').get('lastKnownAccountUuid')
    bucket = profiles.session_bucket(profile)
    if not meta.get('accountUuid') or not meta.get('organizationUuid'):
        raise UsageError('login_required', 'Connect live usage with the official Claude Code sign-in.')
    if not account or not bucket:
        raise UsageError('desktop_setup', 'Sign in to this Desktop account and open Code once first.')
    if meta['accountUuid'] != account or meta['organizationUuid'] != bucket.name:
        raise UsageError('identity_mismatch', 'The Code login differs from this Desktop account. Reconnect using the matching account and workspace.')
    return {'accountId': meta['accountUuid'], 'organizationId': meta['organizationUuid'],
            'email': meta.get('emailAddress', ''), 'plan': meta.get('organizationRateLimitTier', '')}


def identity_key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_claude(profile, timeout=24):
    identity = claude_identity(profile)
    try:
        binary = profiles.claude_binary()
    except profiles.ProfileError as exc:
        raise UsageError('client_missing', 'Install the official Claude Code CLI to enable live usage.') from exc
    env = profiles.clean_env(profile)
    env.update(TERM='xterm-256color', ENABLE_CLAUDEAI_MCP_SERVERS='false', DISABLE_AUTOUPDATER='1')
    auth = subprocess.run([binary, 'auth', 'status'], env=env, capture_output=True, text=True, timeout=10,
                          cwd=profiles.ROOT)
    try:
        state = json.loads(auth.stdout)
    except ValueError:
        state = {}
    if not state.get('loggedIn'):
        raise UsageError('login_required', 'Connect live usage with the official Claude Code sign-in.')
    # Use an empty app-owned folder. Never execute a prompt, hooks, or configured MCP servers.
    folder = profiles.ROOT / 'verification'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    args = [binary, '--safe-mode', '--strict-mcp-config', '--settings',
            '{"disableAllHooks":true,"remoteControlAtStartup":false,"disableRemoteControl":true}',
            '--tools', '', '--ax-screen-reader', '/usage']
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 50, 140, 0, 0))
    proc = None
    raw = b''
    last_data = time.monotonic()
    deadline = last_data + timeout
    try:
        proc = subprocess.Popen(args, env=env, cwd=folder, stdin=slave, stdout=slave,
                                stderr=slave, start_new_session=True)
        os.close(slave)
        slave = -1
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.15)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                raw += chunk
                last_data = time.monotonic()
                if len(raw) > 1024 * 1024:
                    raise UsageError('unsupported_output', 'The Claude usage screen returned an unexpected response.')
            text = strip_terminal(raw.decode('utf-8', 'replace'))
            if 'Do you trust the files' in text or 'Is this a project you created' in text:
                raise UsageError('setup_required', 'Open usage setup once to finish the official client’s folder confirmation.')
            if '429' in text or 'Too many requests' in text:
                raise UsageError('rate_limited', 'Claude asked us to wait. Automatic refresh will back off.')
            if parse_claude_usage(text) and time.monotonic() - last_data > 0.8:
                break
            if proc.poll() is not None:
                break
    finally:
        if slave >= 0:
            os.close(slave)
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=2)
        os.close(master)
    observed = time.time()
    meters = parse_claude_usage(raw.decode('utf-8', 'replace'), observed)
    if not meters:
        raise UsageError('refresh_failed', 'Claude did not return usage. Open the native usage screen or try again later.')
    # A concurrent sign-in may never attach one account's sample to another account.
    after = claude_identity(profile)
    if (identity['accountId'], identity['organizationId']) != (after['accountId'], after['organizationId']):
        raise UsageError('identity_changed', 'The account changed during refresh. Retry after sign-in finishes.')
    return {'source': 'Claude Code /usage', 'sampledAt': observed, 'meters': meters,
            'identity': after, 'identityKey': identity_key({k: after[k] for k in ('accountId', 'organizationId')})}


def codex_env(home):
    env = dict(os.environ)
    for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN', 'CODEX_AUTH_TOKEN',
                 'OPENAI_BASE_URL', 'OPENAI_ORG_ID', 'OPENAI_ORGANIZATION'):
        env.pop(name, None)
    env['CODEX_HOME'] = str(home)
    return env


class CodexConnection:
    def __init__(self, binary, home, timeout=18):
        self.proc = subprocess.Popen([str(binary), 'app-server', '--stdio'], env=codex_env(home),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        self.buffer = b''
        self.timeout = timeout
        self.index = 0

    def send(self, message):
        self.proc.stdin.write(json.dumps(message).encode() + b'\n')
        self.proc.stdin.flush()

    def request(self, method, params=None):
        self.index += 1
        message = {'id': self.index, 'method': method}
        if params is not None:
            message['params'] = params
        self.send(message)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if b'\n' not in self.buffer:
                if not select.select([self.proc.stdout], [], [], 0.2)[0]:
                    if self.proc.poll() is not None:
                        break
                    continue
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                self.buffer += chunk
                if len(self.buffer) > 2 * 1024 * 1024:
                    raise UsageError('unsupported_output', 'The Codex client returned an unexpected response.')
                continue
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                result = json.loads(line)
            except ValueError:
                continue
            if result.get('id') != self.index:
                continue
            if 'error' in result:
                raise UsageError('refresh_failed', 'Codex could not read account limits. Check the native client’s login and connection.')
            return result.get('result', {})
        raise UsageError('timeout', 'Codex did not respond in time. Your last reading is kept.')

    def close(self):
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(timeout=2)
        self.proc.stdin.close()
        self.proc.stdout.close()


def parse_codex_limits(response):
    buckets = response.get('rateLimitsByLimitId')
    if not isinstance(buckets, dict) or not buckets:
        fallback = response.get('rateLimits')
        buckets = {fallback.get('limitId') or 'codex': fallback} if isinstance(fallback, dict) else {}
    meters = []
    for key, value in buckets.items():
        if not isinstance(value, dict):
            continue
        for slot in ('primary', 'secondary'):
            window = value.get(slot)
            if not isinstance(window, dict) or percent(window.get('usedPercent')) is None:
                continue
            minutes = window.get('windowDurationMins')
            valid_minutes = type(minutes) in (int, float) and math.isfinite(minutes) and 0 < minutes <= 525600
            minutes = minutes if valid_minutes else None
            title = ('Weekly' if minutes == 10080 else 'Daily' if minutes == 1440 else
                     'Session' if minutes == 300 else f'{minutes:g} minute window' if minutes else 'Usage window')
            if len(buckets) > 1:
                title = f"{value.get('limitName') or key} · {title}"
            reset = window.get('resetsAt')
            if type(reset) not in (int, float) or not math.isfinite(reset) or not 0 < reset < 32503680000:
                reset = None
            meters.append({'id': f'{key}_{slot}', 'label': title, 'usedPercent': window['usedPercent'],
                           'windowMinutes': minutes, 'resetsAt': reset, 'resetDescription': None})
    return meters


def read_codex(binary, home):
    connection = CodexConnection(binary, home)
    try:
        connection.request('initialize', {'clientInfo': {'name': 'sessionpier',
                           'title': 'SessionPier', 'version': '2.0.0'}})
        connection.send({'method': 'initialized', 'params': {}})
        account = connection.request('account/read', {'refreshToken': False}).get('account') or {}
        if account.get('type') != 'chatgpt':
            raise UsageError('login_required', 'Sign in to the official Codex client with a ChatGPT subscription.')
        value = connection.request('account/rateLimits/read')
        after = connection.request('account/read', {'refreshToken': False}).get('account') or {}
        if account != after:
            raise UsageError('identity_changed', 'The Codex account changed during refresh. Retry after sign-in finishes.')
        meters = parse_codex_limits(value)
        if not meters:
            raise UsageError('unavailable', 'This Codex account has not reported a percentage limit. Unknown is not zero.')
        identity = {'email': account.get('email', ''), 'plan': account.get('planType', ''),
                    'accountId': account.get('id', '')}
        return {'source': 'Codex app server', 'sampledAt': time.time(), 'meters': meters,
                'identity': identity, 'identityKey': identity_key(identity)}
    finally:
        connection.close()
