FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создаем структуру, чтобы импорты "from bot.config" работали идеально
RUN mkdir -p /app/bot

# Копируем файлы вашего корня внутрь папки /app/bot внутри контейнера
COPY config.py main.py entrypoint.sh alembic.ini /app/bot/
COPY database/ /app/bot/database/
COPY handlers/ /app/bot/handlers/
COPY keyboards/ /app/bot/keyboards/
COPY middlewares/ /app/bot/middlewares/
COPY services/ /app/bot/services/
COPY utils/ /app/bot/utils/

# Копируем файлы миграций в корень контейнера, где их будет искать alembic.ini
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Делаем entrypoint исполняемым
RUN chmod +x /app/bot/entrypoint.sh

# ВАЖНО: Остаемся в корневой директории /app
WORKDIR /app

# Запускаем скрипт из корня
CMD ["./bot/entrypoint.sh"]
