from tracking_report import tracking_report
import time
from datetime import datetime as dt
from tg_logger import logger
from get_tokens import get_tokens


# Интервал в минутах между попытками при ошибке
RETRY_DELAY_MINUTES = 5

# Интервал в минутах между успешными обходами
SUCCESS_DELAY_MINUTES = 20

def run_tracking():
    """
    Основная логика трекинга отчётов.
    При необходимости можно расширять, трекать другие площадки или периоды.
    """
    auth_token = get_tokens()['access']

    # --- Rubrain трекинг ---
    rubrain_url = 'https://rubrain.com/api/v2/report/manager/project-report/summary/'
    rubrain_result_spread = 'Парсинг тайм-трекинга Rubrain'

    tracking_report(rubrain_url, 11, 2025, auth_token, rubrain_result_spread)
    tracking_report(rubrain_url, 12, 2025, auth_token, rubrain_result_spread)

    # --- Junbrain трекинг ---
    junbrain_url = 'https://junbrain.ru/api/v2/report/manager/project-report/summary/'
    junbrain_result_spread = 'Парсинг тайм-трекинга Junbrain'

    tracking_report(junbrain_url, 11, 2025, auth_token, junbrain_result_spread)
    tracking_report(junbrain_url, 12, 2025, auth_token, junbrain_result_spread)

    print(dt.now())


def main():
    """
    Основной цикл работы скрипта.
    """
    while True:
        run_tracking()
        time.sleep(60 * SUCCESS_DELAY_MINUTES)  # Пауза между успешными обходами


def run_with_restart_on_fail():
    """
    Обёртка для main(), перезапускает основной цикл при ошибках с задержкой в N минут.
    Уведомляет через логгер о критической ошибке.
    """
    while True:
        try:
            main()
        except Exception as e:
            # Отправка критической ошибки в Telegram
            logger.critical(f"AutoTrackingReport, ошибка: {str(e)}")
            # Ждём N минут перед повторным запуском
            time.sleep(60 * RETRY_DELAY_MINUTES)
            logger.info(f"AutoTrackingReport, перезапуск скрипта..")


if __name__ == "__main__":
    run_with_restart_on_fail()