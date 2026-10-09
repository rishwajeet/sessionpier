#!/usr/bin/env python3
"""Local Claude profile manager. Never reads or transfers login credentials."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

HOME = Path.home()
ROOT = HOME / 'Library/Application Support/Claude Profiles'
MASTER_CLI = HOME / '.claude'
MASTER_DESKTOP = HOME / 'Library/Application Support/Claude'
CLAUDE_APP = Path('/Applications/Claude.app')
APP = Path(os.environ.get('COMPANION_APP_BUNDLE', str(HOME / 'Applications/SessionPier.app')))
SOURCE = Path(__file__).resolve()
SHARED = ('CLAUDE.md', 'skills', 'agents', 'commands', 'hooks', 'output-styles', 'statusline.sh')
PLUGIN_SHARED = ('cache', 'marketplaces', 'installed_plugins.json', 'known_marketplaces.json')
SHARED_HISTORY_DIRS = ('projects', 'file-history', 'plans', 'tasks', 'todos')
SESSION_FIELDS = {
    'sessionId', 'cliSessionId', 'cwd', 'originCwd', 'gitAnchors', 'lastFocusedAt',
    'createdAt', 'lastActivityAt', 'model', 'effort', 'isArchived', 'title',
    'titleSource', 'completedTurns', 'titleTurn', 'lastAssistantUuid',
    'priorCliSessionIds', 'rewindEdges', 'transcriptModelStates',
}
AUTH_ENV = {
    'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL',
    'ANTHROPIC_PROFILE', 'ANTHROPIC_FEDERATION_RULE_ID', 'ANTHROPIC_ORGANIZATION_ID',
    'ANTHROPIC_IDENTITY_TOKEN_FILE', 'CLAUDE_CODE_OAUTH_TOKEN',
    'CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR', 'CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR',
    'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY',
    'CLAUDE_CODE_HOST_CREDS_FILE', 'CLAUDE_CODE_HOST_AUTH_ENV_VAR',
    'CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST',
}
AUTH_SETTINGS = {'apiKeyHelper', 'forceLoginMethod', 'forceLoginOrgUUID', 'forceLoginGatewayUrl'}


class ProfileError(Exception):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')


def read_json(path, default=None):
    if not path.exists():
        return {} if default is None else default
    try:
        value = json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        raise ProfileError(f'Cannot read valid JSON at {path}') from exc
    if not isinstance(value, dict):
        raise ProfileError(f'Expected a JSON object at {path}')
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = json.dumps(value, indent=2, ensure_ascii=False) + '\n'
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.profile-write-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def init_root():
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    ROOT.chmod(0o700)


@contextlib.contextmanager
def locked():
    init_root()
    with (ROOT / '.manager.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def slug(name):
    name = name.strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _-]{0,39}', name):
        raise ProfileError('Use 1–40 letters, numbers, spaces, dashes or underscores.')
    return re.sub(r'[ _]+', '-', name).lower()


def registry():
    return read_json(ROOT / 'profiles.json', {'version': 1, 'profiles': []})


def get_profile(name):
    key = slug(name)
    for item in registry()['profiles']:
        if item['id'] == key:
            return item
    raise ProfileError(f'Unknown profile: {name}. Run claude-profile list.')


def paths(profile):
    if profile['default']:
        return MASTER_DESKTOP, MASTER_CLI
    base = ROOT / 'profiles' / profile['id']
    return base / 'desktop', base / 'cli'


def requires_remote_control_block(profile):
    # New/unknown profiles stay protected until their ownership is explicit.
    return profile.get('remoteControlPolicy', 'blocked') != 'allowed'


def desktop_code_config(profile):
    if not profile['default'] and (requires_remote_control_block(profile) or profile.get('historySharingEnabled') is False):
        return paths(profile)[1]
    return MASTER_CLI


def desktop_runtime_matches(profile):
    """Recognize protected processes launched with their isolated config root.

    A config file alone does not establish which settings a running app reads.
    Store only process identity/config path, never its environment or tokens.
    """
    running = desktop_pids(profile)
    if not running or desktop_code_config(profile) == MASTER_CLI:
        return True
    try:
        saved = read_json(ROOT / 'runtime' / (profile['id'] + '.json'))
    except ProfileError:
        return False
    if (len(running) != 1 or saved.get('pid') != running[0]
            or saved.get('codeConfig') != str(desktop_code_config(profile))):
        return False
    try:
        started = subprocess.run(['/bin/ps', '-p', str(running[0]), '-o', 'lstart='],
                                 capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(started) and saved.get('processStartedAt') == started


def record_desktop_runtime(profile, pid):
    started = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart='],
                             capture_output=True, text=True, check=True).stdout.strip()
    write_json(ROOT / 'runtime' / (profile['id'] + '.json'),
               {'pid': pid, 'processStartedAt': started,
                'codeConfig': str(desktop_code_config(profile)), 'recordedAt': now()})


def clean_env(profile, desktop=False):
    env = dict(os.environ)
    for key in AUTH_ENV | {'CLAUDE_CONFIG_DIR', 'CLAUDE_SECURESTORAGE_CONFIG_DIR',
                           'CLAUDE_USER_DATA_DIR', 'CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT'}:
        env.pop(key, None)
    desk, cli = paths(profile)
    if not profile['default'] and not desktop:
        env['CLAUDE_CONFIG_DIR'] = str(cli)
        env['CLAUDE_SECURESTORAGE_CONFIG_DIR'] = str(cli)
    if not profile['default'] and desktop:
        # Desktop supplies the selected account's OAuth to its embedded Code engine.
        # Shared-account settings are isolated; transcript directories stay linked.
        env['CLAUDE_USER_DATA_DIR'] = str(desk)
        if desktop_code_config(profile) != MASTER_CLI:
            env['CLAUDE_CONFIG_DIR'] = str(desktop_code_config(profile))
    env['CLAUDE_PROFILE_NAME'] = profile['name']
    return env


def claude_binary():
    candidates = [HOME / '.local/bin/claude', Path('/opt/homebrew/bin/claude')]
    found = shutil.which('claude')
    if found:
        candidates.insert(0, Path(found))
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise ProfileError('Claude Code was not found. Install it before opening a Code session.')


def desktop_pids(profile):
    desk, _ = paths(profile)
    binary = str(CLAUDE_APP / 'Contents/MacOS/Claude')
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,args='], capture_output=True, text=True, check=True)
    matches = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[1].startswith(binary):
            continue
        command = parts[1]
        if command != binary and not command.startswith(binary + ' '):
            continue
        flag = '--user-data-dir=' + str(desk)
        match = re.search(re.escape(flag) + r'(?=$| --)', command)
        if match or (profile['default'] and '--user-data-dir=' not in command):
            matches.append(int(parts[0]))
    return matches


def cli_running(profile):
    # lsof only reports filenames; we never inspect a running process's environment.
    if profile['default']:
        return False
    _, cli = paths(profile)
    result = subprocess.run(['/usr/sbin/lsof', '-nP', '-Fpn', '-c', 'claude'], capture_output=True, text=True)
    return any(line.startswith('n' + str(cli) + '/') for line in result.stdout.splitlines())


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def shared_files():
    """Enumerate only reusable definitions; credentials and plugin data are excluded."""
    result = {}
    roots = [(MASTER_CLI / name, name) for name in SHARED]
    roots += [(MASTER_CLI / 'plugins' / name, 'plugins/' + name) for name in PLUGIN_SHARED]
    for source, relative in roots:
        if source.is_file():
            result[relative] = source
        elif source.is_dir():
            for base, dirs, files in os.walk(source, followlinks=False):
                dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules'}]
                for filename in files:
                    if filename in {'.DS_Store', '.credentials.json'}:
                        continue
                    path = Path(base) / filename
                    if path.is_file():
                        result[str(Path(relative) / path.relative_to(source))] = path
    return result


def sanitized_settings(profile=None):
    settings = read_json(MASTER_CLI / 'settings.json')
    for key in AUTH_SETTINGS:
        settings.pop(key, None)
    settings['env'] = {k: v for k, v in settings.get('env', {}).items()
                       if k not in AUTH_ENV | {'CLAUDE_CONFIG_DIR', 'CLAUDE_SECURESTORAGE_CONFIG_DIR', 'CLAUDE_USER_DATA_DIR'}}
    if profile is not None:
        if requires_remote_control_block(profile):
            settings['disableRemoteControl'] = True
            settings['remoteControlAtStartup'] = False
        else:
            settings.pop('disableRemoteControl', None)
            settings['remoteControlAtStartup'] = False
    return settings


def link_shared_history(profile):
    """Terminal profiles retain isolated auth, but resume the same local transcripts."""
    if profile['default'] or profile.get('historySharingEnabled') is False:
        return
    _, cli = paths(profile)
    for name in SHARED_HISTORY_DIRS:
        source = MASTER_CLI / name
        source.mkdir(parents=True, exist_ok=True)
        target = cli / name
        if target.is_symlink() and target.resolve() == source.resolve():
            continue
        if target.exists():
            # A profile used before shared-history mode may contain unique work.
            # Never replace such a directory automatically.
            if target.is_dir() and not any(target.iterdir()):
                target.rmdir()
            else:
                raise ProfileError(f'Unmerged local history exists at {target}. It was left intact.')
        target.symlink_to(source, target_is_directory=True)
    source = MASTER_CLI / 'history.jsonl'
    if source.is_file():
        target = cli / 'history.jsonl'
        if not target.exists() and not target.is_symlink():
            target.symlink_to(source)


def session_bucket(profile):
    """Resolve identity from Desktop, never from possibly different CLI credentials."""
    desk, _ = paths(profile)
    account = read_json(desk / 'config.json').get('lastKnownAccountUuid')
    uuid = r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'
    if not isinstance(account, str) or not re.fullmatch(uuid, account):
        return None
    root = desk / 'claude-code-sessions' / account
    # This cookie holds only the selected organization UUID, not a session token.
    cookie_db = desk / 'Cookies'
    org = None
    if cookie_db.exists():
        try:
            with sqlite3.connect(cookie_db.as_uri() + '?mode=ro', uri=True, timeout=2) as db:
                rows = db.execute("SELECT value FROM cookies WHERE name = 'lastActiveOrg' AND host_key IN ('.claude.ai', 'claude.ai')").fetchall()
                values = {r[0] for r in rows if re.fullmatch(uuid, r[0] or '')}
                if len(values) == 1:
                    org = values.pop()
        except sqlite3.Error:
            pass
    if org:
        return root / org
    buckets = [d for d in root.iterdir() if d.is_dir() and re.fullmatch(uuid, d.name)] if root.exists() else []
    return buckets[0] if len(buckets) == 1 else None


def desktop_login_saved(profile):
    desk, _ = paths(profile)
    if not read_json(desk / 'config.json').get('lastKnownAccountUuid'):
        return False
    cookie_db = desk / 'Cookies'
    if not cookie_db.exists():
        return False
    try:
        with sqlite3.connect(cookie_db.as_uri() + '?mode=ro', uri=True, timeout=2) as db:
            return bool(db.execute("SELECT count(*) FROM cookies WHERE name='sessionKey' AND host_key IN ('.claude.ai','claude.ai')").fetchone()[0])
    except sqlite3.Error:
        return False


def usage_snapshot(profile, *, clock=None):
    """Read Desktop's own org-scoped usage sample, without credentials/network.

    Claude Desktop 2.26454.2 stores percentages in version-2
    plan-usage-history.json. Its writer samples at most once per 270 seconds;
    background refresh is controlled by Desktop and can pause when inactive.
    Reset times are not persisted, so never infer a reset or remaining quota.
    """
    current = time.time() if clock is None else clock
    empty = {'status': 'unavailable', 'sampledAt': None, 'ageSeconds': None,
             'stale': True, 'meters': [], 'note': 'No usage snapshot yet'}
    if not desktop_login_saved(profile):
        return {**empty, 'note': 'Sign in to Desktop to see usage'}
    try:
        bucket = session_bucket(profile)
        if bucket is None:
            return {**empty, 'note': 'Open Code once to identify this account’s usage'}
        desk, _ = paths(profile)
        history = read_json(desk / 'plan-usage-history.json')
        if history.get('version') != 2 or not isinstance(history.get('samples'), list):
            return empty
        # Reject unscoped legacy rows and other organizations, even if newer.
        # A future timestamp must not make stale data appear fresh indefinitely.
        samples = [r for r in history['samples'] if isinstance(r, dict)
                   and r.get('org') == bucket.name
                   and type(r.get('t')) in (int, float) and math.isfinite(r['t'])
                   and 0 < r['t'] <= (current + 60) * 1000
                   and isinstance(r.get('u'), dict)]
        if not samples:
            return empty
        latest = max(samples, key=lambda r: r['t'])
        labels = [('fh', 'Session · 5 hours'), ('sd', 'Weekly · all models'),
                  ('so', 'Weekly · Opus'), ('sn', 'Weekly · Sonnet'),
                  ('oa', 'Weekly · OAuth apps'), ('cw', 'Weekly · Cowork'),
                  ('om', 'Weekly · Omelette'), ('op', 'Omelette promotional'),
                  ('xu', 'Extra usage budget')]
        meters = []
        for key, label in labels:
            value = latest['u'].get(key)
            valid = type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100
            # Keep the two primary windows visible; missing is never zero.
            if key in ('fh', 'sd') or valid:
                meters.append({'id': key, 'label': label, 'usedPercent': value if valid else None})
        if not any(m['usedPercent'] is not None for m in meters):
            return empty
        age = max(0, current - latest['t'] / 1000)
        return {'status': 'snapshot', 'sampledAt': latest['t'] / 1000,
                'ageSeconds': int(age), 'stale': age > 20 * 60, 'meters': meters,
                'note': 'Read from this account’s Claude Desktop usage snapshot'}
    except (ProfileError, OSError, ValueError, TypeError):
        # A partially written/malformed usage file must not disable switching.
        return {**empty, 'note': 'Usage snapshot could not be read; open Claude to refresh it'}


def activity(row):
    value = row.get('lastActivityAt', row.get('createdAt', 0))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000
        except ValueError:
            pass
    return 0


def session_catalog():
    """Read sidebar records only; transcripts stay at their original paths."""
    catalog = {}
    skipped = 0
    for profile in registry()['profiles']:
        if profile.get('historySharingEnabled') is False:
            continue
        desk, _ = paths(profile)
        root = desk / 'claude-code-sessions'
        for file in sorted(root.glob('*/*/local_*.json')):
            try:
                raw = file.read_bytes()
                row = json.loads(raw)
                # Do not consume a row changing underneath this snapshot.
                if raw != file.read_bytes() or not isinstance(row, dict):
                    skipped += 1
                    continue
                sid = row.get('sessionId', '')
                cli_id = row.get('cliSessionId', '')
                cwd = row.get('cwd', '')
                if not re.fullmatch(r'local_[A-Za-z0-9_-]+', sid) or file.stem != sid:
                    skipped += 1
                    continue
                if not re.fullmatch(r'[A-Za-z0-9_-]+', cli_id) or not isinstance(cwd, str) or not Path(cwd).is_absolute():
                    skipped += 1
                    continue
                if not any((MASTER_CLI / 'projects').glob(f'*/{cli_id}.jsonl')):
                    skipped += 1
                    continue
                clean = {k: v for k, v in row.items() if k in SESSION_FIELDS}
                # Account-scoped connector snapshots, bridges, and approvals are
                # intentionally re-established by the destination account.
                clean['permissionMode'] = 'default'
                if sid not in catalog or activity(clean) > activity(catalog[sid]['row']):
                    catalog[sid] = {'row': clean, 'source': str(file),
                                    'sha256': hashlib.sha256(raw).hexdigest()}
            except (OSError, ValueError, TypeError):
                skipped += 1
    return catalog, skipped


def history_status(profile):
    bucket = session_bucket(profile)
    catalog, skipped = session_catalog()
    return {'availableSessions': len(catalog), 'skippedRows': skipped,
            'remoteControlBlocked': remote_control_blocked(desktop_code_config(profile)),
            'ready': bucket is not None, 'desktopSharedConfig': str(desktop_code_config(profile)),
            'message': 'Local Code history is shared. Stop the old turn before resuming elsewhere.' if bucket else
                       'Sign in and open Code once, then use Refresh Code history.'}


def remote_control_blocked(config=None):
    settings = read_json((config or MASTER_CLI) / 'settings.json')
    return settings.get('disableRemoteControl') is True


def require_local_history_privacy(profile, *, terminal=False):
    if not requires_remote_control_block(profile):
        return
    config = paths(profile)[1] if terminal else desktop_code_config(profile)
    if not remote_control_blocked(config):
        raise ProfileError(f"{profile['name']} is a protected shared-account profile. It requires "
                           f'disableRemoteControl: true in {config / "settings.json"}. '
                           'Remote Control can expose local conversations to other devices '
                           'signed into the same account. Model requests still go to Anthropic.')
    if not terminal and not desktop_runtime_matches(profile):
        raise ProfileError(f"Restart {profile['name']} from SessionPier before continuing. "
                           'Its running app was not launched with the protected settings directory.')


def sync_code_history(profile):
    if profile.get('historySharingEnabled') is False:
        return {'copied': 0, 'updated': 0, 'setupRequired': False, 'sharingDisabled': True,
                'message': 'Local history sharing is off for this account.'}
    require_local_history_privacy(profile)
    if desktop_pids(profile):
        raise ProfileError(f"Quit the {profile['name']} Claude instance before refreshing its Code history.")
    bucket = session_bucket(profile)
    if bucket is None:
        return {'copied': 0, 'updated': 0, 'setupRequired': True,
                'message': 'Sign in and open Code once, then refresh Code history.'}
    catalog, skipped = session_catalog()
    bucket.mkdir(parents=True, exist_ok=True, mode=0o700)
    journal = ROOT / 'history-backups' / now() / profile['id']
    copied, updated = 0, 0
    changes = []
    for sid, record in catalog.items():
        destination = bucket / (sid + '.json')
        source = Path(record['source'])
        if destination == source:
            continue
        row = record['row']
        if destination.exists():
            previous = read_json(destination)
            if activity(previous) >= activity(row):
                continue
            # Preserve destination account permissions and integration choices.
            merged = dict(previous)
            merged.update({k: v for k, v in row.items() if k != 'permissionMode'})
        else:
            # Do not resurrect archived sessions in another account.
            if row.get('isArchived'):
                continue
            merged = row
        if hashlib.sha256(source.read_bytes()).hexdigest() != record['sha256']:
            skipped += 1
            continue
        # Recheck immediately before writing; the destination must stay closed.
        if desktop_pids(profile):
            raise ProfileError('The destination profile opened during history refresh. Close it and try again.')
        journal.mkdir(parents=True, exist_ok=True, mode=0o700)
        existed = destination.exists()
        if existed:
            shutil.copy2(destination, journal / destination.name)
        changes.append({'path': str(destination), 'created': not existed,
                        'backup': str(journal / destination.name) if existed else None})
        write_json(journal / 'changes.json', {'changes': changes})
        write_json(destination, merged)
        updated += int(existed)
        copied += int(not existed)
    return {'copied': copied, 'updated': updated, 'skipped': skipped, 'setupRequired': False}


def rebase_plugin_paths(value, cli):
    if isinstance(value, str):
        prefix = str(MASTER_CLI / 'plugins') + '/'
        if value.startswith(prefix):
            return str(cli / 'plugins') + '/' + value[len(prefix):]
    if isinstance(value, dict):
        return {k: rebase_plugin_paths(v, cli) for k, v in value.items()}
    if isinstance(value, list):
        return [rebase_plugin_paths(v, cli) for v in value]
    return value


def sync_profile(profile, files=None):
    if profile['default']:
        return {'profile': profile['name'], 'changed': 0, 'conflicts': [], 'skipped': 'Source profile'}
    if desktop_pids(profile) or cli_running(profile):
        return {'profile': profile['name'], 'changed': 0, 'conflicts': [],
                'skipped': 'Close this profile’s Desktop and Code sessions before syncing.'}
    desk, cli = paths(profile)
    link_shared_history(profile)
    base = cli.parent
    manifest_path = base / 'shared-manifest.json'
    manifest = read_json(manifest_path, {'files': {}, 'mcp': {}})
    previous = manifest.get('files', {})
    updated = dict(previous)
    conflicts = []
    changes = 0
    backup = base / 'backups' / now()
    files = shared_files() if files is None else files
    for relative, source in {**files, 'settings.json': None}.items():
        target = cli / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if source is None:
            content = (json.dumps(sanitized_settings(profile), indent=2) + '\n').encode()
        elif relative in ('plugins/installed_plugins.json', 'plugins/known_marketplaces.json'):
            content = (json.dumps(rebase_plugin_paths(read_json(source), cli), indent=2) + '\n').encode()
        else:
            content = source.read_bytes()
        wanted = hashlib.sha256(content).hexdigest()
        current = fingerprint(target)
        if source is None and not target.is_symlink() and current is not None:
            if read_json(target) == sanitized_settings(profile):
                # Key order/formatting is not a profile-specific settings edit.
                updated[relative] = current
                continue
        if target.is_symlink() or (current is not None and current not in {previous.get(relative), wanted}):
            conflicts.append(relative)
            continue
        if current != wanted:
            if current is not None:
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(target, saved)
            fd, temp = tempfile.mkstemp(dir=target.parent, prefix='.sync-')
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
            os.chmod(temp, 0o700 if source and os.access(source, os.X_OK) else 0o600)
            os.replace(temp, target)
            changes += 1
        updated[relative] = wanted
    # Removed definitions are archived only if the profile has not edited them.
    for relative, old_hash in previous.items():
        if relative in files or relative == 'settings.json':
            continue
        target = cli / relative
        if target.is_file() and fingerprint(target) == old_hash:
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.move(target, saved)
            changes += 1
            updated.pop(relative, None)
        elif target.exists():
            conflicts.append(relative)
    # Merge only the MCP field, preserving account state and local MCP additions.
    for kind, source, target in [
        ('desktop', MASTER_DESKTOP / 'claude_desktop_config.json', desk / 'claude_desktop_config.json'),
        ('cli', HOME / '.claude.json', cli / '.claude.json'),
    ]:
        wanted = read_json(source).get('mcpServers', {})
        if not isinstance(wanted, dict):
            raise ProfileError(f'Invalid mcpServers at {source}')
        current = read_json(target)
        servers = dict(current.get('mcpServers', {}))
        old = manifest.get('mcp', {}).get(kind, {})
        managed = dict(old)
        for name in set(old) | set(wanted):
            if name in servers and name in wanted and servers[name] == wanted[name]:
                managed[name] = wanted[name]
            elif name not in servers or servers.get(name) == old.get(name):
                if name in wanted:
                    servers[name] = wanted[name]
                    managed[name] = wanted[name]
                else:
                    servers.pop(name, None)
                    managed.pop(name, None)
            else:
                conflicts.append(f'{kind} MCP: {name}')
        if servers != current.get('mcpServers', {}) or not target.exists():
            if target.exists():
                saved = backup / f'{kind}-config.json'
                saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(target, saved)
            current['mcpServers'] = servers
            write_json(target, current)
            changes += 1
        manifest.setdefault('mcp', {})[kind] = managed
    manifest.update(files=updated, syncedAt=now())
    write_json(manifest_path, manifest)
    return {'profile': profile['name'], 'changed': changes, 'conflicts': conflicts}


def create(name, default=False, *, share_history=True, shared=True):
    key = slug(name)
    data = registry()
    if any(p['id'] == key for p in data['profiles']):
        raise ProfileError(f'Profile already exists: {name}')
    if default and any(p['default'] for p in data['profiles']):
        raise ProfileError('The existing Claude setup already has a profile name.')
    profile = {'id': key, 'name': name.strip(), 'default': default, 'createdAt': now(),
               'remoteControlPolicy': 'blocked' if shared else 'allowed', 'historySharingEnabled': share_history}
    desk, cli = paths(profile)
    if not default:
        if cli.parent.exists():
            raise ProfileError(f'A data directory already exists at {cli.parent}. It was left untouched.')
        desk.mkdir(parents=True, mode=0o700)
        cli.mkdir(mode=0o700)
        sync_profile(profile)
    data['profiles'].append(profile)
    write_json(ROOT / 'profiles.json', data)
    return profile


def open_desktop(profile):
    require_local_history_privacy(profile)
    if not CLAUDE_APP.exists():
        raise ProfileError('Claude.app was not found in /Applications.')
    running = desktop_pids(profile)
    helper = APP / 'Contents/MacOS/SessionPier'
    if running:
        subprocess.run([str(helper), '--activate-pid', str(running[0])], check=True)
        return f"Switched to {profile['name']}."
    with locked():
        outcome = sync_profile(profile)
        history = sync_code_history(profile)
    desk, _ = paths(profile)
    arguments = [str(helper), '--launch-desktop']
    if not profile['default']:
        arguments += ['--user-data-dir=' + str(desk)]
    subprocess.run(arguments, env=clean_env(profile, desktop=True), check=True)
    for _ in range(24):
        if desktop_pids(profile):
            break
        time.sleep(0.25)
    else:
        raise ProfileError('Claude did not stay running. Check this profile’s desktop/Logs folder.')
    record_desktop_runtime(profile, desktop_pids(profile)[0])
    detail = ' Local setting edits were preserved; run doctor to review.' if outcome.get('conflicts') else ''
    history_note = (f" {history['copied']} local Code sessions added; {history['updated']} refreshed."
                    if not history['setupRequired'] else ' Sign in, open Code, then refresh Code history.')
    return f"Opened {profile['name']}.{history_note}{detail}"


def refresh_history(profile, require_login=True):
    if require_login and session_bucket(profile) is None:
        raise ProfileError('Sign into this Desktop profile and open its Code tab first, then refresh Code history.')
    helper = APP / 'Contents/MacOS/SessionPier'
    for pid in desktop_pids(profile):
        subprocess.run([str(helper), '--quit-pid', str(pid)], check=True)
    for _ in range(40):
        if not desktop_pids(profile):
            return open_desktop(profile)
        time.sleep(0.25)
    raise ProfileError('Claude is still open, perhaps waiting for confirmation. Finish closing this profile, then open it from the picker.')


def prepare_login(profile):
    """Only the destination may receive Claude's shared macOS OAuth callback."""
    require_local_history_privacy(profile)
    helper = APP / 'Contents/MacOS/SessionPier'
    others = [p for p in registry()['profiles'] if p['id'] != profile['id']]
    for other in others:
        for pid in desktop_pids(other):
            subprocess.run([str(helper), '--quit-pid', str(pid)], check=True)
    for _ in range(40):
        if not any(desktop_pids(p) for p in others):
            return refresh_history(profile, require_login=False)
        time.sleep(0.25)
    raise ProfileError('Another Claude window is waiting to quit. Finish its quit confirmation, '
                       'then try sign-in again. No processes were force-quit.')


