#!/bin/sh
echo "Ожидаю запуск базы данных и применяю миграции Alembic..."
alembic upgrade head
echo "Миграции успешно применены! Запускаю Telegram-бота..."
exec python -m bot.main
