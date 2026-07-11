import logging
import datetime
import uuid
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config import config
from bot.database.models import User, Subscription, VPNKey, ProtocolType, SubscriptionType, TariffInbound
from bot.database.crud import create_subscription
from bot.services.xui import xui_client
from bot.services.link_generator import generate_xui_link
from bot.keyboards.user import get_main_menu_keyboard

logger = logging.getLogger(__name__)
admin_router = Router()

# Состояния FSM для создания клиента вручную
class AdminStates(StatesGroup):
    wait_for_tg_id = State()

# Жесткий глобальный фильтр роутера: только для ADMIN_IDS из .env
admin_router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
admin_router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

def get_admin_user_control_keyboard(user_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """Клавиатура управления конкретным пользователем"""
    status_text = "⏸ Деактивировать доступ" if is_active else "▶️ Активировать доступ"
    status_callback = f"adm_status_{user_id}_{'disable' if is_active else 'enable'}"
    
    keyboard = [
        [InlineKeyboardButton(text=status_text, callback_data=status_callback)],
        [InlineKeyboardButton(text="❌ Полностью удалить из системы", callback_data=f"adm_delete_{user_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="admin_list_users")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@admin_router.callback_query(F.data == "admin_main")
async def cb_admin_global_stats(callback: CallbackQuery, db_session: AsyncSession):
    """Оживление кнопки: Глобальная статистика СУБД"""
    await callback.answer()
    
    res_users = await db_session.execute(select(User))
    total_users = len(res_users.scalars().all())
    
    res_subs = await db_session.execute(
        select(Subscription).where(Subscription.expires_at > datetime.datetime.utcnow())
    )
    active_subs = len(res_subs.scalars().all())
    
    res_keys = await db_session.execute(select(VPNKey))
    total_keys = len(res_keys.scalars().all())

    admin_text = (
        f"📊 <b>Глобальная статистика базы данных:</b>\n\n"
        f"• Всего клиентов в СУБД: <code>{total_users}</code>\n"
        f"• Активных подписок (VPN работает): <code>{active_subs}</code>\n"
        f"• Всего сгенерировано ключей доступа: <code>{total_keys}</code>\n"
    )
    keyboard = [[InlineKeyboardButton(text="🔙 В админку", callback_data="back_to_main")]]
    await callback.message.edit_text(text=admin_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@admin_router.callback_query(F.data == "admin_list_users")
async def cb_admin_list_users(callback: CallbackQuery, db_session: AsyncSession):
    """Вывод списка всех клиентов с интерактивными кнопками управления"""
    await callback.answer()
    res = await db_session.execute(select(User))
    users = res.scalars().all()
    
    user_text = (
        "👥 <b>Управление клиентами Overlord VPN:</b>\n\n"
        "Кликните по кнопке с Telegram ID нужного пользователя, "
        "чтобы открыть карточку управления его доступом:\n"
    )
    buttons = []
    
    for u in users:
        username_tag = f" (@{u.username})" if u.username else ""
        btn_text = f"👤 ID: {u.telegram_id}{username_tag}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"adm_manage_view_{u.telegram_id}")])
        
    buttons.append([InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_main")])
    await callback.message.edit_text(text=user_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@admin_router.callback_query(F.data.startswith("adm_manage_view_"))
async def cb_admin_manage_view(callback: CallbackQuery, db_session: AsyncSession):
    """Экран управления конкретным юзером по клику из списка"""
    await callback.answer()
    target_id = int(callback.data.split("_")[-1])
    
    stmt = select(User).where(User.telegram_id == target_id).options(
        selectinload(User.subscriptions).selectinload(Subscription.keys)
    )
    result = await db_session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await callback.message.edit_text("❌ Пользователь не найден.", reply_markup=get_admin_user_control_keyboard(target_id, False))
        return
        
    has_active_sub = any(s.is_active and s.expires_at > datetime.datetime.utcnow() for s in user.subscriptions)
    status_str = "✅ Доступ активен" if has_active_sub else "❌ Доступ заблокирован / Истек"
    
    info_text = (
        f"👤 <b>Карточка управления клиентом</b>\n\n"
        f"• <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
        f"• <b>Юзернейм:</b> @{user.username or 'отсутствует'}\n"
        f"• <b>Текущий статус:</b> <b>{status_str}</b>\n"
    )
    await callback.message.edit_text(text=info_text, reply_markup=get_admin_user_control_keyboard(user.telegram_id, has_active_sub))

@admin_router.callback_query(F.data.startswith("adm_status_"))
async def cb_admin_change_status(callback: CallbackQuery, db_session: AsyncSession):
    """Активация или деактивация всех ключей пользователя на серверах VPN"""
    parts = callback.data.split("_")
    target_id = int(parts[2])
    action = parts[3]
    enable_bool = (action == "enable")
    
    stmt = select(User).where(User.telegram_id == target_id).options(
        selectinload(User.subscriptions).selectinload(Subscription.keys)
    )
    result = await db_session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден.")
        return
        
    for sub in user.subscriptions:
        sub.is_active = enable_bool
        for key in sub.keys:
            if key.protocol_category == ProtocolType.XUI and config.ENABLE_XUI:
                await xui_client.set_client_status(inbound_id=key.inbound_id, client_uuid=key.client_uuid, enable=enable_bool)
            elif key.protocol_category == ProtocolType.IKEV2 and config.ENABLE_STRONGSWAN:
                try:
                    from bot.services.strongswan import strongswan_client
                    l, p = key.config_data.split(":", 1)
                    await strongswan_client.set_user_status(login=l, password=p, enable=enable_bool)
                except Exception: pass
                
    await db_session.commit()
    await callback.answer("✨ Статус успешно синхронизирован с серверами!")
    await cb_admin_list_users(callback, db_session)

@admin_router.callback_query(F.data.startswith("adm_delete_"))
async def cb_admin_delete_user(callback: CallbackQuery, db_session: AsyncSession):
    """Полное каскадное удаление пользователя и всех его ключей с серверов и СУБД"""
    target_id = int(callback.data.split("_")[2])
    stmt = select(User).where(User.telegram_id == target_id).options(
        selectinload(User.subscriptions).selectinload(Subscription.keys)
    )
    result = await db_session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь уже удален.")
        return
        
    for sub in user.subscriptions:
        for key in sub.keys:
            if key.protocol_category == ProtocolType.XUI and config.ENABLE_XUI:
                await xui_client.delete_client(inbound_id=key.inbound_id, client_uuid=key.client_uuid)
            elif key.protocol_category == ProtocolType.IKEV2 and config.ENABLE_STRONGSWAN:
                try:
                    from bot.services.strongswan import strongswan_client
                    await strongswan_client.delete_user(login=key.client_uuid)
                except Exception: pass
                
    await db_session.delete(user)
    await db_session.commit()
    await callback.answer("🗑 Клиент полностью стерт из системы!", show_alert=True)
    await cb_admin_list_users(callback, db_session)

# --- ЛОГИКА РУЧНОГО СОЗДАНИЯ ПОЛЬЗОВАТЕЛЯ И ВЫДАЧИ КЛЮЧЕЙ ---
@admin_router.callback_query(F.data == "admin_create_manual")
async def cb_admin_create_manual_start(callback: CallbackQuery, state: FSMContext):
    """Старт сценария создания клиента вручную"""
    await callback.answer()
    await state.set_state(AdminStates.wait_for_tg_id)
    keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_list_users")]]
    await callback.message.edit_text(
        text="➕ <b>Создание клиента вручную</b>\n\nОтправьте текстовым сообщением <b>Telegram ID</b> пользователя, для которого нужно сгенерировать подписку (30 дней):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@admin_router.message(AdminStates.wait_for_tg_id)
async def msg_admin_create_manual_finish(message: Message, state: FSMContext, db_session: AsyncSession):
    """Финал создания: регистрация в СУБД и пачка во все инбаунды панели 3x-ui"""
    try:
        target_tg_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Ошибка! Telegram ID должен состоять строго из цифр. Попробуйте еще раз:")
        return
        
    await state.clear()
    wait_msg = await message.answer("🔄 <i>Регистрирую клиента на серверах и собираю мульти-протокольные ключи...</i>")
    
    # 1. Проверяем/создаем самого юзера в СУБД через .scalar()
    res_u = await db_session.execute(select(User).where(User.telegram_id == target_tg_id))
    db_user = res_u.scalar()
    if not db_user:
        db_user = User(telegram_id=target_tg_id, username=f"manual_{target_tg_id}")
        db_session.add(db_user)
        await db_session.flush()
        
    # 2. Создаем подписку на 30 дней (BASE)
    sub = await create_subscription(db_session, target_tg_id, SubscriptionType.BASE, duration_days=30)
    
    # 3. Находим инбаунды тарифа BASE и пуляем пачкой на сервер
    res_ib = await db_session.execute(select(TariffInbound).where(TariffInbound.plan_type == SubscriptionType.BASE))
    active_tariff_inbounds = res_ib.scalars().all()
    
    issued_keys_info = []
    if active_tariff_inbounds and config.ENABLE_XUI:
        try:
            inbound_ids_pack = [ib.inbound_id for ib in active_tariff_inbounds]
            email = f"manual_{target_tg_id}_{uuid.uuid4().hex[:4]}"
            client_info = await xui_client.add_client(inbound_ids=inbound_ids_pack, email=email)
            
            if client_info and isinstance(client_info, dict):
                inbounds_list = await xui_client.get_inbounds()
                if not inbounds_list:
                    inbounds_list = []
                    
                for ib in active_tariff_inbounds:
                    target_inbound = next((inb for inb in inbounds_list if inb.get("id") == ib.inbound_id), None)
                    if target_inbound:
                        config_link = generate_xui_link(target_inbound, client_info["uuid"], email, client_info)
                        vpn_key = VPNKey(
                            subscription_id=sub.id,
                            protocol_category=ProtocolType.XUI,
                            protocol_name=ib.protocol_name.upper(),
                            client_uuid=client_info["uuid"],
                            inbound_id=ib.inbound_id,
                            config_data=config_link
                        )
                        db_session.add(vpn_key)
                        issued_keys_info.append(f"🚀 <b>Ключ {ib.protocol_name.upper()}:</b>\n<code>{config_link}</code>")
        except Exception as e:
            logger.error(f"Ошибка ручного добавления в XUI: {e}")
            
    await db_session.commit()
    await wait_msg.delete()
    
    result_text = (
        f"✅ <b>Клиент успешно создан вручную!</b>\n\n"
        f"• <b>Telegram ID:</b> <code>{target_tg_id}</code>\n"
        f"• <b>Срок подписки:</b> 30 дней\n\n"
        f"📋 <b>Сгенерированные мульти-протокольные ключи:</b>\n\n" + "\n\n".join(issued_keys_info) +
        f"\n\nПередайте эти конфигурации пользователю. Он также сможет увидеть их в своем личном кабинете при нажатии /start."
    )
    await message.answer(text=result_text, reply_markup=get_main_menu_keyboard(message.from_user.id))

# Встроенные методы для работы с тарифами инбаундов со страницы 2 вашего PDF
@admin_router.callback_query(F.data == "adm_xui_inbounds")
async def cb_adm_xui_inbounds(callback: CallbackQuery, db_session: AsyncSession):
    await callback.answer()
    all_inbounds = await xui_client.get_inbounds()
    if not all_inbounds:
        await callback.answer("❌ Не удалось получить список инбаундов из 3x-ui", show_alert=True)
        return
    res = await db_session.execute(select(TariffInbound))
    db_inbounds = {i.inbound_id: i.plan_type for i in res.scalars().all()}
    text = "⚙️ <b>Настройка распределения протоколов 3x-ui</b>\n\nКликните по инбаунду, чтобы изменить его тарифный план. Пользователи получат ключи от ВСЕХ инбаундов вашего тарифа:\n\n"
    buttons = []
    for ib in all_inbounds:
        ib_id = ib["id"]
        current_plan = db_inbounds.get(ib_id, "❌ ОТКЛЮЧЕН")
        plan_badge = "🟢 BASE" if current_plan == "base" else "💎 PREMIUM" if current_plan == "premium" else "⚪️ НЕАКТИВЕН"
        btn_text = f"[{ib_id}] {ib['protocol'].upper()} ({ib['remark']}) -> {plan_badge}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"adm_tg_ib_{ib_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_main")])
    await callback.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@admin_router.callback_query(F.data.startswith("adm_tg_ib_"))
async def cb_adm_toggle_ib(callback: CallbackQuery, db_session: AsyncSession):
    ib_id = int(callback.data.split("_")[-1])
    all_inbounds = await xui_client.get_inbounds()
    target_inbound = next((ib for ib in all_inbounds if ib["id"] == ib_id), None) if all_inbounds else None
    if not target_inbound:
        await callback.answer("❌ Этот инбаунд больше не существует в панели!", show_alert=True)
        return
    res = await db_session.execute(select(TariffInbound).where(TariffInbound.inbound_id == ib_id))
    ib_record = res.scalar_one_or_none()
    if not ib_record:
        new_record = TariffInbound(inbound_id=ib_id, plan_type=SubscriptionType.BASE, protocol_name=target_inbound["protocol"], port=target_inbound["port"], remark=target_inbound["remark"])
        db_session.add(new_record)
    elif ib_record.plan_type == SubscriptionType.BASE:
        ib_record.plan_type = SubscriptionType.PREMIUM
    else:
        await db_session.delete(ib_record)
    await db_session.commit()
    await callback.answer("✨ Изменения сохранены!")
    await cb_adm_xui_inbounds(callback, db_session)
