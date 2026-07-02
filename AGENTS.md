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

### main.py
- Точка входа. Содержит основной цикл `run_with_restart_on_fail()`.
- `run_tracking()` — один обход: читает конфиг из Sheets, запускает парсинг для каждого месяца.
- `load_sheet_config(spreadsheet_name)` — читает лист `config` из спредшита, возвращает dict.
- **Hot-reload**: конфиг читается при каждом вызове `run_tracking()`. Чтобы изменения вступили в силу — просто обнови лист `config` в нужном спредшите. Перезапуск не нужен.
- Интервалы: `SUCCESS_DELAY_MINUTES = 20`, `RETRY_DELAY_MINUTES = 5`.

### tracking_report.py
- `tracking_report(query_url, month, year, access_token, result_spread)` — делает HTTP-запрос к API платформы, парсит ответ, записывает в Google Sheets.
- Очищает лист перед записью. Лист называется `{month}-{year}` (например, `3-2026`).

### functions.py
- `gc` — gspread-клиент (инициализируется при импорте через `service_account.json`).
- `write_spread_sheet(spread, sheet, report)` — очищает лист и записывает данные.
- `format_range_to_date(spread, sheet, range)` — форматирует диапазон как дату.
- `convert_to_google_date(date_string)` — конвертирует ISO-дату в Google Sheets serial number.

### get_tokens.py
- `get_tokens(username, password, url)` — логинится на платформе, возвращает `access` и `refresh` токены.
- Credentials берутся из `.env`: `SITE_USERNAME`, `SITE_PASSWORD`.
- Авторизуется на `rubrain.com` — токен работает и для `junbrain.ru` (общая платформа).

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
docker-compose up -d --build --remove-orphans
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
3. Добавить вызовы `load_sheet_config()` и `tracking_report()` по аналогии с Rubrain/Junbrain.

### Отладка
```bash
docker logs -f tracking-parser   # логи в реальном времени
```
- Строки `[config] Rubrain: months=[...], year=...` — подтверждение что конфиг прочитан.
- Если конфиг не читается — проверить название листа (`config`, строчные) и структуру (заголовок в строке 1).

## Важные нюансы

1. **Fallback при пустом конфиге**: если лист `config` недоступен или `MONTHS` пустой — парсинг не запускается (пустой список месяцев). Это безопасное поведение — нет тихой записи мусора.
2. **gc инициализируется при импорте** `functions.py` — переиспользуется во всём проекте, не создавать новый клиент.
3. **Токен авторизации**: `get_tokens()` каждый цикл делает новый логин. Если платформа начнёт блокировать — кэшировать токен с проверкой истечения.
4. **Лист очищается перед записью** (`worksheet.clear()`) — данные перезаписываются, не накапливаются.
5. **Название листа** = `{month}-{year}` (например `3-2026`). Лист должен существовать в спредшите — создать вручную или добавить автосоздание в `write_spread_sheet()`.
