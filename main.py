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

from bot.services.scheduler import setup_scheduler

# Создаем глобальную переменную для шедулера, чтобы иметь к ней доступ при остановке
scheduler = setup_scheduler()

async def on_startup(bot: Bot):
    logger.info("Бот запускается...")
    if config.ENABLE_XUI:
        success = await xui_client.login()
        if success:
            logger.info("Первичная проверка связи с 3x-ui успешна!")
        else:
            logger.warning("Не удалось связаться с 3x-ui! Проверьте панель и настройки .env")
            
    # ПРОВЕРКА СВЯЗИ СО STRONGSWAN ПО SSH:
    if getattr(config, "ENABLE_STRONGSWAN", True):
        from bot.services.strongswan import strongswan_client
        ssh_ok = await strongswan_client.check_connection()
        if not ssh_ok:
            logger.warning("⚠️ Внимание! Удаленное управление StrongSwan по SSH недоступно. Проверьте пароль root или настройки UFW на ноде!")
            
    # Запускаем планировщик фоновых задач
    scheduler.start()
    logger.info("Планировщик фоновых задач успешно запущен (Проверка в 03:00 UTC).")


async def on_shutdown(bot: Bot):
    logger.info("Бот останавливается...")
    # Останавливаем планировщик
    scheduler.shutdown()
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
