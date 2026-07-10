import logging
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config import config
from bot.database.models import User, Subscription, VPNKey, ProtocolType
from bot.database.crud import get_total_users_count, get_active_subscriptions_count
from bot.services.xui import xui_client
from bot.services.strongswan import strongswan_client
from database.models import TariffInbound, SubscriptionType

logger = logging.getLogger(__name__)
admin_router = Router()

def get_admin_user_control_keyboard(user_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """Клавиатура управления конкретным пользователем"""
    status_text = "⏸ Деактивировать" if is_active else "▶️ Активировать"
    status_callback = f"adm_status_{user_id}_{'disable' if is_active else 'enable'}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=status_text, callback_data=status_callback)
        ],
        [
            InlineKeyboardButton(text="❌ Полностью удалить", callback_data=f"adm_delete_{user_id}")
        ]
    ])
    return keyboard

@admin_router.callback_query(F.data == "menu_stats")
async def cb_menu_stats(callback: CallbackQuery, db_session: AsyncSession):
    """Вывод общей статистики (доступно только админам из .env)"""
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔️ У вас нет прав доступа к этому разделу!", show_alert=True)
        return

    total_users = await get_total_users_count(db_session)
    active_subs = await get_active_subscriptions_count(db_session)


    stats_text = (
        "📊 <b>Панель статистики и управления VPN</b>\n\n"
        f"• Всего пользователей в БД: <b>{total_users}</b>\n"
        f"• Активных подписок сейчас: <b>{active_subs}</b>\n\n"
        f"⚙️ <i>Отправьте /manage ID для управления юзером.</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Настройка инбаундов 3x-ui", callback_data="adm_xui_inbounds")],
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")]
    ])
    await callback.message.edit_text(text=stats_text, reply_markup=keyboard)

@admin_router.callback_query(F.data == "adm_xui_inbounds")
async def cb_adm_xui_inbounds(callback: CallbackQuery, db_session: AsyncSession):
    """Выводит список ВСЕХ инбаундов из 3x-ui панели с их текущим тарифом"""
    if callback.from_user.id not in config.ADMIN_IDS: return

    # Подгружаем из API 3x-ui все инбаунды
    all_inbounds = await xui_client.get_inbounds()
    if not all_inbounds:
        await callback.answer("❌ Не удалось получить список инбаундов из 3x-ui", show_alert=True)
        return

    # Подгружаем из нашей БД инбаунды, которые уже привязаны к тарифам
    res = await db_session.execute(select(TariffInbound))
    db_inbounds = {i.inbound_id: i.plan_type for i in res.scalars().all()}

    text = "⚙️ <b>Настройка распределения протоколов 3x-ui</b>\n\nКликните по инбаунду, чтобы изменить его тарифный план. Пользователи получат ключи от ВСЕХ инбаундов, включенных в их тариф!\n\n"
    buttons = []

    for ib in all_inbounds:
        ib_id = ib["id"]
        current_plan = db_inbounds.get(ib_id, "❌ ОТКЛЮЧЕН")
        
        # Красивый статус для кнопки
        plan_badge = "🟢 BASE" if current_plan == "base" else "💎 PREMIUM" if current_plan == "premium" else "⚪️ НЕАКТИВЕН"
        btn_text = f"[{ib_id}] {ib['protocol'].upper()} ({ib['remark']}) -> {plan_badge}"
        
        # При клике циклически меняем тариф: none -> base -> premium -> none
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"adm_toggle_ib_{ib_id}_{ib['protocol']}_{ib['port']}_{ib['remark'][:15]}")] )

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_stats")])
    await callback.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@admin_router.callback_query(F.data.startswith("adm_toggle_ib_"))
async def cb_adm_toggle_ib(callback: CallbackQuery, db_session: AsyncSession):
    """Циклическое переключение тарифа для инбаунда"""
    if callback.from_user.id not in config.ADMIN_IDS: return
    
    # Парсим: adm_toggle_ib_{id}_{protocol}_{port}_{remark}
    parts = callback.data.split("_")
    ib_id = int(parts[3])
    protocol = parts[4]
    port = int(parts[5])
    remark = parts[6]

    # Ищем инбаунд в нашей БД
    res = await db_session.execute(select(TariffInbound).where(TariffInbound.inbound_id == ib_id))
    ib_record = res.scalar_one_or_none()

    if not ib_record:
        # Если не было — ставим BASE
        new_record = TariffInbound(inbound_id=ib_id, plan_type=SubscriptionType.BASE, protocol_name=protocol, port=port, remark=remark)
        db_session.add(new_record)
    elif ib_record.plan_type == SubscriptionType.BASE:
        # Если был BASE — повышаем до PREMIUM
        ib_record.plan_type = SubscriptionType.PREMIUM
    else:
        # Если был PREMIUM — удаляем привязку (отключаем)
        await db_session.delete(ib_record)

    await db_session.commit()
    # Мгновенно обновляем меню
    await cb_adm_xui_inbounds(callback, db_session)

