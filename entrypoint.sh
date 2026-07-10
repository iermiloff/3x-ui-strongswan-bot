#!/bin/sh

echo "⏳ Ожидаю запуск базы данных PostgreSQL (${DB_HOST}:${DB_PORT})..."

# Цикл, который проверяет доступность порта каждые 1 секунду
while ! nc -z "$DB_HOST" "$DB_PORT"; do
  sleep 1
done

echo "✅ База данных успешно запущена! Применяю миграции Alembic..."
alembic upgrade head

echo "✨ Миграции успешно применены! Запускаю Telegram-бота..."
exec python -m bot.main
