import os
import datetime
from dotenv import load_dotenv
from closeio_api import Client
import gspread
from gspread.utils import rowcol_to_a1
from env_loader import SECRETS_PATH

SERVICE_ACCOUNT_FILE = os.path.join(SECRETS_PATH, 'service_account.json')
gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)

api_key = os.getenv('CLOSE_API_KEY_MARY')
api = Client(api_key)



def write_spread_sheet(spread, sheet, report):
    """
    Очищает лист гугл таблицы и записывает на него отчет
    :param spread: гугл таблица (название)
    :param sheet: название листа
    :param report: отчет в виде списка списков
    :return: None
    """
    sh = gc.open(spread)
    worksheet = sh.worksheet(sheet)
    worksheet.clear()
    print(f"Лист {sheet} в таблице {spread} очищен")

    # Получить размеры отчета (количество строк и столбцов)
    num_rows = len(report)
    num_cols = len(report[0])

    # Получить диапазон для записи данных
    start_cell = rowcol_to_a1(1, 1)
    end_cell = rowcol_to_a1(num_rows, num_cols)

    # Записать значения в диапазон
    cell_range = f"{start_cell}:{end_cell}"
    worksheet.update(report, cell_range, value_input_option="user_entered")

    print("Отчет записан")



def format_range_to_date(spread, sheet, range):
    sh = gc.open(spread)
    worksheet = sh.worksheet(sheet)
    worksheet.format(f"{range}", {'numberFormat': {'type': 'DATE',
                                                   'pattern': 'dd.mm.yyyy'}})
    print(f"Формат диапазона {range} в файле {spread} на листе {sheet} изменен на формат даты")



def convert_to_google_date(date_string, inc_pattern="%Y-%m-%d"):
    try:
        date_obj = datetime.datetime.strptime(date_string, inc_pattern)
        google_date = date_obj.toordinal() - datetime.datetime(1899, 12, 30).toordinal()
        return google_date
    except ValueError:
        return "Неверный формат даты. Пожалуйста, используйте формат 'yyyy-mm-dd'."

