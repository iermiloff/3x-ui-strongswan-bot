FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости в корень контейнера
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создаем папку bot внутри контейнера, чтобы работали импорты вида "from bot.config"
RUN mkdir -p /app/bot

# Копируем папки вашего корня (config.py, database, handlers и т.д.) внутрь /app/bot
COPY config.py main.py entrypoint.sh alembic.ini /app/bot/
COPY database/ /app/bot/database/
COPY handlers/ /app/bot/handlers/
COPY keyboards/ /app/bot/keyboards/
├── middlewares/ /app/bot/middlewares/
├── services/ /app/bot/services/
└── utils/ /app/bot/utils/

# Копируем системные файлы Alembic для миграций в корень контейнера
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Делаем entrypoint исполняемым
RUN chmod +x /app/bot/entrypoint.sh

# Смещаем рабочую директорию, чтобы скрипты видели правильные пути
WORKDIR /app/bot

# Запускаем через entrypoint
CMD ["./entrypoint.sh"]
