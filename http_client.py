"""HTTP-клиент, устойчивый к потерям TCP-соединений (RUB-3245).

Хост rubrain.com / junbrain.ru теряет ~50% SYN при установке нового соединения, а уже открытое
keep-alive соединение работает почти без потерь. Поэтому:
  * ретраится КАЖДЫЙ отдельный запрос (ретрай вокруг всей цепочки запросов не помогает: при
    p(успеха)=0.5 цепочка из N запросов проходит с вероятностью 0.5**N);
  * на каждый домен один keep-alive Session на весь прогон — теряется только connect;
  * предохранитель: домен, на котором исчерпались ретраи несколько запросов подряд, считается
    недоступным до конца прогона — иначе по-настоящему лежащий домен растягивает прогон на часы.

Клиент создаётся на один прогон и закрывается в конце (см. run_tracking в main.py).
"""
import time
from urllib.parse import urlparse

import requests

MAX_ATTEMPTS = 10  # попыток на один запрос (первая + 9 повторов)
RETRY_PAUSE = 2  # секунд между попытками

# Потерянный SYN всё равно не оживёт — ждать connect дольше 10 с смысла нет.
CONNECT_TIMEOUT = 10
# Замер на проде 02.10.2026: project-report/summary отвечает за 0.3–2.6 с (до ~200 КБ).
# 40 с — запас на порядок на рост данных, но не 30+ минут на зависший ответ с учётом ретраев.
READ_TIMEOUT = 40

# Столько исчерпанных запросов подряд — и домен считается недоступным до конца прогона.
BREAKER_THRESHOLD = 2

RETRY_STATUSES = {429, 502, 503, 504}
RETRY_EXCEPTIONS = (
    requests.exceptions.ConnectTimeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ReadTimeout,
)


class DomainUnavailable(Exception):
    """Домен помечен недоступным в этом прогоне — запрос не отправлялся."""


class RetryClient:
    def __init__(self, session_factory=requests.Session, sleep=time.sleep):
        self._session_factory = session_factory
        self._sleep = sleep
        self._sessions = {}
        self._consecutive_exhausted = {}
        self._unavailable = set()
        # домен -> {'requests': вызовов get/post, 'retries': повторных попыток, 'exhausted': сдавшихся запросов}
        self.stats = {}

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)

    def request(self, method, url, on_unauthorized=None, **kwargs):
        """Запрос с ретраями. 4xx (кроме 429) возвращается как есть — разбор остаётся за вызывающим.

        on_unauthorized: если ответ 401, один раз вызывается callback; он возвращает dict kwargs
        (например {'headers': ...}), которыми запрос повторяется. Повторный 401 возвращается как есть.
        """
        domain = urlparse(url).hostname
        if domain in self._unavailable:
            raise DomainUnavailable(domain)
        kwargs.setdefault('timeout', (CONNECT_TIMEOUT, READ_TIMEOUT))
        self._stats(domain)['requests'] += 1

        response = self._send_with_retries(domain, method, url, kwargs)
        if response.status_code == 401 and on_unauthorized is not None:
            kwargs.update(on_unauthorized())
            response = self._send_with_retries(domain, method, url, kwargs)
        return response

    def _send_with_retries(self, domain, method, url, kwargs):
        stats = self._stats(domain)
        session = self._sessions.get(domain)
        if session is None:
            session = self._sessions[domain] = self._session_factory()

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = session.request(method, url, **kwargs)
            except RETRY_EXCEPTIONS as e:
                failure = e
            else:
                if response.status_code not in RETRY_STATUSES:
                    self._consecutive_exhausted[domain] = 0
                    return response
                failure = response
            if attempt < MAX_ATTEMPTS:
                stats['retries'] += 1
                self._sleep(RETRY_PAUSE)

        stats['exhausted'] += 1
        self._consecutive_exhausted[domain] = self._consecutive_exhausted.get(domain, 0) + 1
        if self._consecutive_exhausted[domain] >= BREAKER_THRESHOLD:
            self._unavailable.add(domain)
        if isinstance(failure, Exception):
            raise failure
        failure.raise_for_status()  # 429/502/503/504 -> HTTPError

    def _stats(self, domain):
        return self.stats.setdefault(domain, {'requests': 0, 'retries': 0, 'exhausted': 0})

    def summary(self):
        """Одна строка для docker logs в конце прогона."""
        if not self.stats:
            return 'Connect retries (RUB-3245): нет запросов'
        parts = [
            f"{domain} req={s['requests']} retries={s['retries']} exhausted={s['exhausted']}"
            + (' UNAVAILABLE' if domain in self._unavailable else '')
            for domain, s in self.stats.items()
        ]
        return 'Connect retries (RUB-3245): ' + ' | '.join(parts)

    def close(self):
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
