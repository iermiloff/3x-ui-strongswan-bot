import logging
from typing import Optional
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.config import config

logger = logging.getLogger(__name__)

async def check_channel_subscription(bot: Bot, user_id: int) -> bool:
    """
    Проверяет, подписан ли пользователь на обязательный Telegram-канал.
    Возвращает True, если подписан, и False в противном случае.
    """
    # Если ID канала не указан (например, равен 0), пропускаем проверку
    if not config.REQUIRED_CHANNEL_ID:
        return True

    try:
        member = await bot.get_chat_member(chat_id=config.REQUIRED_CHANNEL_ID, user_id=user_id)
        # Возможные статусы активного участника
        if member.status in ["member", "administrator", "creator"]:
            return True
        return False
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки пользователя {user_id} в канале {config.REQUIRED_CHANNEL_ID}: {e}")
        # Если бота удалили из канала или ID указан неверно, по умолчанию разрешаем доступ, 
        # чтобы бот не «умер» для всех пользователей. В логах будет ошибка.
        return True

async def get_subscription_keyboard(bot: Bot) -> Optional[InlineKeyboardMarkup]:
    """
    Генерирует инлайн-клавиатуру со ссылкой на канал и кнопкой «Проверить подписку».
    """
    try:
        # Получаем информацию о чате, чтобы достать прямую ссылку (если канал публичный)
        chat = await bot.get_chat(config.REQUIRED_CHANNEL_ID)
        invite_link = chat.invite_link or f"https://t.me{chat.username}" if chat.username else None
        
        if not invite_link:
            # Если ссылку получить не удалось (приватный канал без сгенерированного invite_link в боте)
            return None

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📢 Подписаться на канал", url=invite_link)
            ],
            [
                InlineKeyboardButton(text="🔄 Я подписался, проверить", callback_data="check_sub_again")
            ]
        ])
        return keyboard
    except Exception as e:
        logger.error(f"Не удалось создать клавиатуру подписки: {e}")
        return None
