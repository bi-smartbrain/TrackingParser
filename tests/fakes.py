"""Общие тестовые заглушки: «сеть» на уровне адаптера requests и фейки модулей с побочными эффектами
при импорте (functions — Google Sheets, tg_logger — Telegram)."""
import sys
import types
import unittest
from urllib.parse import urlparse

import requests
from requests.adapters import BaseAdapter

from http_client import RetryClient


def make_response(request, status, body=b'{"ok": true}'):
    r = requests.Response()
    r.status_code = status
    r._content = body
    r.url = request.url
    r.request = request
    return r


class Host:
    """Сценарий одного домена. Элемент: исключение (бросается), HTTP-статус или (статус, тело bytes).
    Когда сценарий кончился, повторяется последний элемент."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []  # (request, kwargs адаптера)

    def handle(self, request, kwargs):
        self.calls.append((request, kwargs))
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        status, body = item if isinstance(item, tuple) else (item, b'{"ok": true}')
        return make_response(request, status, body)


class FlakyConnectHost:
    """Модель потери SYN: новое соединение устанавливается с вероятностью 1-p, а установленное
    keep-alive соединение работает без потерь."""

    def __init__(self, rng, loss=0.5):
        self.rng = rng
        self.loss = loss
        self.connected = False
        self.connect_attempts = 0
        self.calls = []

    def handle(self, request, kwargs):
        self.calls.append((request, kwargs))
        if not self.connected:
            self.connect_attempts += 1
            if self.rng.random() < self.loss:
                raise requests.exceptions.ConnectTimeout('SYN потерян')
            self.connected = True
        return make_response(request, 200)


class Network(BaseAdapter):
    def __init__(self, **hosts):
        super().__init__()
        self.hosts = {name.replace('_', '.'): h for name, h in hosts.items()}
        self.closed = 0

    def send(self, request, **kwargs):
        return self.hosts[urlparse(request.url).hostname].handle(request, kwargs)

    def close(self):
        self.closed += 1


class Case(unittest.TestCase):
    def make_client(self, **hosts):
        self.net = Network(**hosts)
        self.sleeps = []
        self.sessions = []

        def session_factory():
            s = requests.Session()
            s.mount('https://', self.net)
            self.sessions.append(s)
            return s

        return RetryClient(session_factory=session_factory, sleep=self.sleeps.append)


def install_module_stubs():
    """Подменяет functions и tg_logger: настоящие при импорте лезут в Google/Telegram.
    Идемпотентно; возвращает фейковый functions, в котором write_spread_sheet и format_range_to_date
    пишут вызовы в .writes / .formats (их сбрасывает reset())."""
    if 'functions' in sys.modules and getattr(sys.modules['functions'], 'IS_STUB', False):
        return sys.modules['functions']

    functions = types.ModuleType('functions')
    functions.IS_STUB = True
    functions.gc = object()
    functions.writes = []
    functions.formats = []
    functions.write_spread_sheet = lambda spread, sheet, report: functions.writes.append((spread, sheet, report))
    functions.format_range_to_date = lambda spread, sheet, rng: functions.formats.append((spread, sheet, rng))
    functions.convert_to_google_date = lambda s: 'D:' + s

    def reset():
        functions.writes.clear()
        functions.formats.clear()

    functions.reset = reset
    sys.modules['functions'] = functions

    tg = types.ModuleType('tg_logger')
    tg.logger = types.SimpleNamespace(
        info=lambda *a, **k: None, critical=lambda *a, **k: None)
    sys.modules['tg_logger'] = tg
    return functions
