#!/bin/sh

echo "⏳ Ожидаю запуск базы данных PostgreSQL..."

# Запускаем однострочник на чистом Python, который пингует порт базы данных
python -c "
import socket
import time
import os

host = os.getenv('DB_HOST', 'postgres_db')
port = int(os.getenv('DB_PORT', 5432))

while True:
    try:
        with socket.create_connection((host, port), timeout=1):
            break
    except (OSError, ConnectionRefusedError):
        time.sleep(1)
"

echo "✅ База данных успешно запущена! Применяю миграции Alembic..."
alembic upgrade head

echo "✨ Миграции успешно применены! Запускаю Telegram-бота..."
exec python -m bot.main
