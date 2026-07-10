from aiogram import Router, Bot, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from bot.database.models import User
from bot.keyboards.user import get_main_menu_keyboard
from bot.services.telegram import check_channel_subscription, get_subscription_keyboard

user_router = Router()

async def send_welcome_or_sub(bot: Bot, chat_id: int, db_user: User):
    """Вспомогательная функция для отправки меню или требования подписаться"""
    is_subscribed = await check_channel_subscription(bot, chat_id)
    
    if not is_subscribed:
        sub_keyboard = await get_subscription_keyboard(bot)
        if sub_keyboard:
            await bot.send_message(
                chat_id=chat_id,
                text="⚠️ <b>Доступ заблокирован!</b>\n\nДля использования VPN-бота необходимо быть подписанным на наш официальный канал. Подпишитесь и нажмите кнопку проверки ниже:",
                reply_markup=sub_keyboard
            )
            return
        # Если клавиатуру подписки создать не удалось (ошибка ссылки), пропускаем в меню
    
    # Если подписан — выводим приветствие и главное меню
    username_str = f", {db_user.username}" if db_user.username else ""
    welcome_text = (
        f"👋 Приветствуем{username_str} в нашем VPN-сервисе!\n\n"
        f"🚀 У нас доступны сверхбыстрые протоколы для обхода блокировок (XUI) "
        f"и стабильный нативный IKEv2 (StrongSwan) для iOS/macOS/роутеров без сторонних приложений.\n\n"
        f"⚙️ Выберите интересующий раздел в меню ниже:"
    )
    await bot.send_message(
        chat_id=chat_id,
        text=welcome_text,
        reply_markup=get_main_menu_keyboard()
    )

@user_router.message(CommandStart())
async def cmd_start(message: Message, db_user: User, bot: Bot):
    """Обработка команды /start"""
    await send_welcome_or_sub(bot, message.chat.id, db_user)

@user_router.callback_query(F.data == "check_sub_again")
async def cb_check_sub_again(callback: CallbackQuery, db_user: User, bot: Bot):
    """Обработка кнопки 'Я подписался, проверить'"""
    is_subscribed = await check_channel_subscription(bot, callback.from_user.id)
    
    if is_subscribed:
        await callback.answer("✅ Подписка подтверждена!", show_alert=True)
        # Удаляем сообщение с требованием подписки
        await callback.message.delete()
        # Высылаем главное меню
        await send_welcome_or_sub(bot, callback.from_user.id, db_user)
    else:
        await callback.answer("❌ Вы всё еще не подписались на канал!", show_alert=True)
