from loguru import logger
from notifiers.logging import NotificationHandler
from env_loader import SECRETS_PATH
import os

token = os.getenv("TG_TOKEN")
chat_id_1 = os.getenv("CHAT_ID_1")

params = {
    'token': token,
    'chat_id': chat_id_1
}

tg_handler = NotificationHandler('telegram', defaults=params)

logger.add(tg_handler, level='INFO')