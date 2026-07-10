import datetime
import logging
import uuid
from aiogram import Router, Bot, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import config
from bot.database.models import User, SubscriptionType, ProtocolType, VPNKey
from bot.database.crud import check_free_trial_availability, update_free_trial_timestamp, create_subscription
from bot.keyboards.user import get_main_menu_keyboard
from bot.services.telegram import check_channel_subscription, get_subscription_keyboard
from bot.services.xui import xui_client
from bot.services.strongswan import strongswan_client

logger = logging.getLogger(__name__)
user_router = Router()

async def send_welcome_or_sub(bot: Bot, chat_id: int, db_user: User):
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
    
    username_str = f", {db_user.username}" if db_user.username else ""
    welcome_text = (
        f"👋 Приветствуем{username_str} в нашем VPN-сервисе!\n\n"
        f"🚀 У нас доступны сверхбыстрые протоколы для обхода блокировок (XUI) "
        f"и стабильный нативный IKEv2 (StrongSwan) для iOS/macOS/роутеров без сторонних приложений.\n\n"
        f"⚙️ Выберите интересующий раздел в меню ниже:"
    )
    await bot.send_message(id=chat_id, text=welcome_text, reply_markup=get_main_menu_keyboard())

@user_router.message(CommandStart())
async def cmd_start(message: Message, db_user: User, bot: Bot):
    await send_welcome_or_sub(bot, message.chat.id, db_user)

@user_router.callback_query(F.data == "check_sub_again")
async def cb_check_sub_again(callback: CallbackQuery, db_user: User, bot: Bot):
    is_subscribed = await check_channel_subscription(bot, callback.from_user.id)
    if is_subscribed:
        await callback.answer("✅ Подписка подтверждена!", show_alert=True)
        await callback.message.delete()
        await send_welcome_or_sub(bot, callback.from_user.id, db_user)
    else:
        await callback.answer("❌ Вы всё еще не подписались на канал!", show_alert=True)

# --- ЛОГИКА БЕСПЛАТНОГО ТЕСТОВОГО ПЕРИОДА ---

@user_router.callback_query(F.data == "menu_trial")
async def cb_menu_trial(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    """Выдача бесплатного периода на 1 день раз в месяц (Строго через 3x-ui)"""
    # 1. Проверяем доступность триала по календарю (база данных)
    is_available = await check_free_trial_availability(db_session, db_user.telegram_id)
    if not is_available:
        await callback.answer(
            "❌ Вы уже брали тестовый период в этом месяце!\nПовторный тест будет доступен через 30 дней с момента активации прошлой заявки.", 
            show_alert=True
        )
        return

    # Проверяем, включен ли вообще модуль XUI для выдачи тестов
    if not config.ENABLE_XUI:
        await callback.answer("❌ Извините, выдача бесплатных тестов временно недоступна.", show_alert=True)
        return

    await callback.message.edit_text("⏳ <i>Генерирую ваш тестовый ключ доступа, пожалуйста, подождите...</i>")

    issued_keys_info = []
    has_created_any = False

    # 2. Создаем подписку в БД на 1 день (тип BASE)
    sub = await create_subscription(db_session, db_user.telegram_id, SubscriptionType.BASE, duration_days=1)

    # 3. Интеграция с 3x-ui (XUI)
    try:
        inbounds = await xui_client.get_inbounds()
        if inbounds:
            # Берем первый доступный инбаунд для тестов
            target_inbound = inbounds[0]
            inbound_id = target_inbound["id"]
            protocol = target_inbound["protocol"]
            
            email = f"trial_{db_user.telegram_id}_{uuid.uuid4().hex[:4]}"
            client_uuid = await xui_client.add_client(inbound_id=inbound_id, email=email)
            
            if client_uuid:
                # Базовая строка конфигурации
                config_link = f"{protocol}://{client_uuid}@ваша_нода.com:{target_inbound['port']}?remark=Trial_{protocol}"
                
                vpn_key = VPNKey(
                    subscription_id=sub.id,
                    protocol_category=ProtocolType.XUI,
                    protocol_name=protocol.upper(),
                    client_uuid=client_uuid,
                    inbound_id=inbound_id,
                    config_data=config_link
                )
                db_session.add(vpn_key)
                issued_keys_info.append(f"🔑 <b>{protocol.upper()} (3x-ui):</b>\n<code>{config_link}</code>")
                has_created_any = True
    except Exception as e:
        logger.error(f"Ошибка при создании тестового ключа в 3x-ui: {e}")

    # 4. Итог операции
    if has_created_any:
        # Обновляем таймстамп в БД, закрывая доступ к повторному тесту на 30 дней
        await update_free_trial_timestamp(db_session, db_user.telegram_id)
        
        result_text = (
            "🎁 <b>Тестовый период успешно активирован на 1 день!</b>\n\n"
            "Ваш доступ к конфигурации:\n\n" + "\n\n".join(issued_keys_info) + 
            "\n\n⚠️ Ссылка закроется автоматически ровно через 24 часа. Купить полноценный доступ (включая iOS-премиум IKEv2) можно в главном меню."
        )
        await callback.message.edit_text(text=result_text, reply_markup=get_main_menu_keyboard())
    else:
        await callback.message.edit_text(
            text="❌ Извините, произошла техническая ошибка при генерации ключа. Обратитесь в поддержку.",
            reply_markup=get_main_menu_keyboard()
        )
