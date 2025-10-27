FROM python:3.11-slim

WORKDIR /app

# Копируем зависимости сначала для лучшего кэширования
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

CMD ["python", "main.py"]