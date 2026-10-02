# AGENTS.md — Инструкции для AI-ассистента

## О проекте

TrackingParser — сервис автоматического парсинга тайм-трекинга с платформ Rubrain и Junbrain.
Данные записываются в Google Sheets. Конфигурация месяцев/года — hot-reload через лист `config` в каждом спредшите.

## Сервер

- SSH: `root@bi.smartbrain.io`
- Проект: `/opt/TrackingParser/`
- Секреты: `/opt/secrets/` (`.env`, `service_account.json`)
- Авто-обновление: `/opt/auto/update_TrackingParser.sh`
- Docker Compose в папке проекта

## Архитектура

### http_client.py
- `RetryClient` — обёртка над `requests.Session`, устойчивая к потере TCP-соединений (RUB-3245, см. «Важные нюансы» п. 6). Один экземпляр на прогон `run_tracking()`, в конце `close()`.
- Один keep-alive `Session` на домен (создаётся при первом запросе к домену), `.get()` / `.post()`.
- **Ретрай каждого запроса**: до 10 попыток (`MAX_ATTEMPTS`), пауза 2 с (`RETRY_PAUSE`). Ретраятся `ConnectTimeout`, `ConnectionError`, `ReadTimeout` и ответы 429/502/503/504. Остальные 4xx возвращаются как есть (разбор — за вызывающим), ошибки парсинга не ретраятся. Исчерпание: оригинальное исключение, а для статусов — `HTTPError`.
- **Таймауты по умолчанию**: connect 10 с (потерянный SYN не оживёт), read 40 с. Замер на проде 02.10.2026: `project-report/summary` отвечает за 0.3–2.6 с (до ~200 КБ), 40 с — запас на рост данных. `ReadTimeout` тоже ретраится, поэтому значение не завышать: зависший домен растягивает прогон в 10 раз.
- **Предохранитель** (`BREAKER_THRESHOLD = 2`): два подряд исчерпанных запроса к домену → домен недоступен до конца прогона, следующие запросы мгновенно падают `DomainUnavailable` (без таймаутов). Любой ответ сервера (в т.ч. 404) сбрасывает счётчик. Новый прогон = новый клиент = домен снова пробуется.
- **401**: `get(..., on_unauthorized=callable)` — на 401 callback вызывается один раз, возвращает dict kwargs для повтора (например `{'headers': ...}`); повторный 401 возвращается как есть. Access-токен живёт 300 с (`exp-iat`, проверено), а ретраи могут растянуть прогон.
- `.stats` (по домену: `requests`, `retries`, `exhausted`) и `.summary()` — строка `Connect retries (RUB-3245): rubrain.com req=.. retries=.. exhausted=.. | junbrain.ru ...`, недоступный домен помечается `UNAVAILABLE`.

### main.py
- Точка входа. Содержит основной цикл `run_with_restart_on_fail()`.
- `run_tracking()` — один обход: создаёт `RetryClient`, логинится, читает конфиг из Sheets, запускает парсинг для каждого месяца.
- **Изоляция доменов и месяцев**: `_run_platform()` на домен; сбой месяца/конфига домена не мешает остальным месяцам и домену. `DomainUnavailable` → пропуск оставшихся месяцев этого домена. Сбой логина → парсинг не запускается. Все ошибки собираются и в конце кидаются одним `TrackingRunFailed` (сообщение: `Rubrain 9-2026: ConnectTimeout: ...; Junbrain: домен junbrain.ru недоступен ...`) — дебаунс в `run_with_restart_on_fail()` работает как раньше.
- **Сводка**: в конце каждого прогона (в т.ч. неудачного) в stdout печатается `client.summary()` — видно в `docker logs`, в Telegram не уходит.
- Токен: `relogin()` обновляет общий `auth['access']`, поэтому после 401 все следующие запросы идут уже с новым токеном.
- `load_sheet_config(spreadsheet_name)` — читает лист `config` из спредшита, возвращает dict.
- **Hot-reload**: конфиг читается при каждом вызове `run_tracking()`. Чтобы изменения вступили в силу — просто обнови лист `config` в нужном спредшите. Перезапуск не нужен.
- Интервалы: `SUCCESS_DELAY_MINUTES = 20`, `RETRY_DELAY_MINUTES = 5`.
- **Дебаунс критических уведомлений**: `FAILURE_ALERT_THRESHOLD = 5` — критическое сообщение в Telegram (`logger.critical`, с иконкой ❌) шлётся не на каждый сбой, а раз в 5 подряд неудачных попыток. Промежуточные сбои логируются через `print()` (видно в `docker logs`, но не спамит телеграм). Добавлено после инцидента с нестабильным бэкендом Rubrain/Junbrain 26-27 сентября 2026, когда каждый retry слал отдельный critical-алерт.
- **Уведомление о восстановлении**: если критический алерт уже уходил, при следующем успешном цикле в Telegram шлётся одноразовое сообщение с ✅ ("сервис восстановился").

