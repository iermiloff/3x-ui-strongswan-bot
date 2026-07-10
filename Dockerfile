FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости для сборки бинарных пакетов (необходимы для некоторых версий asyncpg/cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости и устанавливаем их в слой кэша Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта в контейнер
COPY . .

# Делаем наш entrypoint-скрипт миграций исполняемым
RUN chmod +x entrypoint.sh

# Запускаем скрипт, который применит миграции Alembic и включит бота
CMD ["./entrypoint.sh"]
