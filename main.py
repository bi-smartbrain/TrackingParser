from tracking_report import tracking_report
from functions import gc
import time
from datetime import datetime as dt
from tg_logger import logger
from get_tokens import get_tokens


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


def run_tracking():
    """
    Основная логика трекинга отчётов.
    Месяцы и год берутся из листа 'config' в каждом спредшите (hot-reload).
    """
    auth_token = get_tokens()['access']

    # --- Rubrain трекинг ---
    rubrain_url = 'https://rubrain.com/api/v2/report/manager/project-report/summary/'
    rubrain_spread = 'Парсинг тайм-трекинга Rubrain'
    cfg_r = load_sheet_config(rubrain_spread)
    months_r = [int(m.strip()) for m in cfg_r.get("MONTHS", "").split(",") if m.strip().isdigit()]
    year_r = int(cfg_r.get("YEAR", dt.now().year))
    print(f"[config] Rubrain: months={months_r}, year={year_r}")
    for month in months_r:
        tracking_report(rubrain_url, month, year_r, auth_token, rubrain_spread)

    # --- Junbrain трекинг ---
    junbrain_url = 'https://junbrain.ru/api/v2/report/manager/project-report/summary/'
    junbrain_spread = 'Парсинг тайм-трекинга Junbrain'
    cfg_j = load_sheet_config(junbrain_spread)
    months_j = [int(m.strip()) for m in cfg_j.get("MONTHS", "").split(",") if m.strip().isdigit()]
    year_j = int(cfg_j.get("YEAR", dt.now().year))
    print(f"[config] Junbrain: months={months_j}, year={year_j}")
    for month in months_j:
        tracking_report(junbrain_url, month, year_j, auth_token, junbrain_spread)

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