### tracking_report.py
- `tracking_report(query_url, month, year, access_token, result_spread, client, relogin=None)` — делает HTTP-запрос к API платформы через общий `RetryClient`, парсит ответ, записывает в Google Sheets. `relogin` — callable, возвращающий свежий access-токен (вызывается один раз на 401).
- **Порядок критичен**: сначала данные полностью получены и разобраны, и только потом `write_spread_sheet` (там `worksheet.clear()`). Любая ошибка раньше (сеть, HTTP, битый JSON, неожиданная структура, сбой на середине разбора) оставляет лист нетронутым. Покрыто тестами — не менять порядок.
- Очищает лист перед записью. Лист называется `{month}-{year}` (например, `3-2026`).

### functions.py
- `gc` — gspread-клиент (инициализируется при импорте через `service_account.json`).
- `write_spread_sheet(spread, sheet, report)` — очищает лист и записывает данные.
- `format_range_to_date(spread, sheet, range)` — форматирует диапазон как дату.
- `convert_to_google_date(date_string)` — конвертирует ISO-дату в Google Sheets serial number.

### get_tokens.py
- `get_tokens(username, password, url, *, client)` — логинится на платформе через `RetryClient` (ретраи и таймауты; `client` обязателен), возвращает `access` и `refresh` токены.
- Credentials берутся из `.env`: `SITE_USERNAME`, `SITE_PASSWORD`.
- Авторизуется на `smartbrain.io` (англоязычный клон rubrain.com, тот же бэкенд/БД, но более стабильный маршрут с нашего сервера) — токен работает и для `junbrain.ru` (общая платформа).
- **Почему не smartbrain.io и для самого отчёта тоже**: на английской версии у ~половины фрилансеров `first_name`/`last_name` в API — `null` (не заполняли англоязычный профиль), альтернативного поля с именем нет. Если тянуть сам отчёт с smartbrain.io, колонка `developer` в таблице превратится в "None None" для части записей (баг уже ловили 1-2 июля 2026 — тогда откатили весь свитч не разобравшись; 28-29 сентября 2026 разобрались: дело только в отчёте, логин безопасен). Поэтому переключён **только логин**, `rubrain_url`/`junbrain_url` в `main.py` остаются на `rubrain.com`/`junbrain.ru`.

### tg_logger.py
- Loguru-логгер с хендлером Telegram (`notifiers`).
- Уведомляет в Telegram при `logger.critical()` и `logger.info()`.
- Использует `TG_TOKEN` и `CHAT_ID_1` из `.env`.

### env_loader.py
- Определяет путь к секретам: `/secrets/` (Docker) или `../secrets/` (локально).
- Загружает `.env` из secrets-директории при импорте.
- `SECRETS_PATH` — публичная переменная, используется в `functions.py`.

