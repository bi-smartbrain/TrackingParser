"""Тесты http_client без сети: сеть подменена адаптером requests, всё остальное (Session, ретраи,
предохранитель, счётчики) — настоящий код.

Запуск из корня проекта: python -m unittest discover -s tests -t .
"""
import random
import time
import unittest

import requests

from http_client import DomainUnavailable
from tests.fakes import Case, FlakyConnectHost, Host


A = 'https://rubrain.com/api/x/'
B = 'https://junbrain.ru/api/x/'


class RetryTests(Case):
    def test_success_needs_no_retry(self):
        host = Host(200)
        c = self.make_client(rubrain_com=host)
        self.assertEqual(c.get(A).status_code, 200)
        self.assertEqual(len(host.calls), 1)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(c.stats['rubrain.com'], {'requests': 1, 'retries': 0, 'exhausted': 0})

    def test_each_transient_failure_is_retried_until_success(self):
        for exc in (requests.exceptions.ConnectTimeout('c'), requests.exceptions.ConnectionError('e'),
                    requests.exceptions.ReadTimeout('r')):
            with self.subTest(exc=type(exc).__name__):
                host = Host(exc, exc, 200)
                c = self.make_client(rubrain_com=host)
                self.assertEqual(c.get(A).status_code, 200)
                self.assertEqual(len(host.calls), 3)
                self.assertEqual(self.sleeps, [2, 2])
                self.assertEqual(c.stats['rubrain.com'], {'requests': 1, 'retries': 2, 'exhausted': 0})

    def test_gateway_and_throttle_statuses_are_retried(self):
        for status in (502, 503, 504, 429):
            with self.subTest(status=status):
                host = Host(status, 200)
                c = self.make_client(rubrain_com=host)
                self.assertEqual(c.get(A).status_code, 200)
                self.assertEqual(len(host.calls), 2)

    def test_client_errors_are_returned_without_retry(self):
        for status in (400, 403, 404, 500):
            with self.subTest(status=status):
                host = Host(status, 200)
                c = self.make_client(rubrain_com=host)
                self.assertEqual(c.get(A).status_code, status)
                self.assertEqual(len(host.calls), 1)
                self.assertEqual(self.sleeps, [])

    def test_gives_up_after_ten_attempts_and_raises_the_original_error(self):
        host = Host(requests.exceptions.ConnectTimeout('syn lost'))
        c = self.make_client(rubrain_com=host)
        with self.assertRaises(requests.exceptions.ConnectTimeout):
            c.get(A)
        self.assertEqual(len(host.calls), 10)
        self.assertEqual(self.sleeps, [2] * 9)  # после последней попытки не спим
        self.assertEqual(c.stats['rubrain.com'], {'requests': 1, 'retries': 9, 'exhausted': 1})

    def test_exhausted_retryable_status_raises_http_error(self):
        host = Host(503)
        c = self.make_client(rubrain_com=host)
        with self.assertRaises(requests.exceptions.HTTPError):
            c.get(A)
        self.assertEqual(len(host.calls), 10)

    def test_post_is_retried_and_keeps_its_json_body(self):
        host = Host(requests.exceptions.ConnectTimeout('c'), 200)
        c = self.make_client(rubrain_com=host)
        self.assertEqual(c.post(A, json={'email': 'a@b'}).status_code, 200)
        self.assertEqual([r.method for r, _ in host.calls], ['POST', 'POST'])
        self.assertEqual(host.calls[1][0].body, b'{"email": "a@b"}')

    def test_default_timeouts_are_short_connect_and_generous_read(self):
        host = Host(200)
        c = self.make_client(rubrain_com=host)
        c.get(A)
        connect, read = host.calls[0][1]['timeout']
        self.assertLessEqual(connect, 10)
        self.assertGreaterEqual(read, 30)

    def test_caller_can_override_timeout(self):
        host = Host(200)
        c = self.make_client(rubrain_com=host)
        c.get(A, timeout=(3, 7))
        self.assertEqual(host.calls[0][1]['timeout'], (3, 7))


