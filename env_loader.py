from dotenv import load_dotenv
import os


def get_secrets_path():
    """Определяет корректный путь к секретам"""
    if os.path.exists('../secrets/service_account.json'):
        return '../secrets'
    elif os.path.exists('/secrets/service_account.json'):
        return '/secrets'
    else:
        raise FileNotFoundError("Папка secrets не найдена")


def setup_environment():
    """Настраивает переменные окружения"""
    secrets_path = get_secrets_path()
    env_file_path = os.path.join(secrets_path, '.env')
    load_dotenv(env_file_path)

    return secrets_path


# Инициализация при импорте модуля
SECRETS_PATH = setup_environment()
