"""Build a portable Mac companion and keep only one installed app."""
from pathlib import Path
import argparse
import datetime as dt
import json
import os
import plistlib
import platform
import shlex
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
APP_ID = 'house.machine.claude-accounts'
APP_NAME = 'SessionPier'
VERSION = '2.0.0'
APP = HOME / 'Applications' / f'{APP_NAME}.app'
LSREGISTER = Path('/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister')


def managed_app(path):
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        info = plistlib.loads((path / 'Contents/Info.plist').read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False
    if info.get('CFBundleIdentifier') == APP_ID:
        return True
    profile = info.get('ClaudeProfileID')
    return isinstance(profile, str) and bool(profile) and info.get('CFBundleIdentifier') == f'house.machine.claude-profile.{profile}'


def zip_app(path, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError(f'Archive already exists: {target}')
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(path), str(target)], check=True)
    with zipfile.ZipFile(target) as saved:
        if saved.testzip() is not None or f'{path.name}/Contents/Info.plist' not in saved.namelist():
            raise RuntimeError(f'Archive verification failed: {target}')


def archive_app(path, folder):
    if not managed_app(path):
        raise RuntimeError(f'Refusing to archive an unrelated app: {path}')
    target = folder / f'{path.stem}.zip'
    zip_app(path, target)
    if LSREGISTER.exists():
        subprocess.run([str(LSREGISTER), '-u', str(path)], capture_output=True, check=False)
    shutil.rmtree(path)
    return {'original': str(path), 'archive': str(target)}


def python_runtime():
    uv = shutil.which('uv')
    if not uv:
        raise RuntimeError('Install uv to build the app. Installed apps do not need uv.')
    found = subprocess.run([uv, 'python', 'find', '--managed-python', '3.13'], capture_output=True, text=True)
    if found.returncode:
        subprocess.run([uv, 'python', 'install', '3.13'], check=True)
        found = subprocess.run([uv, 'python', 'find', '--managed-python', '3.13'], check=True, capture_output=True, text=True)
    executable = Path(found.stdout.strip()).resolve()
    root = executable.parent.parent
    if not (root / 'lib').is_dir():
        raise RuntimeError('The managed Python runtime layout is not supported.')
    return root


def build_app(build, runtime):
    binary = build / 'Contents/MacOS/SessionPier'
    resources = build / 'Contents/Resources'
    binary.parent.mkdir(parents=True)
    resources.mkdir(parents=True)
    sources = [ROOT / 'src' / name for name in ('Accounts.swift', 'CompanionModel.swift', 'CompanionViews.swift')]
    subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-target', platform.machine() + '-apple-macosx13.0', '-parse-as-library', '-O',
                    *map(str, sources), '-o', str(binary)], check=True)
    info = {'CFBundleIdentifier': APP_ID, 'CFBundleName': APP_NAME,
            'CFBundleDisplayName': APP_NAME, 'CFBundleExecutable': 'SessionPier',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': VERSION,
            'CFBundleVersion': '6', 'CFBundleIconFile': 'Accounts.icns',
            'NSHighResolutionCapable': True, 'LSMinimumSystemVersion': '13.0',
            'NSHumanReadableCopyright': 'Independent companion. Not affiliated with Anthropic or OpenAI.'}
    (build / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    iconset = build.parent / 'Accounts.iconset'
    subprocess.run(['xcrun', 'swift', str(ROOT / 'scripts/generate_icon.swift'), str(iconset)], check=True)
    subprocess.run(['/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o', str(resources / 'Accounts.icns')], check=True)
    backend = resources / 'backend'
    backend.mkdir()
    for name in ('claude_profile.py', 'usage_service.py', 'companion.py'):
        shutil.copy2(ROOT / 'src' / name, backend / name)
    shutil.copytree(runtime, resources / 'runtime', symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (resources / 'backend.json').write_text(json.dumps({'python': 'runtime/bin/python3', 'backend': 'backend'}, indent=2) + '\n')
    demo = ROOT / 'tests/fixtures/demo-snapshot.json'
    if demo.exists():
        shutil.copy2(demo, resources / 'demo-snapshot.json')
    for name in ('LICENSE', 'THIRD-PARTY-NOTICES.md'):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, resources / name)
    shutil.copytree(ROOT / 'licenses', resources / 'licenses')
    # The managed runtime is relocatable. Check its interpreter before shipping.
    result = subprocess.run([str(resources / 'runtime/bin/python3'), '-I', '-B', '-c',
                             'import json,sqlite3,ssl,zoneinfo,pty; print("runtime-ok")'],
                            capture_output=True, text=True, check=True)
    if result.stdout.strip() != 'runtime-ok':
        raise RuntimeError('Bundled runtime validation failed.')
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(build)], check=True)
    # Import the shipped backend after signing: execution must not add bytecode
    # caches to sealed resources. All runtime entrypoints also use -B.
    subprocess.run([str(resources / 'runtime/bin/python3'), '-B', '-c',
                    'import sys; sys.path.insert(0, sys.argv[1]); import companion, usage_service, claude_profile',
                    str(backend)], cwd=build.parent, check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(build)], check=True)