## Google Sheets структура

### Конфиг (лист `config` в каждом спредшите)

| key | value | описание |
|-----|-------|----------|
| MONTHS | `3,4` | Список месяцев через запятую |
| YEAR | `2026` | Год парсинга |

- Строка 1 — заголовок (пропускается).
- Строки, начинающиеся с `#` в колонке A, — комментарии (игнорируются).
- Изменения подхватываются при следующем цикле (до 20 минут).

### Данные (листы `{month}-{year}`)

Каждый лист = один месяц. Колонки: `developer`, `project_id`, `project_name`, `created`, `date`, `description`, `hours`, `hours_norma`, `hours_summary`, `minutes`, `modified`, `report_type`, `status`.

### Спредшиты

- `Парсинг тайм-трекинга Rubrain` — данные с rubrain.com
- `Парсинг тайм-трекинга Junbrain` — данные с junbrain.ru

## CI/CD — автодеплой

Деплой происходит **автоматически** при каждом `git push origin main` через GitHub Actions.

### Workflow: `.github/workflows/deploy.yml`
- Триггер: push в ветку `main`
- SSH на `root@bi.smartbrain.io` → запускает `/opt/auto/update_TrackingParser.sh`
- Секрет: `SSH_PRIVATE_KEY` в Settings → Secrets → Actions репозитория

### Ручной деплой
```bash
ssh root@bi.smartbrain.io "bash /opt/auto/update_TrackingParser.sh"
```

**Если автодеплой падает мгновенно (~1 сек) с ошибкой SSH-шага**: вероятно,
`/opt/auto/update_TrackingParser.sh` отсутствует на сервере (bootstrap не
завершён — так было 27.09.2026). Разово создать вручную:
```bash
ssh root@bi.smartbrain.io "cd /opt/TrackingParser && cp scripts/update_TrackingParser.sh /opt/auto/update_TrackingParser.sh && chmod +x /opt/auto/update_TrackingParser.sh"
```
Если падает не мгновенно, а на самом SSH-рукопожатии — см. `~/.claude/CLAUDE.md`
про сверку `SSH_PRIVATE_KEY` по fingerprint.

## Деплой паттерн

### Dockerfile
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

### docker-compose.yml
```yaml
services:
  tracking-parser:
    build: .
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
      - TZ=Europe/Moscow
    volumes:
      - /opt/secrets:/secrets:ro
      - ./logs:/app/logs
```

### update скрипт (/opt/auto/update_TrackingParser.sh)
```bash
set -e
cd /opt/TrackingParser
git fetch origin main
git reset --hard origin/main
docker compose up -d --build --remove-orphans
docker image prune -f
docker builder prune -f --filter "until=168h"
cp scripts/update_TrackingParser.sh /opt/auto/update_TrackingParser.sh
chmod +x /opt/auto/update_TrackingParser.sh
```

## Частые задачи

### Сменить месяцы парсинга
Открыть лист `config` в нужном спредшите, обновить значение `MONTHS` (например, `4,5`).
Перезапуск не нужен — подхватится при следующем цикле.

### Сменить год
Обновить `YEAR` в листе `config`. Аналогично — без перезапуска.

### Добавить новую платформу
1. Добавить URL новой платформы в `main.py` → `run_tracking()`.
2. Создать новый спредшит с листом `config` (структура та же).
3. Добавить вызов `_run_platform(...)` по аналогии с Rubrain/Junbrain — он сам читает конфиг, изолирует сбои месяцев и использует общий `RetryClient`.

### Отладка
```bash
docker logs -f tracking-parser   # логи в реальном времени
```
- Строки `[config] Rubrain: months=[...], year=...` — подтверждение что конфиг прочитан.
- Строка `Connect retries (RUB-3245): rubrain.com req=.. retries=.. exhausted=.. | junbrain.ru ... | smartbrain.io ...` в конце каждого прогона — статистика ретраев по доменам (см. «Важные нюансы» п. 6).