class CircuitBreakerTests(Case):
    def dead(self):
        return Host(requests.exceptions.ConnectTimeout('down'))

    def test_third_request_to_dead_domain_fails_instantly(self):
        host = self.dead()
        c = self.make_client(rubrain_com=host)
        for _ in range(2):
            with self.assertRaises(requests.exceptions.ConnectTimeout):
                c.get(A)
        sends, sleeps = len(host.calls), len(self.sleeps)

        t = time.perf_counter()
        with self.assertRaises(DomainUnavailable):
            c.get(A)
        elapsed = time.perf_counter() - t

        self.assertLess(elapsed, 0.05)
        self.assertEqual(len(host.calls), sends)  # в сеть не ходили
        self.assertEqual(len(self.sleeps), sleeps)  # не ждали
        self.assertEqual(c.stats['rubrain.com']['exhausted'], 2)

    def test_one_exhausted_request_does_not_trip_the_breaker(self):
        host = Host(*([requests.exceptions.ConnectTimeout('x')] * 10), 200)
        c = self.make_client(rubrain_com=host)
        with self.assertRaises(requests.exceptions.ConnectTimeout):
            c.get(A)
        self.assertEqual(c.get(A).status_code, 200)

    def test_success_resets_the_consecutive_failure_count(self):
        t = requests.exceptions.ConnectTimeout('x')
        host = Host(*([t] * 10), 200, *([t] * 10), 200)
        c = self.make_client(rubrain_com=host)
        with self.assertRaises(requests.exceptions.ConnectTimeout):
            c.get(A)
        self.assertEqual(c.get(A).status_code, 200)
        with self.assertRaises(requests.exceptions.ConnectTimeout):
            c.get(A)  # второй провал, но не подряд: домен ещё доступен
        self.assertEqual(c.get(A).status_code, 200)

    def test_breaker_is_per_domain(self):
        good = Host(200)
        c = self.make_client(rubrain_com=self.dead(), junbrain_ru=good)
        for _ in range(2):
            with self.assertRaises(requests.exceptions.ConnectTimeout):
                c.get(A)
        with self.assertRaises(DomainUnavailable):
            c.get(A)
        self.assertEqual(c.get(B).status_code, 200)

    def test_breaker_resets_with_a_new_client(self):
        c1 = self.make_client(rubrain_com=self.dead())
        for _ in range(2):
            with self.assertRaises(requests.exceptions.ConnectTimeout):
                c1.get(A)
        c2 = self.make_client(rubrain_com=Host(200))
        self.assertEqual(c2.get(A).status_code, 200)

    def test_http_answers_count_as_alive_for_the_breaker(self):
        # 404 — сервер ответил, домен жив: счётчик провалов сбрасывается
        t = requests.exceptions.ConnectTimeout('x')
        host = Host(*([t] * 10), 404, *([t] * 10), 200)
        c = self.make_client(rubrain_com=host)
        with self.assertRaises(requests.exceptions.ConnectTimeout):
            c.get(A)
        self.assertEqual(c.get(A).status_code, 404)
        with self.assertRaises(requests.exceptions.ConnectTimeout):
            c.get(A)
        self.assertEqual(c.get(A).status_code, 200)


