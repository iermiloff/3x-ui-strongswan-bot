FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создаем папку bot внутри контейнера для правильных импортов
RUN mkdir -p /app/bot

# Копируем файлы вашего корня внутрь /app/bot
COPY config.py main.py entrypoint.sh alembic.ini /app/bot/
COPY database/ /app/bot/database/
COPY handlers/ /app/bot/handlers/
COPY keyboards/ /app/bot/keyboards/
COPY middlewares/ /app/bot/middlewares/
COPY services/ /app/bot/services/
COPY utils/ /app/bot/utils/

# Копируем папки Alembic для миграций
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Делаем entrypoint исполняемым
RUN chmod +x /app/bot/entrypoint.sh

# Смещаем рабочую директорию, чтобы скрипты видели .env в /app/bot/
WORKDIR /app/bot

# Запускаем через entrypoint
CMD ["./entrypoint.sh"]
