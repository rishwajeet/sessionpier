import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('profiles', Path(__file__).parents[1] / 'src/claude_profile.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.patches = [
            patch.object(p, 'HOME', self.home),
            patch.object(p, 'ROOT', self.home / 'profiles root'),
            patch.object(p, 'MASTER_CLI', self.home / '.claude'),
            patch.object(p, 'MASTER_DESKTOP', self.home / 'desktop'),
            patch.object(p, 'desktop_pids', return_value=[]),
            patch.object(p, 'cli_running', return_value=False),
        ]
        for item in self.patches:
            item.start()
        p.init_root()
        p.MASTER_CLI.mkdir()
        p.MASTER_DESKTOP.mkdir()
        p.write_json(p.MASTER_CLI / 'settings.json', {
            'disableRemoteControl': True,
            'model': 'example-model', 'apiKeyHelper': 'PRIVATE-HELPER',
            'env': {'ANTHROPIC_API_KEY': 'SECRET-KEY', 'CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS': '1'}})
        p.write_json(self.home / '.claude.json', {
            'oauthAccount': {'emailAddress': 'personal@example.test'}, 'privateToken': 'PRIVATE-TOKEN',
            'mcpServers': {'example': {'command': 'test-mcp'}}})
        p.write_json(p.MASTER_DESKTOP / 'claude_desktop_config.json', {
            'preferences': {'personal': True}, 'mcpServers': {'desktop-mcp': {'command': 'mcp'}}})
        (p.MASTER_CLI / 'CLAUDE.md').write_text('Shared instructions')
        (p.MASTER_CLI / 'plugins/data').mkdir(parents=True)
        (p.MASTER_CLI / 'plugins/data/private.json').write_text('private plugin account data')
        p.write_json(p.MASTER_CLI / 'plugins/installed_plugins.json', {
            'version': 2, 'plugins': {'example': [{'installPath': str(p.MASTER_CLI / 'plugins/cache/example')}]}})
        self.work = p.create('Work')
        self.desk, self.cli = p.paths(self.work)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_credentials_and_identity_are_not_copied(self):
        content = (self.cli / '.claude.json').read_text()
        self.assertNotIn('oauthAccount', content)
        self.assertNotIn('PRIVATE-TOKEN', content)
        self.assertFalse((self.cli / 'plugins/data').exists())
        settings = p.read_json(self.cli / 'settings.json')
        self.assertNotIn('apiKeyHelper', settings)
        self.assertNotIn('ANTHROPIC_API_KEY', settings['env'])
        self.assertEqual(settings['env']['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'], '1')
        self.assertNotIn('preferences', p.read_json(self.desk / 'claude_desktop_config.json'))

    def test_profile_changes_and_account_state_survive_sync(self):
        state = p.read_json(self.cli / '.claude.json')
        state['oauthAccount'] = {'emailAddress': 'work@example.test'}
        state['mcpServers']['custom'] = {'command': 'profile-only'}
        p.write_json(self.cli / '.claude.json', state)
        (self.cli / 'settings.json').write_text('{"model":"local-choice"}')
        (p.MASTER_CLI / 'CLAUDE.md').write_text('Updated instructions')
        result = p.sync_profile(self.work)
        self.assertIn('settings.json', result['conflicts'])
        self.assertEqual(p.read_json(self.cli / 'settings.json')['model'], 'local-choice')
        self.assertEqual((self.cli / 'CLAUDE.md').read_text(), 'Updated instructions')
        self.assertEqual(p.read_json(self.cli / '.claude.json')['oauthAccount']['emailAddress'], 'work@example.test')
        self.assertIn('custom', p.read_json(self.cli / '.claude.json')['mcpServers'])
        self.assertTrue(list((self.cli.parent / 'backups').rglob('CLAUDE.md')))

    def test_idempotency_and_source_removal(self):
        self.assertEqual(p.sync_profile(self.work)['changed'], 0)
        (p.MASTER_CLI / 'CLAUDE.md').unlink()
        p.sync_profile(self.work)
        self.assertFalse((self.cli / 'CLAUDE.md').exists())
        self.assertTrue(list((self.cli.parent / 'backups').rglob('CLAUDE.md')))

    def test_separate_names_directories_and_environment(self):
        client = p.create('Client')
        self.assertNotEqual(p.paths(client), p.paths(self.work))
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'x', 'CLAUDE_CODE_OAUTH_TOKEN': 'y',
                                     'CLAUDE_SECURESTORAGE_CONFIG_DIR': 'wrong'}):
            env = p.clean_env(self.work, desktop=True)
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN', env)
        self.assertEqual(env.get('CLAUDE_CONFIG_DIR'), str(self.cli))
        self.assertNotIn('CLAUDE_SECURESTORAGE_CONFIG_DIR', env)
        self.assertEqual(env['CLAUDE_USER_DATA_DIR'], str(self.desk))
        terminal_env = p.clean_env(self.work)
        self.assertEqual(terminal_env['CLAUDE_CONFIG_DIR'], str(self.cli))
        self.assertEqual(terminal_env['CLAUDE_SECURESTORAGE_CONFIG_DIR'], str(self.cli))

    def test_terminal_history_points_at_original_files(self):
        transcript = p.MASTER_CLI / 'projects/example/session.jsonl'
        transcript.parent.mkdir()
        transcript.write_text('existing conversation\n')
        self.assertEqual((self.cli / 'projects/example/session.jsonl').resolve(), transcript.resolve())
        self.assertEqual((self.cli / 'projects/example/session.jsonl').read_text(), 'existing conversation\n')

    def test_history_opt_out_is_isolated_at_creation_and_resync(self):
        isolated = p.create('Isolated', share_history=False, shared=False)
        desk, cli = p.paths(isolated)
        self.assertEqual(p.desktop_code_config(isolated), cli)
        self.assertEqual(p.clean_env(isolated, desktop=True)['CLAUDE_CONFIG_DIR'], str(cli))
        for name in p.SHARED_HISTORY_DIRS:
            self.assertFalse((cli / name).is_symlink())
        p.sync_profile(isolated)
        for name in p.SHARED_HISTORY_DIRS:
            self.assertFalse((cli / name).is_symlink())
        self.assertTrue(p.sync_code_history(isolated)['sharingDisabled'])
        self.make_bucket(isolated, '99999999-9999-9999-9999-999999999999')
        source = desk / 'claude-code-sessions'
        # Opted-out sources must never be enumerated into the shared catalog.
        with patch.object(Path, 'glob', autospec=True) as glob:
            p.session_catalog()
            self.assertNotIn(source, [call.args[0] for call in glob.call_args_list])

    def make_bucket(self, profile, account='11111111-1111-1111-1111-111111111111'):
        desk, _ = p.paths(profile)
        p.write_json(desk / 'config.json', {'lastKnownAccountUuid': account})
        bucket = desk / 'claude-code-sessions' / account / '22222222-2222-2222-2222-222222222222'
        bucket.mkdir(parents=True)
        return bucket

    def usage_history(self, samples, version=2):
        p.write_json(self.desk / 'plan-usage-history.json', {'version': version, 'samples': samples})

    def test_usage_is_selected_by_profile_and_current_organization(self):
        bucket = self.make_bucket(self.work)
        self.usage_history([
            {'org': bucket.name, 't': 999_000, 'u': {'fh': 37, 'sd': 85}},
            {'org': 'other-org', 't': 1_000_000, 'u': {'fh': 0, 'sd': 0}},
            {'org': None, 't': 1_000_000, 'u': {'fh': 100}},
        ])
        with patch.object(p, 'desktop_login_saved', return_value=True):
            result = p.usage_snapshot(self.work, clock=1000)
        self.assertEqual([m['usedPercent'] for m in result['meters']], [37, 85])
        self.assertEqual(result['sampledAt'], 999)
        self.assertFalse(result['stale'])
        # It never consults a different profile's file or the Terminal account.
        client = p.create('Client')
        self.make_bucket(client, '33333333-3333-3333-3333-333333333333')
        with patch.object(p, 'desktop_login_saved', return_value=True):
            self.assertEqual(p.usage_snapshot(client, clock=1000)['status'], 'unavailable')

    def test_usage_missing_weekly_is_unknown_not_zero_or_previous_value(self):
        bucket = self.make_bucket(self.work)
        self.usage_history([
            {'org': bucket.name, 't': 900_000, 'u': {'fh': 30, 'sd': 99}},
            {'org': bucket.name, 't': 999_000, 'u': {'fh': 1}},
        ])
        with patch.object(p, 'desktop_login_saved', return_value=True):
            result = p.usage_snapshot(self.work, clock=1000)
        self.assertEqual([m['usedPercent'] for m in result['meters']], [1, None])

    def test_usage_old_snapshot_stays_old_and_does_not_infer_reset(self):
        bucket = self.make_bucket(self.work)
        self.usage_history([{'org': bucket.name, 't': 1_000_000, 'u': {'fh': 100, 'sd': 100}}])
        with patch.object(p, 'desktop_login_saved', return_value=True):
            result = p.usage_snapshot(self.work, clock=30_000)
        self.assertTrue(result['stale'])
        self.assertEqual(result['ageSeconds'], 29_000)
        self.assertEqual([m['usedPercent'] for m in result['meters']], [100, 100])
        self.assertNotIn('resetsAt', result)

    def test_usage_rejects_invalid_values_and_future_samples(self):
        bucket = self.make_bucket(self.work)
        self.usage_history([
            {'org': bucket.name, 't': 999_000, 'u': {'fh': 99.9, 'sd': True, 'sn': -1, 'so': 101, 'xu': '0'}},
            {'org': bucket.name, 't': 2_000_000, 'u': {'fh': 0, 'sd': 0}},
            {'org': bucket.name, 't': 'bad', 'u': {'fh': 0}},
            None,
        ])
        with patch.object(p, 'desktop_login_saved', return_value=True):
            result = p.usage_snapshot(self.work, clock=1000)
        self.assertEqual([m['usedPercent'] for m in result['meters']], [99.9, None])

    def test_usage_corrupt_legacy_and_logged_out_fail_closed(self):
        bucket = self.make_bucket(self.work)
        self.usage_history([{'org': bucket.name, 't': 999_000, 'u': {'fh': 40}}])
        with patch.object(p, 'desktop_login_saved', return_value=False):
            self.assertEqual(p.usage_snapshot(self.work, clock=1000)['meters'], [])
        with patch.object(p, 'desktop_login_saved', return_value=True):
            self.usage_history([{'t': 999_000, 'fh': 40, 'sd': 50}], version=1)
            self.assertEqual(p.usage_snapshot(self.work, clock=1000)['status'], 'unavailable')
            (self.desk / 'plan-usage-history.json').write_text('{"samples":')
            self.assertEqual(p.usage_snapshot(self.work, clock=1000)['status'], 'unavailable')

    def test_desktop_sidebar_transfer_keeps_transcript_and_excludes_auth_snapshots(self):
        personal = p.create('Personal', default=True)
        source = self.make_bucket(personal)
        destination = self.make_bucket(self.work, '33333333-3333-3333-3333-333333333333')
        transcript = p.MASTER_CLI / 'projects/example/cli-123.jsonl'
        transcript.parent.mkdir()
        transcript.write_text('shared transcript remains unchanged')
        original = {'sessionId': 'local_test', 'cliSessionId': 'cli-123', 'cwd': str(self.home),
                    'title': 'Continue this work', 'lastActivityAt': 100,
                    'remoteMcpServersConfig': {'private': 'ACCOUNT-SPECIFIC'},
                    'sessionPermissionUpdates': ['private'], 'permissionMode': 'bypassPermissions',
                    'bridgeSessionIds': ['other-account-bridge']}
        p.write_json(source / 'local_test.json', original)
        outcome = p.sync_code_history(self.work)
        self.assertEqual(outcome['copied'], 1)
        row = p.read_json(destination / 'local_test.json')
        self.assertEqual(row['cliSessionId'], 'cli-123')
        self.assertEqual(row['permissionMode'], 'default')
        self.assertNotIn('remoteMcpServersConfig', row)
        self.assertNotIn('bridgeSessionIds', row)
        self.assertNotIn('sessionPermissionUpdates', row)
        self.assertEqual(p.read_json(source / 'local_test.json'), original)
        self.assertEqual(transcript.read_text(), 'shared transcript remains unchanged')
        self.assertEqual(p.sync_code_history(self.work)['copied'], 0)
        # A later response in Work must update Personal's pointer on the way back.
        row.update(lastActivityAt=200, title='Continued on Work')
        p.write_json(destination / 'local_test.json', row)
        self.assertEqual(p.sync_code_history(personal)['updated'], 1)
        returned = p.read_json(source / 'local_test.json')
        self.assertEqual(returned['title'], 'Continued on Work')
        self.assertEqual(returned['remoteMcpServersConfig'], original['remoteMcpServersConfig'])

    def test_history_refuses_running_destination_and_waits_for_real_identity(self):
        self.assertTrue(p.sync_code_history(self.work)['setupRequired'])
        with patch.object(p, 'desktop_pids', return_value=[123]):
            with self.assertRaises(p.ProfileError):
                p.sync_code_history(self.work)

    def test_history_and_launch_block_without_remote_control_privacy(self):
        settings = p.read_json(self.cli / 'settings.json')
        for value in (False, 'true', None):
            settings['disableRemoteControl'] = value
            p.write_json(self.cli / 'settings.json', settings)
            with self.assertRaisesRegex(p.ProfileError, 'Remote Control can expose'):
                p.sync_code_history(self.work)
            with self.assertRaises(p.ProfileError):
                p.open_desktop(self.work)
        self.assertFalse(p.history_status(self.work)['remoteControlBlocked'])

    def test_owned_desktop_uses_original_config_without_requiring_block(self):
        self.work['remoteControlPolicy'] = 'allowed'
        settings = p.read_json(p.MASTER_CLI / 'settings.json')
        settings.pop('disableRemoteControl')
        p.write_json(p.MASTER_CLI / 'settings.json', settings)
        self.assertEqual(p.desktop_code_config(self.work), p.MASTER_CLI)
        self.assertIsNone(p.clean_env(self.work, desktop=True).get('CLAUDE_CONFIG_DIR'))
        p.require_local_history_privacy(self.work)
        self.assertTrue(p.sync_code_history(self.work)['setupRequired'])

    def test_shared_account_stays_blocked_when_master_allows_remote_control(self):
        settings = p.read_json(p.MASTER_CLI / 'settings.json')
        settings.pop('disableRemoteControl')
        settings['remoteControlAtStartup'] = True
        p.write_json(p.MASTER_CLI / 'settings.json', settings)
        p.sync_profile(self.work)
        protected = p.read_json(self.cli / 'settings.json')
        self.assertIs(protected['disableRemoteControl'], True)
        self.assertIs(protected['remoteControlAtStartup'], False)
        self.assertEqual(p.desktop_code_config(self.work), self.cli)
        self.assertEqual((self.cli / 'projects').resolve(), (p.MASTER_CLI / 'projects').resolve())
        p.require_local_history_privacy(self.work)

    def test_protected_running_process_must_match_launch_record(self):
        with patch.object(p, 'desktop_pids', return_value=[123]):
            with self.assertRaisesRegex(p.ProfileError, 'protected settings directory'):
                p.require_local_history_privacy(self.work)
            p.write_json(p.ROOT / 'runtime/work.json', {
                'pid': 123, 'codeConfig': str(self.cli), 'processStartedAt': 'known-start'})
            with patch.object(p.subprocess, 'run') as run:
                run.return_value.stdout = 'known-start\n'
                p.require_local_history_privacy(self.work)
                run.return_value.stdout = 'different-start\n'
                self.assertFalse(p.desktop_runtime_matches(self.work))

    def test_login_does_not_open_target_if_another_window_refuses_to_quit(self):
        p.create('Personal', default=True)
        def pids(profile):
            return [123] if profile['id'] == 'personal' else []
        with patch.object(p, 'desktop_pids', side_effect=pids), \
             patch.object(p.subprocess, 'run') as run, \
             patch.object(p.time, 'sleep'), \
             patch.object(p, 'refresh_history') as reopen:
            with self.assertRaisesRegex(p.ProfileError, 'waiting to quit'):
                p.prepare_login(self.work)
            reopen.assert_not_called()
            self.assertEqual(run.call_args.args[0][-2:], ['--quit-pid', '123'])

    def test_refresh_only_restarts_destination_and_reopens_it(self):
        personal = p.create('Personal', default=True)
        self.make_bucket(self.work)
        queried = []
        def pids(profile):
            queried.append(profile['id'])
            if profile['id'] == personal['id']:
                return [111]
            return [222] if len(queried) == 1 else []
        with patch.object(p, 'desktop_pids', side_effect=pids), \
             patch.object(p.subprocess, 'run') as run, \
             patch.object(p, 'open_desktop', return_value='reopened') as reopen:
            self.assertEqual(p.refresh_history(self.work), 'reopened')
            self.assertEqual(run.call_args.args[0][-2:], ['--quit-pid', '222'])
            self.assertEqual(run.call_count, 1)
            self.assertNotIn('personal', queried)
            reopen.assert_called_once_with(self.work)

    def test_original_paths_are_untouched(self):
        personal = p.create('Personal', default=True)
        before = (self.home / '.claude.json').read_bytes()
        self.assertEqual(p.paths(personal), (p.MASTER_DESKTOP, p.MASTER_CLI))
        self.assertEqual(p.sync_profile(personal)['skipped'], 'Source profile')
        self.assertEqual(before, (self.home / '.claude.json').read_bytes())
        with self.assertRaises(p.ProfileError):
            p.archive(personal)

    def test_plugin_install_paths_rebase(self):
        value = p.read_json(self.cli / 'plugins/installed_plugins.json')
        self.assertEqual(value['plugins']['example'][0]['installPath'], str(self.cli / 'plugins/cache/example'))

    def test_archive_restore_preserves_original_paths_and_data(self):
        (self.cli / 'sentinel').write_text('private profile state')
        p.archive(self.work)
        self.assertFalse(self.cli.exists())
        p.restore('Work')
        self.assertEqual((self.cli / 'sentinel').read_text(), 'private profile state')
        self.assertEqual(p.get_profile('Work')['id'], 'work')

    def test_running_profile_is_not_modified(self):
        with patch.object(p, 'desktop_pids', return_value=[123]):
            result = p.sync_profile(self.work)
            self.assertIn('Close', result['skipped'])
            with self.assertRaises(p.ProfileError):
                p.archive(self.work)

    def test_invalid_and_duplicate_names_are_rejected(self):
        for name in ['../escape', '-option', '$(id)', 'x\ny', 'a/b']:
            with self.assertRaises(p.ProfileError):
                p.slug(name)
        with self.assertRaises(p.ProfileError):
            p.create('WORK')


if __name__ == '__main__':
    unittest.main()
