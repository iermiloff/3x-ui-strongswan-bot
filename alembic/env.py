import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 1. Импортируем наш конфиг бота и объект Base с моделями
from bot.config import config
from bot.database.models import Base
from bot.database.db_helper import DATABASE_URL

# Получаем объект конфигурации Alembic
alembic_config = context.config

# Настраиваем логирование на основе файла alembic.ini
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# Передаем метадату наших моделей для автогенерации миграций
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Запуск миграций в offline-режиме (без реального подключения к БД)"""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    """Запуск миграций в online-режиме (с асинхронным подключением)"""
    # Динамически подставляем актуальный URL из нашего .env файла
    configuration = alembic_config.get_section(alembic_config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = DATABASE_URL

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
