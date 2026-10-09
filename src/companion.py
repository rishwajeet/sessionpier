#!/usr/bin/env python3
"""Native companion backend. Public JSON contains status, never credentials."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import fcntl
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

import claude_profile as p
import usage_service as usage

STATE = p.ROOT / 'companion'
DEFAULT_SETTINGS = {'version': 1, 'refreshSeconds': 300, 'notificationsEnabled': False,
                    'showDockIcon': True, 'globalShortcutEnabled': True, 'launchAtLogin': False}


def read(path, fallback=None):
    try:
        return p.read_json(path, fallback)
    except p.ProfileError:
        return {} if fallback is None else fallback


def settings():
    result = {**DEFAULT_SETTINGS, **read(STATE / 'settings.json')}
    if result.get('refreshSeconds') not in (60, 300, 900):
        result['refreshSeconds'] = 300
    for key in ('notificationsEnabled', 'showDockIcon', 'globalShortcutEnabled', 'launchAtLogin'):
        result[key] = result.get(key) is True
    return result


def find_binary(name):
    path = shutil.which(name)
    if path:
        return path
    for base in (p.HOME / '.local/bin', Path('/opt/homebrew/bin'), Path('/usr/local/bin')):
        candidate = base / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def codex_accounts():
    rows = read(STATE / 'codex-accounts.json', {'accounts': []}).get('accounts', [])
    valid = [row for row in rows if isinstance(row, dict) and isinstance(row.get('id'), str)
             and row['id'].startswith('codex-') and p.slug(row['id']) == row['id']]
    if find_binary('codex') and not any(row['id'] == 'codex-current' for row in valid):
        valid.insert(0, {'id': 'codex-current', 'name': 'Codex', 'default': True})
    return valid


def codex_home(row):
    return p.HOME / '.codex' if row.get('default') else STATE / 'codex' / row['id']


def cache_file(identifier):
    if not identifier or p.slug(identifier) != identifier:
        raise p.ProfileError('Invalid account identifier.')
    return STATE / 'usage' / f'{identifier}.json'


@contextlib.contextmanager
def account_lock(identifier):
    folder = STATE / 'locks'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / f'{identifier}.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def native_profiles():
    return p.registry()['profiles']


def lookup(identifier):
    for row in native_profiles():
        if identifier == 'claude-' + row['id']:
            return 'claude', row
    for row in codex_accounts():
        if identifier == row['id']:
            return 'codex', row
    raise p.ProfileError('Account not found.')


def normalize_cache(value, clock):
    sample = value.get('sample')
    if not isinstance(sample, dict):
        return None
    timestamp = sample.get('sampledAt')
    if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or not 0 < timestamp <= clock + 60:
        return None
    meters = [m for m in sample.get('meters', []) if isinstance(m, dict)
              and isinstance(m.get('id'), str) and isinstance(m.get('label'), str)
              and usage.percent(m.get('usedPercent')) is not None]
    if not meters:
        return None
    age = max(0, int(clock - timestamp))
    stale = age > max(600, settings()['refreshSeconds'] * 2)
    return {**sample, 'meters': meters, 'ageSeconds': age, 'stale': stale,
            'status': 'cached' if stale or value.get('error') else 'live'}


def usage_for_claude(profile, cached, clock):
    result = normalize_cache(cached, clock)
    # Binding failure invalidates old live values, even when their clock is fresh.
    if result:
        try:
            identity = usage.claude_identity(profile)
            actual = usage.identity_key({k: identity[k] for k in ('accountId', 'organizationId')})
            if actual != result.get('identityKey') or (cached.get('error') or {}).get('code') in ('identity_mismatch', 'identity_changed', 'login_required'):
                result = None
        except usage.UsageError:
            result = None
    if result:
        return result
    fallback = p.usage_snapshot(profile, clock=clock)
    if fallback['status'] == 'snapshot':
        meters = []
        for row in fallback['meters']:
            if row['id'] not in ('fh', 'sd', 'so', 'sn'):
                continue
            meters.append({'id': row['id'], 'label': {'fh': 'Session', 'sd': 'Weekly', 'so': 'Opus weekly', 'sn': 'Sonnet weekly'}[row['id']],
                           'usedPercent': row['usedPercent'], 'windowMinutes': 300 if row['id'] == 'fh' else 10080,
                           'resetsAt': None, 'resetDescription': None})
        return {'status': 'snapshot', 'source': 'Claude Desktop snapshot', 'sampledAt': fallback['sampledAt'],
                'ageSeconds': fallback['ageSeconds'], 'stale': True, 'meters': meters}
    return {'status': 'unavailable', 'source': None, 'sampledAt': None, 'ageSeconds': None, 'stale': True, 'meters': []}


def connection_for_claude(row, cache):
    try:
        usage.claude_identity(row)
    except usage.UsageError as exc:
        return {'state': exc.code, 'message': str(exc)}
    error = cache.get('error') or {}
    if error:
        return {'state': error.get('code', 'refresh_failed'), 'message': error.get('message', 'Could not refresh usage.')}
    if not cache.get('sample'):
        return {'state': 'not_checked', 'message': 'Live usage has not been checked yet.'}
    return {'state': 'connected', 'message': 'Live usage connected'}


def snapshot():
    clock = time.time()
    rows = []
    for profile in native_profiles():
        identifier = 'claude-' + profile['id']
        desk, cli = p.paths(profile)
        cached = read(cache_file(identifier))
        current = usage_for_claude(profile, cached, clock)
        identity = current.get('identity') or {}
        running = p.desktop_pids(profile)
        rows.append({'id': identifier, 'profileId': profile['id'], 'name': profile['name'],
                     'provider': 'claude', 'providerLabel': 'Claude', 'default': profile['default'],
                     'email': identity.get('email', ''), 'plan': identity.get('plan', ''),
                     'desktopRunning': bool(running), 'desktopPID': running[0] if running else None,
                     'desktopLoginSaved': p.desktop_login_saved(profile),
                     'historyReady': p.session_bucket(profile) is not None,
                     'historySharingEnabled': profile.get('historySharingEnabled', True),
                     'remoteControlBlocked': p.remote_control_blocked(p.desktop_code_config(profile)),
                     'requiresRemoteControlBlock': p.requires_remote_control_block(profile),
                     'desktopRuntimeMatches': p.desktop_runtime_matches(profile),
                     'desktopPath': str(desk), 'cliPath': str(cli),
                     'connection': connection_for_claude(profile, cached), 'usage': current,
                     'lastAttemptAt': cached.get('lastAttemptAt'), 'nextAttemptAt': cached.get('nextAttemptAt')})
    for row in codex_accounts():
        cached = read(cache_file(row['id']))
        current = normalize_cache(cached, clock)
        error = cached.get('error') or {}
        if error.get('code') in ('login_required', 'identity_changed'):
            current = None
        identity = (current or {}).get('identity') or {}
        rows.append({'id': row['id'], 'profileId': row['id'], 'name': row['name'],
                     'provider': 'codex', 'providerLabel': 'ChatGPT · Codex', 'default': row.get('default', False),
                     'email': identity.get('email', ''), 'plan': identity.get('plan', ''),
                     'desktopRunning': False, 'desktopPID': None,
                     'desktopLoginSaved': bool(current), 'historyReady': False, 'historySharingEnabled': False,
                     'remoteControlBlocked': False, 'requiresRemoteControlBlock': False, 'desktopRuntimeMatches': True,
                     'desktopPath': str(codex_home(row)), 'cliPath': str(codex_home(row)),
                     'connection': {'state': error.get('code', 'connected' if current else 'not_checked'),
                                    'message': error.get('message', 'Live usage connected' if current else 'Connect through the official Codex client.')},
                     'usage': current or {'status': 'unavailable', 'source': None, 'sampledAt': None,
                                         'ageSeconds': None, 'stale': True, 'meters': []},
                     'lastAttemptAt': cached.get('lastAttemptAt'), 'nextAttemptAt': cached.get('nextAttemptAt')})
    return {'version': 2, 'generatedAt': clock, 'settings': settings(), 'accounts': rows,
            'clients': {'claudeAvailable': find_binary('claude') is not None, 'codexAvailable': find_binary('codex') is not None}}


def refresh_one(identifier, force=False, fetchers=None):
    provider, profile = lookup(identifier)
    with account_lock(identifier) as acquired:
        if not acquired:
            return
        path = cache_file(identifier)
        previous = read(path)
        clock = time.time()
        since_attempt = clock - previous.get('lastAttemptAt', 0)
        # Manual clicks still cannot hammer a failed endpoint or overlap a probe.
        if since_attempt < (15 if force else 0) or (not force and previous.get('nextAttemptAt', 0) > clock):
            return
        saved = {**previous, 'lastAttemptAt': clock}
        interval = settings()['refreshSeconds']
        try:
            if fetchers and provider in fetchers:
                sample = fetchers[provider](profile)
            elif provider == 'claude':
                sample = usage.read_claude(profile)
            else:
                binary = find_binary('codex')
                if not binary:
                    raise usage.UsageError('client_missing', 'Install the official Codex CLI to connect this account.')
                sample = usage.read_codex(binary, codex_home(profile))
            saved.update(sample=sample, error=None, failures=0, nextAttemptAt=time.time() + interval)
            history = previous.get('history', []) if previous.get('sample', {}).get('identityKey') == sample['identityKey'] else []
            record = {'at': sample['sampledAt'], 'values': {m['id']: m['usedPercent'] for m in sample['meters']}}
            saved['history'] = ([r for r in history if r.get('at', 0) > clock - 7 * 86400] + [record])[-2016:]
        except (usage.UsageError, subprocess.SubprocessError, OSError, ValueError, p.ProfileError) as exc:
            failures = min(10, previous.get('failures', 0) + 1)
            code = exc.code if isinstance(exc, usage.UsageError) else 'refresh_failed'
            message = str(exc) if isinstance(exc, usage.UsageError) else 'The native client could not refresh usage. Check the connection and try again.'
            wait = 900 if code in ('login_required', 'identity_mismatch', 'desktop_setup', 'setup_required', 'client_missing') else min(3600, max(interval, 60) * (2 ** (failures - 1)))
            saved.update(error={'code': code, 'message': message}, failures=failures, nextAttemptAt=time.time() + wait)
        p.write_json(path, saved)


def refresh(identifier=None, force=False):
    ids = [identifier] if identifier else ['claude-' + r['id'] for r in native_profiles()] + [r['id'] for r in codex_accounts()]
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda key: refresh_one(key, force), ids))
    return snapshot()


def terminal_command(identifier, operation, cwd=None):
    lookup(identifier)
    args = ['/usr/bin/env', 'COMPANION_APP_BUNDLE=' + str(p.APP), sys.executable, '-B', str(Path(__file__).resolve()), operation, identifier]
    if cwd:
        args += ['--cwd', str(Path(cwd).expanduser().resolve())]
    folder = STATE / 'terminals'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / f'{identifier}-{operation}.command'
    target.write_text('#!/bin/zsh\n' + shlex.join(args) + '\n')
    target.chmod(0o700)
    subprocess.run(['/usr/bin/open', '-a', 'Terminal', str(target)], check=True)


def login_run(identifier):
    provider, row = lookup(identifier)
    if provider == 'claude':
        binary = p.claude_binary()
        env = p.clean_env(row)
        args = [binary, 'auth', 'login', '--claudeai']
    else:
        binary = find_binary('codex')
        if not binary:
            raise p.ProfileError('Install the official Codex CLI first.')
        home = codex_home(row)
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = usage.codex_env(home)
        args = [binary, 'login']
    print(f"Connect {row['name']} using the provider’s official sign-in. Return to SessionPier afterward.", flush=True)
    result = subprocess.run(args, env=env)
    if result.returncode == 0:
        # Native auth may have changed; allow the next explicit refresh immediately.
        cached = read(cache_file(identifier))
        cached.update(lastAttemptAt=0, nextAttemptAt=0)
        p.write_json(cache_file(identifier), cached)
        print('Sign-in complete. Return to SessionPier; live usage will update automatically.')
    return result.returncode


def setup_run(identifier):
    provider, row = lookup(identifier)
    if provider != 'claude':
        return login_run(identifier)
    folder = p.ROOT / 'verification'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = p.clean_env(row)
    env.update(DISABLE_AUTOUPDATER='1', ENABLE_CLAUDEAI_MCP_SERVERS='false')
    binary = p.claude_binary()
    os.chdir(folder)
    os.execve(binary, [binary, '--safe-mode', '--strict-mcp-config', '--settings',
                      '{"disableAllHooks":true,"remoteControlAtStartup":false,"disableRemoteControl":true}',
                      '--tools', '', '/usage'], env)


def codex_run(identifier, cwd):
    provider, row = lookup(identifier)
    if provider != 'codex':
        raise p.ProfileError('Choose a Codex account.')
    binary = find_binary('codex')
    if not binary:
        raise p.ProfileError('Install the official Codex CLI first.')
    folder = Path(cwd).expanduser().resolve()
    if not folder.is_dir():
        raise p.ProfileError('Choose an existing project folder.')
    os.chdir(folder)
    os.execve(binary, [binary], usage.codex_env(codex_home(row)))


def add_account(provider, name, shared=False, share_history=False):
    with p.locked():
        if provider == 'claude':
            row = p.create(name, share_history=share_history, shared=shared)
            return 'claude-' + row['id']
        identifier = 'codex-' + p.slug(name)
        rows = codex_accounts()
        if any(row['id'] == identifier for row in rows):
            raise p.ProfileError('An account with that name already exists.')
        row = {'id': identifier, 'name': name.strip(), 'default': False}
        home = codex_home(row)
        if home.exists():
            raise p.ProfileError('This account folder already exists; choose another name.')
        home.mkdir(parents=True, mode=0o700)
        rows.append(row)
        p.write_json(STATE / 'codex-accounts.json', {'accounts': rows})
        return identifier


def main():
    os.umask(0o077)
    p.init_root()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('snapshot')
    refresh_parser = sub.add_parser('refresh')
    refresh_parser.add_argument('id', nargs='?')
    refresh_parser.add_argument('--force', action='store_true')
    for command in ('connect', 'setup', 'login-run', 'setup-run', 'open', 'refresh-history', 'terminal', 'codex-run', 'sign-in-desktop'):
        child = sub.add_parser(command)
        child.add_argument('id')
        child.add_argument('--cwd', default=str(p.HOME))
    pref = sub.add_parser('set-preference')
    pref.add_argument('key')
    pref.add_argument('value')
    add = sub.add_parser('add')
    add.add_argument('provider', choices=['claude', 'codex'])
    add.add_argument('name')
    add.add_argument('--shared', action='store_true')
    add.add_argument('--share-history', action='store_true')
    sub.add_parser('import-claude')
    sub.add_parser('sync')
    sub.add_parser('doctor')
    args = parser.parse_args()
    try:
        if args.command == 'snapshot':
            result = snapshot()
        elif args.command == 'refresh':
            result = refresh(args.id, args.force)
        elif args.command == 'set-preference':
            if args.key not in DEFAULT_SETTINGS or args.key == 'version':
                raise p.ProfileError('Unknown preference.')
            value = json.loads(args.value)
            if (args.key == 'refreshSeconds' and value not in (60, 300, 900)) or (args.key != 'refreshSeconds' and type(value) is not bool):
                raise p.ProfileError('Invalid preference value.')
            data = settings()
            data[args.key] = value
            p.write_json(STATE / 'settings.json', data)
            if args.key == 'refreshSeconds':
                for path in (STATE / 'usage').glob('*.json'):
                    with account_lock(path.stem) as acquired:
                        if not acquired:
                            continue
                        cached = read(path)
                        if not cached.get('error') and isinstance(cached.get('lastAttemptAt'), (int, float)):
                            cached['nextAttemptAt'] = cached['lastAttemptAt'] + value
                            p.write_json(path, cached)
            result = {'message': 'Preference saved'}
        elif args.command == 'add':
            result = {'id': add_account(args.provider, args.name, args.shared, args.share_history)}
        elif args.command == 'import-claude':
            with p.locked():
                row = p.create('Personal', default=True)
                data = p.registry()
                for item in data['profiles']:
                    if item['id'] == row['id']:
                        item['remoteControlPolicy'] = 'allowed'
                        item['historySharingEnabled'] = True
                p.write_json(p.ROOT / 'profiles.json', data)
            result = {'message': 'Imported the existing Claude Desktop profile.'}
        elif args.command == 'sign-in-desktop':
            provider, row = lookup(args.id)
            if provider != 'claude':
                raise p.ProfileError('Choose a Claude account.')
            result = {'message': p.prepare_login(row)}
        elif args.command == 'connect':
            terminal_command(args.id, 'login-run')
            result = {'message': 'Finish sign-in in the official client’s browser flow.'}
        elif args.command == 'setup':
            terminal_command(args.id, 'setup-run')
            result = {'message': 'Complete the native client’s setup, then return here.'}
        elif args.command == 'login-run':
            return login_run(args.id)
        elif args.command == 'setup-run':
            return setup_run(args.id)
        elif args.command == 'codex-run':
            return codex_run(args.id, args.cwd)
        elif args.command in ('open', 'refresh-history', 'terminal'):
            provider, row = lookup(args.id)
            if provider == 'codex':
                terminal_command(args.id, 'codex-run', args.cwd)
                result = {'message': f"Opened {row['name']} in the official Codex CLI."}
            elif args.command == 'open':
                result = {'message': p.open_desktop(row)}
            elif args.command == 'refresh-history':
                result = {'message': p.refresh_history(row)}
            else:
                result = {'message': p.terminal(row, args.cwd)}
        elif args.command == 'sync':
            with p.locked():
                files = p.shared_files()
                result = {'details': [p.sync_profile(row, files) for row in native_profiles()]}
        elif args.command == 'doctor':
            result = {'details': p.doctor()}
        else:
            result = {}
        print(json.dumps(result))
    except (p.ProfileError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
