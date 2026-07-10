from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from bot.config import config

# Формируем строку подключения (URL) для асинхронного драйвера asyncpg
# Извлекаем пароль и токен как обычные строки через .get_secret_value()
DATABASE_URL = (
    f"postgresql+asyncpg://{config.DB_USER}:{config.DB_PASSWORD.get_secret_value()}"
    f"@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"
)

class DatabaseHelper:
    def __init__(self, url: str, echo: bool = False):
        # Создаем асинхронный движок
        self.engine = create_async_engine(
            url=url,
            echo=echo,  # Если True, в консоль будут выводиться все SQL-запросы (полезно для отладки)
        )
        # Создаем фабрику сессий
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    async def session_getter(self) -> AsyncSession:
        """Асинхронный генератор сессий для использования в хендлерах и мидлварях"""
        async with self.session_factory() as session:
            yield session
            await session.commit()

# Создаем единственный экземпляр хелпера на все приложение
db_helper = DatabaseHelper(url=DATABASE_URL, echo=False)