def code(profile, arguments):
    with locked():
        outcome = sync_profile(profile)
    if outcome.get('conflicts'):
        print('Profile-specific edits kept: ' + ', '.join(outcome['conflicts'][:8]), file=sys.stderr)
    require_local_history_privacy(profile, terminal=True)
    removed = sorted(AUTH_ENV & os.environ.keys())
    if removed:
        print('Using profile login; ignored inherited credential overrides: ' + ', '.join(removed), file=sys.stderr)
    print(f"Claude Code · {profile['name']}", file=sys.stderr)
    os.execve(claude_binary(), ['claude', *arguments], clean_env(profile))


def terminal(profile, cwd):
    cwd = Path(cwd).expanduser().resolve()
    if not cwd.is_dir():
        raise ProfileError(f'Folder not found: {cwd}')
    path = ROOT / 'terminals' / f"Claude - {profile['name']}.command"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = shlex.join([str(HOME / '.local/bin/claude-profile'), 'code', profile['id']])
    path.write_text('#!/bin/zsh\ncd -- ' + shlex.quote(str(cwd)) + ' || exit 1\n' + command + '\n')
    path.chmod(0o700)
    subprocess.run(['/usr/bin/open', '-a', 'Terminal', str(path)], check=True)
    return f"Opened a {profile['name']} Code terminal."


