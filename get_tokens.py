import os
from dotenv import load_dotenv


def get_tokens(
        username=os.getenv("SITE_USERNAME"),
        password=os.getenv("SITE_PASSWORD"),
        url="https://smartbrain.io/api/auth/login/?active_lang=ru",
        *,
        client):
    """Логинится на платформе. client — http_client.RetryClient (ретраи, таймауты, keep-alive)."""
    response = client.post(url, json={
        'email': username,
        'password': password
    })

    if response.status_code == 200:
        return response.json()  # Возвращает access_token и refresh_token
    else:
        raise Exception('Не удалось получить токены: {}'.format(response.text))
