"""get_tokens: логин идёт через RetryClient (ретраи + таймауты), поведение и URL не меняются."""
import json
import unittest

import requests

from get_tokens import get_tokens
from tests.fakes import Case, Host

LOGIN_URL = 'https://smartbrain.io/api/auth/login/?active_lang=ru'
TOKENS = b'{"access": "A", "refresh": "R"}'


class GetTokensTests(Case):
    def test_posts_credentials_to_smartbrain_login_and_returns_tokens(self):
        host = Host((200, TOKENS))
        c = self.make_client(smartbrain_io=host)

        tokens = get_tokens('user@x', 'secret', client=c)

        self.assertEqual(tokens, {'access': 'A', 'refresh': 'R'})
        request = host.calls[0][0]
        self.assertEqual((request.method, request.url), ('POST', LOGIN_URL))
        self.assertEqual(json.loads(request.body), {'email': 'user@x', 'password': 'secret'})

    def test_login_survives_lost_connects(self):
        lost = requests.exceptions.ConnectTimeout('SYN lost')
        host = Host(lost, lost, (200, TOKENS))
        c = self.make_client(smartbrain_io=host)
        self.assertEqual(get_tokens('u', 'p', client=c)['access'], 'A')
        self.assertEqual(len(host.calls), 3)

    def test_login_has_a_timeout(self):
        host = Host((200, TOKENS))
        c = self.make_client(smartbrain_io=host)
        get_tokens('u', 'p', client=c)
        self.assertIsNotNone(host.calls[0][1]['timeout'])

    def test_rejected_credentials_raise_with_server_text_and_are_not_retried(self):
        host = Host((400, b'{"detail": "bad credentials"}'))
        c = self.make_client(smartbrain_io=host)
        with self.assertRaisesRegex(Exception, 'Не удалось получить токены.*bad credentials'):
            get_tokens('u', 'wrong', client=c)
        self.assertEqual(len(host.calls), 1)


if __name__ == '__main__':
    unittest.main()