def archive(profile):
    if profile['default']:
        raise ProfileError('Your original Claude setup cannot be archived with this tool.')
    if desktop_pids(profile) or cli_running(profile):
        raise ProfileError('Close this profile’s Desktop and Code sessions before archiving.')
    data = registry()
    destination = ROOT / 'archive' / f"{profile['id']}-{now()}"
    destination.mkdir(parents=True, mode=0o700)
    _, cli = paths(profile)
    shutil.move(cli.parent, destination / 'profile')
    write_json(destination / 'profile.json', profile)
    data['profiles'] = [p for p in data['profiles'] if p['id'] != profile['id']]
    write_json(ROOT / 'profiles.json', data)
    return f'Archived locally at {destination}. Keychain entries were left intact.'


def restore(name):
    key = slug(name)
    data = registry()
    if any(p['id'] == key for p in data['profiles']):
        raise ProfileError('A profile with this name is already active.')
    matches = sorted((ROOT / 'archive').glob(key + '-*'), reverse=True)
    if not matches:
        raise ProfileError(f'No archived profile named {name}.')
    saved = matches[0]
    profile = read_json(saved / 'profile.json')
    _, cli = paths(profile)
    if cli.parent.exists():
        raise ProfileError('The original profile directory is occupied; nothing was replaced.')
    shutil.move(saved / 'profile', cli.parent)
    data['profiles'].append(profile)
    write_json(ROOT / 'profiles.json', data)
    return f"Restored {profile['name']} to its original paths."


