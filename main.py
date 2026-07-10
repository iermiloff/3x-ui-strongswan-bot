import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import config
from bot.services.xui import xui_client

# Настраиваем вывод логов в консоль
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

async def on_startup(bot: Bot):
    logger.info("Бот запускается...")
    # При старте пробуем авторизоваться в 3x-ui панель, если она включена
    if config.ENABLE_XUI:
        success = await xui_client.login()
        if success:
            logger.info("Первичная проверка связи с 3x-ui успешна!")
        else:
            logger.warning("Не удалось связаться с 3x-ui! Проверьте панель и настройки .env")

async def on_shutdown(bot: Bot):
    logger.info("Бот останавливается...")
    # Закрываем сессию клиента 3x-ui, чтобы освободить ресурсы сервера
    if config.ENABLE_XUI:
        await xui_client.close()
    logger.info("Бот успешно остановлен.")
    
async def main():
    bot = Bot(
        token=config.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    dp = Dispatcher()

    # Мидлварь для базы данных
    from bot.middlewares.db import DbSessionMiddleware
    dp.update.middleware(DbSessionMiddleware())

    # РЕГИСТРАЦИЯ РОУТЕРОВ
    from bot.handlers.user import user_router
    from bot.handlers.admin import admin_router
    dp.include_router(user_router)
    dp.include_router(admin_router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот выключен вручную через Ctrl+C.")
