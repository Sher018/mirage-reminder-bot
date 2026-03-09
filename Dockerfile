# Dockerfile для запуска бота на любом сервере с Docker
FROM python:3.11-slim

WORKDIR /app

# Зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY . .

# База данных в /data (монтировать volume)
ENV DATABASE_PATH=/data/bot.db

CMD ["python", "main.py"]