def wrappers():
    resources = APP / 'Contents/Resources'
    command = [str(resources / 'runtime/bin/python3'), '-B', str(resources / 'backend/claude_profile.py')]
    header = '#!/bin/sh\n# Managed by machine_house/claude-profile\nexport COMPANION_APP_BUNDLE=' + shlex.quote(str(APP)) + '\n'
    return {
        'claude-profile': header + 'exec ' + shlex.join(command) + ' "$@"\n',
        'cla': header + 'if [ "$#" -eq 0 ]; then\n  exec ' + shlex.quote(str(HOME / '.local/bin/claude-profile')) + ' gui\nfi\nexec ' + shlex.quote(str(HOME / '.local/bin/claude-profile')) + ' code "$@"\n',
    }


def install(package=None):
    if APP.exists() and not managed_app(APP):
        raise RuntimeError(f'Unrelated app exists; refusing to replace {APP}')
    bin_dir = HOME / '.local/bin'
    if not package:
        for name in wrappers():
            path = bin_dir / name
            if path.exists() and 'Managed by machine_house/claude-profile' not in path.read_text():
                raise RuntimeError(f'An unrelated {path} already exists; it was left untouched.')
    runtime = python_runtime()
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    archives = ROOT / 'build/app-archives.noindex' / stamp
    archived = []
    APP.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.claude-accounts-build-', suffix='.noindex', dir=APP.parent) as temp:
        build = Path(temp) / APP.name
        build_app(build, runtime)
        if package:
            target = Path(package).expanduser().resolve()
            zip_app(build, target)
            print(f'Packaged {target}. The installed app was not changed.')
            return
        if APP.exists():
            archived.append(archive_app(APP, archives / 'replaced'))
        build.rename(APP)
    candidates = [HOME / 'Applications/Claude Accounts.app', ROOT / 'build/Claude Accounts.app']
    candidates.extend(sorted((ROOT / 'build/previous').glob('*/Claude Accounts.app')))
    candidates.extend(sorted(APP.parent.glob('Claude - *.app')))
    for index, path in enumerate(candidates):
        if managed_app(path):
            archived.append(archive_app(path, archives / f'legacy-{index:03d}'))
    if archived:
        (archives / 'manifest.json').write_text(json.dumps(archived, indent=2) + '\n')
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, content in wrappers().items():
        path = bin_dir / name
        path.write_text(content)
        path.chmod(0o755)
    if LSREGISTER.exists():
        subprocess.run([str(LSREGISTER), '-f', str(APP)], check=True, capture_output=True)
    print(f'Installed {APP} ({VERSION}) with its own runtime and backend.')
    print(f'Archived {len(archived)} outgoing app bundles in {archives}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', metavar='ZIP', help='Build a release ZIP without replacing the installed app')
    args = parser.parse_args()
    install(args.package)