### Тесты
Без сети и без новых зависимостей (стандартный `unittest`), из корня проекта:
```bash
python -m unittest discover -s tests -t .
```
`functions` и `tg_logger` в тестах подменяются заглушками (`tests/fakes.py`): настоящие при импорте лезут в Google Sheets и Telegram. Локально `main.py` против прод-таблиц не запускать — он чистит и пишет листы.
- Если конфиг не читается — проверить название листа (`config`, строчные) и структуру (заголовок в строке 1).

## Важные нюансы

1. **Fallback при пустом конфиге**: если лист `config` недоступен или `MONTHS` пустой — парсинг не запускается (пустой список месяцев). Это безопасное поведение — нет тихой записи мусора.
2. **gc инициализируется при импорте** `functions.py` — переиспользуется во всём проекте, не создавать новый клиент.
3. **Токен авторизации**: `get_tokens()` каждый цикл делает новый логин. Если платформа начнёт блокировать — кэшировать токен с проверкой истечения. Access-токен живёт 5 минут, а ретраи могут растянуть прогон: на 401 запрос один раз перелогинивается (`relogin`) и повторяется, повторный 401 — ошибка. API на неверный токен отвечает именно 401 (проверено на проде).
4. **Лист очищается перед записью** (`worksheet.clear()`) — данные перезаписываются, не накапливаются.
5. **Название листа** = `{month}-{year}` (например `3-2026`). Лист должен существовать в спредшите — создать вручную или добавить автосоздание в `write_spread_sheet()`.
6. **Бэкенд Rubrain/Junbrain теряет ~50% TCP SYN при установке нового соединения** (RUB-3245). rubrain.com, junbrain.ru и engibrain.ru резолвятся в один IP `158.160.145.254` (Yandex Cloud); smartbrain.io — другая площадка (`116.202.129.176`), потерь там нет. ICMP проходит, снаружи хост доступен, уже установленное keep-alive соединение работает почти без потерь — страдают только клиенты, открывающие новые соединения (в т.ч. bi-server, egress-IP `46.202.155.155` — его же заявляли в DevOps по whitelist; AAAA-записей нет, IPv6 не участвует). Замер с bi-server 02.10.2026: ~30–57% потерянных connect на rubrain.com/junbrain.ru (`curl --connect-timeout 6`; 30 свежих соединений: 39 и 20 ретраев), 0% на smartbrain.io. До фикса: 480 строк `ConnectTimeout`/`Max retries` за 72 ч, 28 серий сбоев подряд (до 60 попыток), 82 критических алерта в Telegram.
   - **Что работает**: ретрай каждого отдельного запроса + keep-alive `Session` + предохранитель — всё это `http_client.RetryClient` (см. архитектуру). Принцип: теряется только connect, а не обмен по открытому соединению.
   - **Что НЕ работает**: ретрай вокруг всей многошаговой операции. При p(успеха)≈0.5 на connect цепочка из N запросов проходит с вероятностью 0.5^N (у соседнего сервиса первая попытка с 8 такими циклами дала 100% отказ). Поэтому не оборачивать `run_tracking()` в ретраи и не создавать `Session`/`requests.get` на каждый вызов.
   - Остаточные сбои возможны, если домен реально лежит: тогда предохранитель отрубает его после двух исчерпанных запросов, остальные домены/месяцы продолжают работать, а в конце прогона `TrackingRunFailed` уходит в дебаунс (`FAILURE_ALERT_THRESHOLD`). Тревогу стоит бить только если сбои продолжаются подряд без единого успешного цикла.
   - Строку `Connect retries (RUB-3245): ...` в `docker logs` смотреть для оценки: `retries` > 0 при `exhausted=0` — нормальный режим (потери вылечены ретраями), `exhausted` > 0 или `UNAVAILABLE` — домен реально недоступен.
