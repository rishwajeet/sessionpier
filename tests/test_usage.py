import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
import usage_service as u
import companion as c


class UsageParsingTests(unittest.TestCase):
    def test_claude_screen_with_ansi_and_repeated_percent(self):
        raw = '\x1b[32mCurrent session\x1b[0m\r\n25% 25% used\r\nResets 8:30pm (UTC)\r\nCurrent week (all models)\r\n99.9% 99.9% used\r\nResets Oct 12 at 4:30pm (UTC)\r\nCurrent week (Fable)\r\n6% 6% used\r\nUsage credits\r\n100% used\r\n'
        clock = dt.datetime(2026, 10, 10, 18, tzinfo=dt.timezone.utc).timestamp()
        meters = u.parse_claude_usage(raw, clock)
        self.assertEqual([m['usedPercent'] for m in meters], [25, 99.9, 6])
        self.assertEqual(meters[0]['resetsAt'], dt.datetime(2026, 10, 10, 20, 30, tzinfo=dt.timezone.utc).timestamp())
        self.assertEqual(meters[1]['label'], 'Weekly')
        self.assertEqual(len(meters), 3)  # Billing percentages cannot become quota windows.

    def test_partial_and_absent_windows_never_become_zero(self):
        meters = u.parse_claude_usage('Current session\nLoading…\nCurrent week (all models)\n38% used\n')
        self.assertEqual([m['id'] for m in meters], ['seven_day'])
        self.assertEqual(u.parse_claude_usage('Session\nTotal cost: $0.00\nUsage: 0 input, 0 output'), [])

    def test_invalid_percent_and_reset_are_unknown(self):
        self.assertEqual(u.parse_claude_usage('Current session\n101% used\n'), [])
        self.assertIsNone(u.reset_time('Resets whenever', 1000))
        self.assertIsNone(u.reset_time('Resets 8:30pm (Unknown/Zone)', 1000))
        self.assertIsNone(u.percent(True))
        self.assertIsNone(u.percent(float('nan')))

    def test_dated_reset_year_rollover_and_timezone(self):
        clock = dt.datetime(2026, 12, 31, 18, tzinfo=dt.timezone.utc).timestamp()
        reset = u.reset_time('Resets Jan 2 at 4:30pm (Asia/Calcutta)', clock)
        self.assertEqual(reset, dt.datetime(2027, 1, 2, 11, tzinfo=dt.timezone.utc).timestamp())

    def test_codex_primary_can_be_weekly_not_session(self):
        response = {'rateLimitsByLimitId': {'codex': {'primary': {'usedPercent': 42, 'windowDurationMins': 10080, 'resetsAt': 1800000000}, 'secondary': None}}}
        result = u.parse_codex_limits(response)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['label'], 'Weekly')
        self.assertEqual(result[0]['usedPercent'], 42)

    def test_codex_buckets_stay_distinct_and_missing_limits_unknown(self):
        response = {'rateLimitsByLimitId': {
            'main': {'limitName': 'Core', 'primary': {'usedPercent': 0, 'windowDurationMins': 300}},
            'review': {'limitName': 'Review', 'secondary': {'usedPercent': 75, 'windowDurationMins': 10080}},
            'unknown': {'primary': {'usedPercent': None, 'windowDurationMins': 300}},
        }}
        result = u.parse_codex_limits(response)
        self.assertEqual([r['id'] for r in result], ['main_primary', 'review_secondary'])
        self.assertEqual([r['label'] for r in result], ['Core · Session', 'Review · Weekly'])
        self.assertIsNone(result[0]['resetsAt'])

    def test_codex_legacy_response_and_bad_fields(self):
        result = u.parse_codex_limits({'rateLimits': {'primary': {'usedPercent': 20, 'windowDurationMins': -10, 'resetsAt': True}}})
        self.assertEqual(result[0]['label'], 'Usage window')
        self.assertIsNone(result[0]['resetsAt'])
        self.assertIsNone(result[0]['windowMinutes'])


class IdentityTests(unittest.TestCase):
    def test_claude_requires_both_matching_account_and_org(self):
        row = {'id': 'work', 'default': False}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); desk = root / 'desktop'; cli = root / 'cli'
            desk.mkdir(); cli.mkdir()
            (desk / 'config.json').write_text(json.dumps({'lastKnownAccountUuid': 'account-a'}))
            meta = cli / '.claude.json'
            with patch.object(u.profiles, 'paths', return_value=(desk, cli)), patch.object(u.profiles, 'session_bucket', return_value=Path('org-a')):
                for account, org in [('account-b', 'org-a'), ('account-a', 'org-b')]:
                    meta.write_text(json.dumps({'oauthAccount': {'accountUuid': account, 'organizationUuid': org}}))
                    with self.assertRaises(u.UsageError) as error:
                        u.claude_identity(row)
                    self.assertEqual(error.exception.code, 'identity_mismatch')
                meta.write_text(json.dumps({'oauthAccount': {'accountUuid': 'account-a', 'organizationUuid': 'org-a'}}))
                self.assertEqual(u.claude_identity(row)['accountId'], 'account-a')

    def test_codex_rejects_identity_change_and_closes_connection(self):
        from unittest.mock import MagicMock
        connection = MagicMock()
        connection.request.side_effect = [{}, {'account': {'type': 'chatgpt', 'email': 'one@example.test'}},
            {'rateLimits': {'primary': {'usedPercent': 20}}}, {'account': {'type': 'chatgpt', 'email': 'two@example.test'}}]
        with patch.object(u, 'CodexConnection', return_value=connection):
            with self.assertRaises(u.UsageError) as error:
                u.read_codex('codex', Path('/example'))
        self.assertEqual(error.exception.code, 'identity_changed')
        connection.close.assert_called_once()

    def test_claude_cache_drops_reading_when_identity_differs(self):
        sample = {'sampledAt': 1800000000, 'identityKey': 'previous-identity',
            'meters': [{'id': 'session', 'label': 'Session', 'usedPercent': 9}]}
        with patch.object(c.usage, 'claude_identity', return_value={'accountId': 'new', 'organizationId': 'org'}), \
             patch.object(c.p, 'usage_snapshot', return_value={'status': 'unavailable'}):
            reading = c.usage_for_claude({}, {'sample': sample}, 1800000001)
        self.assertEqual(reading['status'], 'unavailable')
        self.assertEqual(reading['meters'], [])


class UsageCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patchers = [patch.object(c, 'STATE', root), patch.object(c, 'lookup', return_value=('claude', {'id': 'one'}))]
        for item in self.patchers:
            item.start()
        self.clock = 1800000000

    def tearDown(self):
        for item in reversed(self.patchers):
            item.stop()
        self.temp.cleanup()

    def sample(self, identity='a', percent=30, at=None):
        return {'sampledAt': self.clock if at is None else at, 'identityKey': identity, 'source': 'test client',
                'meters': [{'id': 'session', 'label': 'Session', 'usedPercent': percent, 'windowMinutes': 300,
                            'resetsAt': None, 'resetDescription': None}]}

    def test_success_failure_preserves_timestamp_and_enforces_backoff(self):
        with patch.object(c.time, 'time', return_value=self.clock):
            c.refresh_one('claude-one', fetchers={'claude': lambda _: self.sample()})
        def fail(_):
            raise u.UsageError('refresh_failed', 'Temporary connection problem')
        with patch.object(c.time, 'time', return_value=self.clock + 400):
            c.refresh_one('claude-one', fetchers={'claude': fail})
        cached = c.read(c.cache_file('claude-one'))
        self.assertEqual(cached['sample']['sampledAt'], self.clock)
        self.assertEqual(cached['error']['code'], 'refresh_failed')
        self.assertEqual(c.normalize_cache(cached, self.clock + 400)['status'], 'cached')
        self.assertGreater(cached['nextAttemptAt'], self.clock + 400)
        with patch.object(c.time, 'time', return_value=self.clock + 401):
            c.refresh_one('claude-one', fetchers={'claude': lambda _: self.fail('Backoff was ignored')})

    def test_manual_refresh_has_minimum_spacing(self):
        with patch.object(c.time, 'time', return_value=self.clock):
            c.refresh_one('claude-one', force=True, fetchers={'claude': lambda _: self.sample()})
            c.refresh_one('claude-one', force=True, fetchers={'claude': lambda _: self.fail('Duplicate refresh')})

    def test_identity_change_does_not_join_trends(self):
        with patch.object(c.time, 'time', return_value=self.clock):
            c.refresh_one('claude-one', fetchers={'claude': lambda _: self.sample('first')})
        with patch.object(c.time, 'time', return_value=self.clock + 400):
            c.refresh_one('claude-one', fetchers={'claude': lambda _: self.sample('second', at=self.clock + 400)})
        self.assertEqual(len(c.read(c.cache_file('claude-one'))['history']), 1)

    def test_account_files_and_locks_are_separate(self):
        with patch.object(c.time, 'time', return_value=self.clock):
            c.refresh_one('claude-one', fetchers={'claude': lambda _: self.sample('one', 20)})
            c.refresh_one('claude-two', fetchers={'claude': lambda _: self.sample('two', 70)})
        self.assertEqual(c.read(c.cache_file('claude-one'))['sample']['meters'][0]['usedPercent'], 20)
        self.assertEqual(c.read(c.cache_file('claude-two'))['sample']['meters'][0]['usedPercent'], 70)
        with c.account_lock('claude-one') as acquired:
            self.assertTrue(acquired)
            with c.account_lock('claude-one') as duplicate:
                self.assertFalse(duplicate)
            with c.account_lock('claude-two') as separate:
                self.assertTrue(separate)

    def test_future_and_corrupt_cache_cannot_look_fresh(self):
        self.assertIsNone(c.normalize_cache({'sample': self.sample(at=self.clock + 1000)}, self.clock))
        self.assertIsNone(c.normalize_cache({'sample': {'sampledAt': True}}, self.clock))
        old = c.normalize_cache({'sample': self.sample(at=self.clock - 3600)}, self.clock)
        self.assertTrue(old['stale'])
        self.assertEqual(old['sampledAt'], self.clock - 3600)

    def test_login_failure_is_actionable_without_discarding_recoverable_cache(self):
        with patch.object(c.time, 'time', return_value=self.clock):
            c.refresh_one('claude-one', fetchers={'claude': lambda _: self.sample()})
        def fail(_):
            raise u.UsageError('login_required', 'Connect the official client')
        with patch.object(c.time, 'time', return_value=self.clock + 400):
            c.refresh_one('claude-one', fetchers={'claude': fail})
        result = c.read(c.cache_file('claude-one'))
        self.assertEqual(result['error']['code'], 'login_required')
        self.assertEqual(result['sample']['sampledAt'], self.clock)
        self.assertEqual(result['nextAttemptAt'], self.clock + 1300)

    def test_process_errors_never_publish_raw_exception_output(self):
        def fail(_):
            raise OSError('secret-value-in-process-output')
        with patch.object(c.time, 'time', return_value=self.clock):
            c.refresh_one('claude-one', fetchers={'claude': fail})
        self.assertNotIn('secret-value', c.cache_file('claude-one').read_text())


if __name__ == '__main__':
    unittest.main()
