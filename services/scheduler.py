import datetime
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from bot.config import config
from bot.database.db_helper import db_helper
from bot.database.models import Subscription, ProtocolType
from bot.services.xui import xui_client
from bot.services.strongswan import strongswan_client

logger = logging.getLogger(__name__)

async def deactivate_expired_subscriptions():
    """Фоновая задача: поиск и отключение просроченных подписок"""
    logger.info("Запуск ночной проверки и отключения просроченных подписок...")
    now = datetime.datetime.utcnow()
    
    # Получаем сессию базы данных
    async for session in db_helper.session_getter():
        # Ищем все активные подписки, у которых истек срок действия
        stmt = (
            select(Subscription)
            .where(Subscription.is_active == True)
            .where(Subscription.expires_at <= now)
            .options(selectinload(Subscription.keys))
        )
        
        result = await session.execute(stmt)
        expired_subs = result.scalars().all()
        
        if not expired_subs:
            logger.info("Просроченных подписок не найдено.")
            return

        logger.info(f"Найдено {len(expired_subs)} просроченных подписок. Начинаю блокировку...")
        
        for sub in expired_subs:
            # 1. Меняем статус в локальной БД бота
            sub.is_active = False
            
            # 2. Отключаем ключи на удаленных серверах VPN
            for key in sub.keys:
                if key.protocol_category == ProtocolType.XUI and config.ENABLE_XUI:
                    try:
                        await xui_client.set_client_status(
                            inbound_id=key.inbound_id, 
                            client_uuid=key.client_uuid, 
                            enable=False
                        )
                        logger.info(f"Ключ XUI {key.client_uuid} успешно деактивирован.")
                    except Exception as e:
                        logger.error(f"Ошибка деактивации XUI ключа {key.client_uuid}: {e}")
                        
                elif key.protocol_category == ProtocolType.IKEV2 and config.ENABLE_STRONGSWAN:
                    try:
                        # В нашей новой схеме swanctl передаем логин и пароль
                        # Метод set_user_status переименует файл в .disabled и сделает reload
                        login = key.client_uuid
                        # Извлекаем пароль из config_data (формат login:password)
                        _, password = key.config_data.split(":", 1)
                        
                        await strongswan_client.set_user_status(login=login, password=password, enable=False)
                        logger.info(f"Аккаунт StrongSwan {login} успешно переведен в .disabled")
                    except Exception as e:
                        logger.error(f"Ошибка деактивации StrongSwan аккаунта {key.client_uuid}: {e}")

        # Фиксируем массовое отключение в БД
        await session.commit()
        logger.info("Все просроченные подписки успешно обработаны и сохранены.")

def setup_scheduler():
    """Инициализация и запуск планировщика задач"""
    scheduler = AsyncIOScheduler(timezone="UTC")
    
    # Настраиваем запуск задачи раз в сутки ровно в 03:00 ночи по UTC
    scheduler.add_job(
        deactivate_expired_subscriptions,
        trigger="cron",
        hour=3,
        minute=0,
        id="expired_subs_cleaner"
    )
    
    return scheduler
