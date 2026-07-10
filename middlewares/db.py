from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from bot.database.db_helper import db_helper
from bot.database.crud import get_or_create_user

class DbSessionMiddleware(BaseMiddleware):
    """
    Мидлварь для автоматического управления сессиями PostgreSQL.
    Создает асинхронную сессию на каждый апдейт, регистрирует пользователя 
    и прокидывает сессию в аргументы хендлеров.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Извлекаем данные о пользователе, вызвавшем событие
        event_user = data.get("event_from_user")
        if not event_user:
            return await handler(event, data)

        # Получаем асинхронную сессию из нашего db_helper
        async for session in db_helper.session_getter():
            # Автоматически регистрируем или обновляем юзера в БД
            db_user = await get_or_create_user(
                session=session,
                telegram_id=event_user.id,
                username=event_user.username
            )
            
            # Сохраняем сессию и объект юзера в словарь data, 
            # чтобы их можно было просто забрать в аргументах любого хендлера
            data["db_session"] = session
            data["db_user"] = db_user
            
            # Передаем управление дальше по цепочке к хендлерам
            return await handler(event, data)
