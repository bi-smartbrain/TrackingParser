"""run_tracking: домены и месяцы изолированы, ошибки собираются и кидаются одним исключением в конце
(чтобы дебаунс в run_with_restart_on_fail работал как раньше); в конце прогона печатается сводка."""
import contextlib
import io
import unittest
from unittest import mock
from urllib.parse import urlparse

import requests

from tests.fakes import install_module_stubs

install_module_stubs()  # до импорта main: functions и tg_logger лезут в Google/Telegram

import main  # noqa: E402
from http_client import DomainUnavailable, RetryClient  # noqa: E402

RUB, JUN = 'rubrain.com', 'junbrain.ru'


class RecordingClient(RetryClient):
    instances = []

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.closed = False
        RecordingClient.instances.append(self)

    def close(self):
        self.closed = True
        super().close()


class RunTrackingTests(unittest.TestCase):
    def setUp(self):
        RecordingClient.instances.clear()
        self.calls = []  # (домен, месяц, год, токен, спредшит)
        self.behaviors = {}  # (домен, месяц) -> исключение или callable(kwargs)
        self.config = {'Парсинг тайм-трекинга Rubrain': {'MONTHS': '9,10', 'YEAR': '2026'},
                       'Парсинг тайм-трекинга Junbrain': {'MONTHS': '9,10', 'YEAR': '2026'}}
        self.login = mock.Mock(side_effect=[{'access': 'T1'}, {'access': 'T2'}, {'access': 'T3'}])

        def fake_report(url, month, year, token, spread, **kwargs):
            domain = urlparse(url).hostname
            self.calls.append((domain, month, year, token, spread))
            action = self.behaviors.get((domain, month))
            if isinstance(action, Exception):
                raise action
            if callable(action):
                action(kwargs)

        patches = [
            mock.patch.object(main, 'RetryClient', RecordingClient),
            mock.patch.object(main, 'get_tokens', self.login),
            mock.patch.object(main, 'load_sheet_config', lambda spread: dict(self.config[spread])),
            mock.patch.object(main, 'tracking_report', fake_report),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_tracking(self):
        out = io.StringIO()
        error = None
        with contextlib.redirect_stdout(out):
            try:
                main.run_tracking()
            except Exception as e:  # noqa: BLE001
                error = e
        return error, out.getvalue()

    def visited(self):
        return [(d, m) for d, m, *_ in self.calls]

    def test_clean_run_visits_every_month_and_prints_the_summary(self):
        error, out = self.run_tracking()
        self.assertIsNone(error)
        self.assertEqual(self.visited(), [(RUB, 9), (RUB, 10), (JUN, 9), (JUN, 10)])
        self.assertIn('Connect retries (RUB-3245)', out)
        self.assertTrue(RecordingClient.instances[0].closed)

    def test_login_goes_through_the_shared_client(self):
        self.run_tracking()
        self.assertIs(self.login.call_args.kwargs['client'], RecordingClient.instances[0])

    def test_failed_month_does_not_stop_other_months_or_domains(self):
        self.behaviors[(RUB, 9)] = RuntimeError('boom')
        error, out = self.run_tracking()
        self.assertEqual(self.visited(), [(RUB, 9), (RUB, 10), (JUN, 9), (JUN, 10)])
        self.assertIsInstance(error, main.TrackingRunFailed)
        self.assertIn('Rubrain 9-2026', str(error))
        self.assertIn('boom', str(error))
        self.assertNotIn('Junbrain', str(error))
        self.assertIn('Connect retries (RUB-3245)', out)

    def test_unavailable_domain_skips_its_remaining_months_but_not_the_other_domain(self):
        self.behaviors[(RUB, 9)] = DomainUnavailable(RUB)
        error, _ = self.run_tracking()
        self.assertEqual(self.visited(), [(RUB, 9), (JUN, 9), (JUN, 10)])
        self.assertIsInstance(error, main.TrackingRunFailed)
        self.assertIn(RUB, str(error))
        self.assertIn('[9, 10]', str(error))  # пропущенные месяцы названы

    def test_domain_that_just_gave_up_is_reported_with_its_real_error(self):
        self.behaviors[(RUB, 9)] = requests.exceptions.ConnectTimeout('syn lost')
        self.behaviors[(RUB, 10)] = DomainUnavailable(RUB)
        error, _ = self.run_tracking()
        self.assertEqual(self.visited(), [(RUB, 9), (RUB, 10), (JUN, 9), (JUN, 10)])
        self.assertIn('ConnectTimeout', str(error))
        self.assertIn('syn lost', str(error))

    def test_failed_login_skips_everything_but_still_reports(self):
        self.login.side_effect = requests.exceptions.ConnectTimeout('login down')
        error, out = self.run_tracking()
        self.assertEqual(self.calls, [])
        self.assertIsInstance(error, main.TrackingRunFailed)
        self.assertIn('login down', str(error))
        self.assertIn('Connect retries (RUB-3245)', out)
        self.assertTrue(RecordingClient.instances[0].closed)

    def test_relogin_token_is_used_by_all_following_requests(self):
        self.behaviors[(RUB, 9)] = lambda kwargs: self.assertEqual(kwargs['relogin'](), 'T2')
        error, _ = self.run_tracking()
        self.assertIsNone(error)
        self.assertEqual([c[3] for c in self.calls], ['T1', 'T2', 'T2', 'T2'])

    def test_bad_config_of_one_domain_does_not_stop_the_other(self):
        self.config['Парсинг тайм-трекинга Rubrain'] = {'MONTHS': '9', 'YEAR': 'abc'}
        error, _ = self.run_tracking()
        self.assertEqual(self.visited(), [(JUN, 9), (JUN, 10)])
        self.assertIsInstance(error, main.TrackingRunFailed)
        self.assertIn('Rubrain', str(error))

    def test_empty_config_means_no_parsing_and_no_error(self):
        self.config['Парсинг тайм-трекинга Rubrain'] = {}
        error, _ = self.run_tracking()
        self.assertIsNone(error)
        self.assertEqual(self.visited(), [(JUN, 9), (JUN, 10)])

    def test_every_domain_failing_reports_all_of_them(self):
        for d in (RUB, JUN):
            for m in (9, 10):
                self.behaviors[(d, m)] = RuntimeError(f'{d}-{m}')
        error, _ = self.run_tracking()
        for d in (RUB, JUN):
            for m in (9, 10):
                self.assertIn(f'{d}-{m}', str(error))


if __name__ == '__main__':
    unittest.main()
