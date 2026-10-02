from tracking_report import tracking_report
from functions import gc
import time
from datetime import datetime as dt
from urllib.parse import urlparse
from tg_logger import logger
from get_tokens import get_tokens
from http_client import RetryClient, DomainUnavailable


# Интервал в минутах между попытками при ошибке
RETRY_DELAY_MINUTES = 5

# Интервал в минутах между успешными обходами
SUCCESS_DELAY_MINUTES = 20

# Сколько подряд неудачных попыток нужно накопить, прежде чем слать критическое
# уведомление в Telegram (дебаунс: не спамить на каждый одиночный сбой)
FAILURE_ALERT_THRESHOLD = 5


def load_sheet_config(spreadsheet_name: str) -> dict:
    """Читает лист 'config' из указанного спредшита. Возвращает dict key->value.
    Строка 1 — заголовок. Строки, начинающиеся с '#', игнорируются.
    """
    try:
        sh = gc.open(spreadsheet_name)
        ws = sh.worksheet("config")
        values = ws.get_all_values()
        out = {}
        for row in values[1:]:  # пропускаем заголовок
            if not row or not row[0] or row[0].strip().startswith("#"):
                continue
            key = row[0].strip()
            val = row[1].strip() if len(row) > 1 else ""
            if key and val:
                out[key] = val
        return out
    except Exception as e:
        print(f"[config] Ошибка чтения конфига из '{spreadsheet_name}': {e}")
        return {}


class TrackingRunFailed(Exception):
    """Агрегированная ошибка прогона: в одном прогоне пробуем всё, что можно, а сбои собираем сюда,
    чтобы дебаунс в run_with_restart_on_fail работал как раньше."""


def _describe(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:300]}"


def _run_platform(name, url, spread, auth, relogin, client, errors):
    """Один домен: свой конфиг, свои месяцы; сбой месяца не мешает остальным месяцам и домену."""
    try:
        cfg = load_sheet_config(spread)
        months = [int(m.strip()) for m in cfg.get("MONTHS", "").split(",") if m.strip().isdigit()]
        year = int(cfg.get("YEAR", dt.now().year))
        print(f"[config] {name}: months={months}, year={year}")
    except Exception as e:
        errors.append(f"{name}: конфиг: {_describe(e)}")
        return

    for i, month in enumerate(months):
        try:
            tracking_report(url, month, year, auth['access'], spread, client=client, relogin=relogin)
        except DomainUnavailable:
            errors.append(f"{name}: домен {urlparse(url).hostname} недоступен в этом прогоне, "
                          f"пропущены месяцы {months[i:]}")
            return
        except Exception as e:
            errors.append(f"{name} {month}-{year}: {_describe(e)}")


def run_tracking():
    """
    Основная логика трекинга отчётов.
    Месяцы и год берутся из листа 'config' в каждом спредшите (hot-reload).

    Домены и месяцы изолированы: сбой одного не мешает остальным. Ошибки собираются и в конце
    кидаются одним TrackingRunFailed. На каждый прогон — один RetryClient (keep-alive на домен,
    ретраи каждого запроса, предохранитель), в конце печатается строка сводки (RUB-3245).
    """
    errors = []
    client = RetryClient()
    try:
        try:
            auth = {'access': get_tokens(client=client)['access']}
        except Exception as e:
            errors.append(f"логин: {_describe(e)}")
        else:
            def relogin():
                auth['access'] = get_tokens(client=client)['access']
                return auth['access']

            # --- Rubrain трекинг ---
            rubrain_url = 'https://rubrain.com/api/v2/report/manager/project-report/summary/'
            rubrain_spread = 'Парсинг тайм-трекинга Rubrain'
            _run_platform('Rubrain', rubrain_url, rubrain_spread, auth, relogin, client, errors)

            # --- Junbrain трекинг ---
            junbrain_url = 'https://junbrain.ru/api/v2/report/manager/project-report/summary/'
            junbrain_spread = 'Парсинг тайм-трекинга Junbrain'
            _run_platform('Junbrain', junbrain_url, junbrain_spread, auth, relogin, client, errors)
    finally:
        print(client.summary())
        client.close()

    if errors:
        raise TrackingRunFailed('; '.join(errors))
    print(dt.now())


def run_with_restart_on_fail():
    """
    Основной цикл: перезапускает трекинг при ошибках с задержкой в N минут.
    Дебаунс: критическое уведомление в Telegram шлётся не на каждый сбой,
    а раз в FAILURE_ALERT_THRESHOLD подряд неудачных попыток — иначе при
    нестабильном внешнем API телеграм заваливает одинаковыми алертами.
    Если критический алерт уже уходил, при следующем успешном цикле шлётся
    одноразовое уведомление о восстановлении.
    """
    consecutive_failures = 0
    alert_sent = False
    while True:
        try:
            run_tracking()
            if alert_sent:
                logger.info(
                    f"✅ AutoTrackingReport: сервис восстановился, трекинг снова работает "
                    f"(было {consecutive_failures} сбоев подряд)"
                )
                alert_sent = False
            consecutive_failures = 0
            time.sleep(60 * SUCCESS_DELAY_MINUTES)  # Пауза между успешными обходами
        except Exception as e:
            consecutive_failures += 1
            if consecutive_failures % FAILURE_ALERT_THRESHOLD == 0:
                alert_sent = True
                # Отправка критической ошибки в Telegram
                logger.critical(
                    f"❌ AutoTrackingReport: ошибка повторяется {consecutive_failures}-й раз подряд: {e}"
                )
            else:
                print(f"AutoTrackingReport, ошибка ({consecutive_failures}/{FAILURE_ALERT_THRESHOLD}): {e}")
            # Ждём N минут перед повторным запуском
            time.sleep(60 * RETRY_DELAY_MINUTES)
            print("AutoTrackingReport, перезапуск скрипта..")


if __name__ == "__main__":
    run_with_restart_on_fail()