@admin_router.message(Command("manage"))
async def cmd_manage_user(message: Message, db_session: AsyncSession):
    """Поиск пользователя по ID для управления его доступом"""
    if message.from_user.id not in config.ADMIN_IDS:
        return

    # Парсим ID из команды (например, /manage 123456)
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("⚠️ Использование: <code>/manage TELEGRAM_ID</code>")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ ID пользователя должен быть числом.")
        return

    # Ищем пользователя со всеми его подписками и ключами
    stmt = select(User).where(User.telegram_id == target_id).options(
        selectinload(User.subscriptions).selectinload(Subscription.keys)
    )
    result = await db_session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        await message.answer(f"❌ Пользователь с ID <code>{target_id}</code> не найден в базе данных.")
        return

    # Проверяем, есть ли у него хоть одна работающая подписка
    has_active_sub = any(s.is_active for s in user.subscriptions)
    status_str = "✅ Активен (Есть доступ)" if has_active_sub else "❌ Не активен (Нет доступа)"

    info_text = (
        f"👤 <b>Управление пользователем</b>\n\n"
        f"• Telegram ID: <code>{user.telegram_id}</code>\n"
        f"• Username: @{user.username or 'отсутствует'}\n"
        f"• Текущий статус: <b>{status_str}</b>\n"
    )
    
    await message.answer(text=info_text, reply_markup=get_admin_user_control_keyboard(user.telegram_id, has_active_sub))

@admin_router.callback_query(F.data.startswith("adm_status_"))
async def cb_admin_change_status(callback: CallbackQuery, db_session: AsyncSession):
    """Активация или деактивация всех ключей пользователя на серверах VPN"""
    if callback.from_user.id not in config.ADMIN_IDS:
        return

    parts = callback.data.split("_")
    target_id = int(parts[2])
    action = parts[3] # 'enable' или 'disable'
    enable_bool = (action == "enable")

    stmt = select(User).where(User.telegram_id == target_id).options(
        selectinload(User.subscriptions).selectinload(Subscription.keys)
    )
    result = await db_session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        await callback.answer("Пользователь не найден.")
        return

    # Переключаем статус подписок в БД и дергаем API серверов
    for sub in user.subscriptions:
        sub.is_active = enable_bool
        for key in sub.keys:
            if key.protocol_category == ProtocolType.XUI and config.ENABLE_XUI:
                await xui_client.set_client_status(inbound_id=key.inbound_id, client_uuid=key.client_uuid, enable=enable_bool)
            elif key.protocol_category == ProtocolType.IKEV2 and config.ENABLE_STRONGSWAN:
                # В StrongSwan для выключения комментируем строку в ipsec.secrets
                try:
                    l, p = key.config_data.split(":", 1)
                    await strongswan_client.set_user_status(login=l, password=p, enable=enable_bool)
                except ValueError:
                    pass

    await callback.message.edit_text(
        text=f"⚙️ Статус пользователя <code>{target_id}</code> изменен на: <b>{action.upper()}D</b>.",
        reply_markup=get_admin_user_control_keyboard(target_id, enable_bool)
    )
    await callback.answer("✅ Статус успешно синхронизирован с VPN-серверами!")

@admin_router.callback_query(F.data.startswith("adm_delete_"))
async def cb_admin_delete_user(callback: CallbackQuery, db_session: AsyncSession):
    """Полное удаление пользователя и всех его ключей с серверов и из БД"""
    if callback.from_user.id not in config.ADMIN_IDS:
        return

    target_id = int(callback.data.split("_")[2])

    stmt = select(User).where(User.telegram_id == target_id).options(
        selectinload(User.subscriptions).selectinload(Subscription.keys)
    )
    result = await db_session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        await callback.answer("Пользователь уже удален.")
        return

    # Удаляем физически со всех серверов
    for sub in user.subscriptions:
        for key in sub.keys:
            if key.protocol_category == ProtocolType.XUI and config.ENABLE_XUI:
                await xui_client.delete_client(inbound_id=key.inbound_id, client_uuid=key.client_uuid)
            elif key.protocol_category == ProtocolType.IKEV2 and config.ENABLE_STRONGSWAN:
                await strongswan_client.delete_user(login=key.client_uuid)

    # Удаляем запись из PostgreSQL (каскадно удалятся подписки и ключи благодаря ForeignKey ondelete="CASCADE")
    await db_session.delete(user)
    
    await callback.message.edit_text(text=f"🗑 Пользователь <code>{target_id}</code> и все его VPN-ключи успешно стерты из системы.")
    await callback.answer("🔥 Полное удаление завершено", show_alert=True)