class ReauthTests(Case):
    def test_401_triggers_one_relogin_and_a_retry_with_the_new_headers(self):
        host = Host(401, 200)
        c = self.make_client(rubrain_com=host)
        relogins = []

        def relogin():
            relogins.append(1)
            return {'headers': {'authorization': 'Bearer NEW'}}

        r = c.get(A, headers={'authorization': 'Bearer OLD'}, on_unauthorized=relogin)

        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(relogins), 1)
        self.assertEqual(host.calls[0][0].headers['authorization'], 'Bearer OLD')
        self.assertEqual(host.calls[1][0].headers['authorization'], 'Bearer NEW')

    def test_second_401_is_returned_and_there_is_no_second_relogin(self):
        host = Host(401)
        c = self.make_client(rubrain_com=host)
        relogins = []
        r = c.get(A, on_unauthorized=lambda: relogins.append(1) or {})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(len(relogins), 1)
        self.assertEqual(len(host.calls), 2)
        with self.assertRaises(requests.exceptions.HTTPError):
            r.raise_for_status()

    def test_relogin_is_not_called_for_non_401_answers(self):
        for status in (200, 403, 404):
            with self.subTest(status=status):
                c = self.make_client(rubrain_com=Host(status))
                relogins = []
                r = c.get(A, on_unauthorized=lambda: relogins.append(1) or {})
                self.assertEqual(r.status_code, status)
                self.assertEqual(relogins, [])

    def test_401_without_callback_is_returned_as_is(self):
        host = Host(401, 200)
        c = self.make_client(rubrain_com=host)
        self.assertEqual(c.get(A).status_code, 401)
        self.assertEqual(len(host.calls), 1)

    def test_retry_after_relogin_still_survives_connect_loss(self):
        t = requests.exceptions.ConnectTimeout('x')
        host = Host(401, t, t, 200)
        c = self.make_client(rubrain_com=host)
        r = c.get(A, on_unauthorized=lambda: {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(host.calls), 4)


class ConnectLossSimulation(Case):
    def test_half_of_connects_lost_every_request_still_succeeds(self):
        rng = random.Random(7)
        hosts = {n: FlakyConnectHost(rng) for n in ('rubrain_com', 'junbrain_ru', 'smartbrain_io')}
        c = self.make_client(**hosts)
        urls = [A, B, 'https://smartbrain.io/api/x/']

        for _ in range(30):
            for u in urls:
                self.assertEqual(c.get(u).status_code, 200)

        for dom in ('rubrain.com', 'junbrain.ru', 'smartbrain.io'):
            self.assertEqual(c.stats[dom]['requests'], 30)
            self.assertEqual(c.stats[dom]['exhausted'], 0)
        self.assertGreater(sum(s['retries'] for s in c.stats.values()), 0)
        # keep-alive: соединение установлено один раз на домен, а не на каждый запрос
        self.assertTrue(all(h.connected for h in hosts.values()))


class LifecycleTests(Case):
    def test_one_session_per_domain_is_reused(self):
        c = self.make_client(rubrain_com=Host(200), junbrain_ru=Host(200))
        for _ in range(3):
            c.get(A)
            c.get(B)
        self.assertEqual(len(self.sessions), 2)

    def test_close_closes_every_session(self):
        c = self.make_client(rubrain_com=Host(200), junbrain_ru=Host(200))
        c.get(A)
        c.get(B)
        c.close()
        self.assertEqual(self.net.closed, 2)

    def test_context_manager_closes_sessions(self):
        with self.make_client(rubrain_com=Host(200)) as c:
            c.get(A)
        self.assertEqual(self.net.closed, 1)

    def test_summary_line_lists_every_used_domain(self):
        t = requests.exceptions.ConnectTimeout('x')
        c = self.make_client(rubrain_com=Host(t, t, 200), junbrain_ru=Host(200))
        c.get(A)
        c.get(B)
        self.assertEqual(
            c.summary(),
            'Connect retries (RUB-3245): rubrain.com req=1 retries=2 exhausted=0 | '
            'junbrain.ru req=1 retries=0 exhausted=0',
        )

    def test_summary_line_flags_a_domain_the_breaker_gave_up_on(self):
        c = self.make_client(rubrain_com=Host(requests.exceptions.ConnectTimeout('x')), junbrain_ru=Host(200))
        for _ in range(2):
            with self.assertRaises(requests.exceptions.ConnectTimeout):
                c.get(A)
        c.get(B)
        self.assertEqual(
            c.summary(),
            'Connect retries (RUB-3245): rubrain.com req=2 retries=18 exhausted=2 UNAVAILABLE | '
            'junbrain.ru req=1 retries=0 exhausted=0',
        )

    def test_summary_line_for_unused_client(self):
        c = self.make_client()
        self.assertEqual(c.summary(), 'Connect retries (RUB-3245): нет запросов')


if __name__ == '__main__':
    unittest.main()
