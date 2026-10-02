"""tracking_report: запрос через RetryClient; лист очищается (write_spread_sheet) только после того,
как данные полностью получены и разобраны."""
import contextlib
import io
import json
import unittest

import requests

from tests.fakes import Case, Host, install_module_stubs

functions = install_module_stubs()  # до импорта tracking_report: настоящий functions лезет в Google

from http_client import DomainUnavailable  # noqa: E402
from tracking_report import tracking_report  # noqa: E402

URL = 'https://rubrain.com/api/v2/report/manager/project-report/summary/'
SPREAD = 'Парсинг тайм-трекинга Rubrain'
HEADER = ['developer', 'project_id', 'project_name', 'created', 'date', 'description', 'hours', 'hours_norma',
          'hours_summary', 'minutes', 'modified', 'report_type', 'status']


def record(description='did x'):
    return {'created': '2026-09-01T10:00:00', 'date': '2026-09-01', 'files': [], 'description': description,
            'hours': 2, 'hours_norma': 8, 'hours_summary': 2, 'minutes': 0, 'modified': 'm',
            'report_type': 't', 'status': 's'}


def spec_report(records, first='Ivan', last='Ivanov', project_id=5):
    return {'specialist': {'freelancer': {'first_name': first, 'last_name': last},
                           'project': {'id': project_id, 'name': 'Proj'}},
            'dates': {'2026-09-01': {'records': records}}}


GOOD = json.dumps({'data': [spec_report([record()])]}).encode()
GOOD_ROW = ['Ivanov Ivan', 5, 'Proj', '2026-09-01T10:00:00', 'D:2026-09-01', 'did x - 2h.', 2, 8, 2, 0, 'm', 't', 's']


class TrackingReportTests(Case):
    def setUp(self):
        functions.reset()

    def run_report(self, host, relogin=None, token='TOKEN'):
        c = self.make_client(rubrain_com=host)
        with contextlib.redirect_stdout(io.StringIO()):  # tracking_report печатает 'трекинг получен'
            return tracking_report(URL, 9, 2026, token, SPREAD, client=c, relogin=relogin)

    def assertSheetUntouched(self):
        self.assertEqual(functions.writes, [])

    def test_writes_the_full_report_once_and_formats_dates(self):
        self.run_report(Host((200, GOOD)))
        self.assertEqual(functions.writes, [(SPREAD, '9-2026', [HEADER, GOOD_ROW])])
        self.assertEqual(functions.formats, [(SPREAD, '9-2026', 'E:E')])

    def test_requests_the_month_with_the_bearer_token(self):
        host = Host((200, GOOD))
        self.run_report(host, token='TOK')
        request = host.calls[0][0]
        self.assertIn('month=9&year=2026&type=monthly', request.url)
        self.assertEqual(request.headers['authorization'], 'Bearer TOK')

    def test_survives_lost_connects(self):
        lost = requests.exceptions.ConnectTimeout('SYN lost')
        self.run_report(Host(lost, lost, (200, GOOD)))
        self.assertEqual(len(functions.writes), 1)

    # --- лист не очищается без полных данных ---

    def test_unreachable_domain_does_not_clear_the_sheet(self):
        with self.assertRaises(requests.exceptions.ConnectTimeout):
            self.run_report(Host(requests.exceptions.ConnectTimeout('down')))
        self.assertSheetUntouched()

    def test_domain_marked_unavailable_does_not_clear_the_sheet(self):
        c = self.make_client(rubrain_com=Host(requests.exceptions.ConnectTimeout('down')))
        for _ in range(2):
            with self.assertRaises(requests.exceptions.ConnectTimeout):
                c.get(URL)
        with self.assertRaises(DomainUnavailable):
            tracking_report(URL, 9, 2026, 'T', SPREAD, client=c)
        self.assertSheetUntouched()

    def test_http_errors_do_not_clear_the_sheet(self):
        for status in (403, 404, 500, 503):
            with self.subTest(status=status):
                with self.assertRaises(requests.exceptions.HTTPError):
                    self.run_report(Host((status, b'oops')))
                self.assertSheetUntouched()

    def test_truncated_json_does_not_clear_the_sheet(self):
        with self.assertRaises(ValueError):
            self.run_report(Host((200, b'{"data": [{"specialist": {')))
        self.assertSheetUntouched()

    def test_unexpected_response_shape_does_not_clear_the_sheet(self):
        with self.assertRaises(KeyError):
            self.run_report(Host((200, b'{"detail": "no data here"}')))
        self.assertSheetUntouched()

    def test_failure_halfway_through_parsing_does_not_write_partial_data(self):
        broken = spec_report([record()])
        del broken['dates']
        body = json.dumps({'data': [spec_report([record()]), broken]}).encode()
        with self.assertRaises(KeyError):
            self.run_report(Host((200, body)))
        self.assertSheetUntouched()

    # --- 401: один релогин ---

    def test_401_relogins_once_and_retries_with_the_new_token(self):
        host = Host(401, (200, GOOD))
        relogins = []
        self.run_report(host, relogin=lambda: relogins.append(1) or 'NEW')
        self.assertEqual(len(relogins), 1)
        self.assertEqual(host.calls[0][0].headers['authorization'], 'Bearer TOKEN')
        self.assertEqual(host.calls[1][0].headers['authorization'], 'Bearer NEW')
        self.assertEqual(len(functions.writes), 1)

    def test_second_401_is_an_error_and_the_sheet_is_untouched(self):
        host = Host(401)
        relogins = []
        with self.assertRaises(requests.exceptions.HTTPError):
            self.run_report(host, relogin=lambda: relogins.append(1) or 'NEW')
        self.assertEqual(len(relogins), 1)
        self.assertEqual(len(host.calls), 2)
        self.assertSheetUntouched()

    def test_401_without_relogin_is_an_error(self):
        host = Host(401)
        with self.assertRaises(requests.exceptions.HTTPError):
            self.run_report(host)
        self.assertEqual(len(host.calls), 1)
        self.assertSheetUntouched()


if __name__ == '__main__':
    unittest.main()