def list_profiles():
    result = []
    for p in registry()['profiles']:
        desk, cli = paths(p)
        config = HOME / '.claude.json' if p['default'] else cli / '.claude.json'
        account = read_json(config).get('oauthAccount') or {}
        pids = desktop_pids(p)
        result.append({**p, 'desktopRunning': bool(pids), 'desktopPID': pids[0] if pids else None,
                       'desktopPath': str(desk), 'cliPath': str(cli),
                       'codeEmail': account.get('emailAddress', ''),
                       'desktopLoginSaved': desktop_login_saved(p),
                       'usage': usage_snapshot(p),
                       'remoteControlBlocked': remote_control_blocked(desktop_code_config(p)),
                       'requiresRemoteControlBlock': requires_remote_control_block(p),
                       'desktopRuntimeMatches': desktop_runtime_matches(p),
                       'historyReady': session_bucket(p) is not None})
    return result


def doctor():
    rows = []
    for profile in registry()['profiles']:
        desk, cli = paths(profile)
        completed = subprocess.run([claude_binary(), 'auth', 'status'], env=clean_env(profile),
                                   capture_output=True, text=True, timeout=20, cwd=HOME)
        try:
            auth = json.loads(completed.stdout)
        except ValueError:
            auth = {}
        rows.append({'profile': profile['name'], 'desktopRunning': bool(desktop_pids(profile)),
                     'desktopLoginSaved': desktop_login_saved(profile),
                     'historyReady': session_bucket(profile) is not None,
                     'remoteControlBlocked': remote_control_blocked(desktop_code_config(profile)),
                     'requiresRemoteControlBlock': requires_remote_control_block(profile),
                     'desktopRuntimeMatches': desktop_runtime_matches(profile),
                     'desktopCodeConfig': str(desktop_code_config(profile)),
                     'cliSignedIn': auth.get('loggedIn'), 'cliEmail': auth.get('email'),
                     'cliConfigMatches': auth.get('configDirectory') == str(cli),
                     'desktopDataPresent': desk.is_dir(),
                     'sharedFiles': len(read_json(cli.parent / 'shared-manifest.json').get('files', {})) if not profile['default'] else 'source',
                     'pickerPresent': APP.is_dir()})
    return {'profiles': rows, 'inheritedAuthOverrides': sorted(AUTH_ENV & os.environ.keys()),
            'sharedLocalCodeHistory': {'path': str(MASTER_CLI / 'projects'),
                                       'availableDesktopSessions': len(session_catalog()[0])},
            'note': 'Shared-account profiles require a Remote Control block. Owned accounts may connect individual sessions. Model requests still go to Anthropic. Desktop account identity must be checked in its account menu.'}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    new = sub.add_parser('new', help='Create an empty isolated account profile')
    new.add_argument('name')
    new.add_argument('--existing', action='store_true', help='Name the existing Claude setup')
    sub.add_parser('list').add_argument('--json', action='store_true')
    sub.add_parser('sync')
    sub.add_parser('doctor')
    sub.add_parser('gui')
    for cmd in ('open', 'code', 'terminal', 'archive', 'restore', 'history-status', 'sync-history', 'refresh-history', 'restart-desktop', 'prepare-login'):
        p = sub.add_parser(cmd)
        p.add_argument('name')
        if cmd == 'code':
            p.add_argument('args', nargs=argparse.REMAINDER)
        if cmd == 'terminal':
            p.add_argument('--cwd', default=str(HOME / 'Code/machine_house'))
        if cmd == 'archive':
            p.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'new':
            with locked():
                result = create(args.name, args.existing)
            print(f"Created {result['name']}.")
        elif args.command == 'list':
            rows = list_profiles()
            print(json.dumps(rows) if args.json else '\n'.join(
                f"{p['id']:16} {p['name']}" + (' (existing setup)' if p['default'] else '') for p in rows))
        elif args.command == 'sync':
            with locked():
                files = shared_files()
                print(json.dumps([sync_profile(p, files) for p in registry()['profiles']], indent=2))
        elif args.command == 'open':
            print(open_desktop(get_profile(args.name)))
        elif args.command == 'code':
            code(get_profile(args.name), args.args)
        elif args.command == 'terminal':
            print(terminal(get_profile(args.name), args.cwd))
        elif args.command == 'history-status':
            print(json.dumps(history_status(get_profile(args.name)), indent=2))
        elif args.command == 'sync-history':
            with locked():
                print(json.dumps(sync_code_history(get_profile(args.name)), indent=2))
        elif args.command == 'refresh-history':
            print(refresh_history(get_profile(args.name)))
        elif args.command == 'restart-desktop':
            print(refresh_history(get_profile(args.name), require_login=False))
        elif args.command == 'prepare-login':
            print(prepare_login(get_profile(args.name)))
        elif args.command == 'archive':
            if not args.yes:
                raise ProfileError('Archive keeps data recoverable. Repeat with --yes to confirm.')
            with locked():
                print(archive(get_profile(args.name)))
        elif args.command == 'restore':
            with locked():
                print(restore(args.name))
        elif args.command == 'doctor':
            print(json.dumps(doctor(), indent=2))
        elif args.command == 'gui':
            subprocess.run(['/usr/bin/open', str(APP)], check=True)
    except (ProfileError, OSError, subprocess.SubprocessError) as exc:
        print(f'claude-profile: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
