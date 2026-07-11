import logging
import json
import uuid
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton # Явный чистый импорт
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.config import config
from bot.database.models import User, Subscription, VPNKey, ProtocolType, SubscriptionType, TariffInbound
from bot.services.xui import xui_client
from bot.services.link_generator import generate_xui_link, create_qr_code_file

logger = logging.getLogger(__name__)
user_router = Router()

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    # Собираем матрицу кнопок напрямую, без билдеров, со строгими именованными аргументами
    inline_keyboard = [
        [InlineKeyboardButton(text="🎁 Бесплатный тест (1 день)", callback_query_data="menu_trial")],
        [InlineKeyboardButton(text="💎 Купить подписку", callback_query_data="menu_tariffs")],
        [InlineKeyboardButton(text="👤 Мой профиль / Ключи", callback_query_data="menu_profile")],
        [InlineKeyboardButton(text="📊 Статистика", callback_query_data="menu_stats")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


@user_router.message(CommandStart())
async def cmd_start(message: Message, db_session: AsyncSession):
    tg_id = message.from_user.id
    res = await db_session.execute(select(User).where(User.telegram_id == tg_id))
    db_user = res.scalar()
    
    if not db_user:
        db_user = User(telegram_id=tg_id, username=message.from_user.username)
        db_session.add(db_user)
        await db_session.commit()
        
    welcome_text = (
        f"👋 <b>Приветствуем вас в Overlord VPN!</b>\n\n"
        f"Наши ноды развернуты на производительных серверах в Финляндии. Маскировка "
        f"<b>Reality gRPC</b> полностью имитирует обычный TLS-трафик браузера и "
        f"на 100% защищена от блокировок ТСПУ и глубокого анализа пакетов (DPI).\n\n"
        f"👉 Выберите нужное действие в меню ниже:"
    )

    # ЖЕСТКАЯ ЗАЩИТА: Объявляем матрицу кнопок прямо в теле ответа, полностью исключая кэши функций!
    direct_keyboard = [
        [InlineKeyboardButton(text="🎁 Бесплатный тест (1 день)", callback_query_data="menu_trial")],
        [InlineKeyboardButton(text="💎 Купить подписку", callback_query_data="menu_tariffs")],
        [InlineKeyboardButton(text="👤 Мой профиль / Ключи", callback_query_data="menu_profile")],
        [InlineKeyboardButton(text="📊 Статистика", callback_query_data="menu_stats")]
    ]
    
    await message.answer(
        text=welcome_text, 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=direct_keyboard)
    )

@user_router.callback_query(F.data == "menu_main")
async def cb_menu_main(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(text="👉 Выберите нужное действие в меню ниже:", reply_markup=get_main_menu_keyboard())

@user_router.callback_query(F.data == "menu_trial")
async def cb_menu_trial(callback: CallbackQuery, db_session: AsyncSession):
    await callback.answer()
    tg_id = callback.from_user.id
    res_user = await db_session.execute(select(User).where(User.telegram_id == tg_id))
    db_user = res_user.scalar()
    
    if db_user and db_user.free_trial_used_at:
        delta = datetime.utcnow() - db_user.free_trial_used_at
        if delta.days < 30:
            await callback.message.answer("❌ Вы уже брали бесплатный тестовый период в этом месяце!\nПовторный тест будет доступен через 30 дней.")
            return

    res_inbounds = await db_session.execute(select(TariffInbound).where(TariffInbound.plan_type == SubscriptionType.BASE))
    active_tariff_inbounds = res_inbounds.scalars().all()
    
    if not active_tariff_inbounds:
        await callback.message.answer("❌ Ошибка: В панели администратора бота пока не настроены порты для базового тарифа.")
        return

    sub = Subscription(user_id=tg_id, plan_type=SubscriptionType.BASE, expires_at=datetime.utcnow() + timedelta(days=1))
    db_session.add(sub)
    await db_session.flush()
    
    issued_keys_info = []
    has_created_any = False
    
    for ib in active_tariff_inbounds:
        email = f"user_{db_user.telegram_id}_{uuid.uuid4().hex[:4]}"
        client_uuid = await xui_client.add_client(inbound_id=ib.inbound_id, email=email)
        
        if client_uuid:
            if ib.link_template:
                config_link = ib.link_template.format(uuid=client_uuid, email=email)
            else:
                target_inbound = await xui_client.get_inbound_info(ib.inbound_id)
                config_link = generate_xui_link(target_inbound, client_uuid, email)
                
            if config_link:
                vpn_key = VPNKey(
                    subscription_id=sub.id, protocol_category=ProtocolType.XUI,
                    protocol_name=ib.protocol_name.upper(), client_uuid=client_uuid,
                    inbound_id=ib.inbound_id, config_data=config_link
                )
                db_session.add(vpn_key)
                has_created_any = True
                issued_keys_info.append(f"🚀 <b>Ключ {ib.protocol_name.upper()} ({ib.remark}):</b>\n<code>{config_link}</code>")

    if has_created_any:
        db_user.free_trial_used_at = datetime.utcnow()
        await db_session.commit()
        
        success_msg = (
            f"✅ <b>Тестовый период успешно активирован!</b>\n"
            f"• Срок действия: 1 день (до {sub.expires_at.strftime('%d.%m.%Y %H:%M')})\n\n"
            f"🛒 <b>Ваш доступ к конфигурации:</b>\n\n" + "\n\n".join(issued_keys_info)
        )
        await callback.message.delete()
        await callback.message.answer(text=success_msg, reply_markup=make_fresh_menu_kb())
        
        res_key = await db_session.execute(select(VPNKey).where(VPNKey.subscription_id == sub.id))
        first_key = res_key.scalars().first()
        if first_key:
            qr_file = create_qr_code_file(first_key.config_data, filename="vpn_trial_qr.png")
            await callback.message.answer_photo(photo=qr_file, caption="📱 Сканируйте QR-код для импорта конфигурации:")
    else:
        await db_session.rollback()
        await callback.message.answer("❌ Произошла техническая ошибка при обращении к серверу 3x-ui. Попробуйте позже.")

@user_router.callback_query(F.data == "menu_tariffs")
async def cb_menu_tariffs(callback: CallbackQuery):
    """Вывод коммерческих тарифных планов"""
    await callback.answer()
    keyboard = [
        [InlineKeyboardButton(text="💎 PREMIUM (Скоростные ноды Reality gRPC)", callback_query_data="buy_premium")],
        [InlineKeyboardButton(text="🔙 Назад в главное меню", callback_query_data="menu_main")]
    ]
    tariffs_text = (
        f"🛒 <b>Доступные тарифные планы Overlord VPN</b>\n\n"
        f"• <b>Тариф PREMIUM:</b>\n"
        f"— Доступ ко всем производительным нодам в Финляндии.\n"
        f"— Архитектура gRPC + Reality (минимальный пинг, обход DPI).\n"
        f"— Без лимита по трафику и скорости.\n"
        f"— Приоритетная поддержка 24/7.\n\n"
        f"👉 Нажмите кнопку ниже для выбора периода подписки:"
    )
    await callback.message.edit_text(text=tariffs_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@user_router.callback_query(F.data == "buy_premium")
async def cb_select_period(callback: CallbackQuery):
    """Меню выбора длительности подписки PREMIUM"""
    await callback.answer()
    keyboard = [
        # Убедитесь, что числа передаются без лишних пробелов, а callback_query_data указан везде строго!
        [InlineKeyboardButton(text="📅 1 месяц — 3.00 USDT", callback_query_data="period_premium_30_3.0")],
        [InlineKeyboardButton(text="📅 3 месяца — 8.00 USDT", callback_query_data="period_premium_90_8.0")],
        [InlineKeyboardButton(text="📅 6 месяцев — 15.00 USDT", callback_query_data="period_premium_180_15.0")],
        [InlineKeyboardButton(text="🔙 Назад к тарифам", callback_query_data="menu_tariffs")]
    ]
    await callback.message.edit_text(
        text="📅 <b>Выберите период подписки PREMIUM:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@user_router.callback_query(F.data.startswith("period_premium_"))
async def cb_create_invoice_page(callback: CallbackQuery):
    """Генерация страницы симуляции оплаты (Тестовый шлюз)"""
    await callback.answer()
    parts = callback.data.split("_")
    days = int(parts[2])
    amount = float(parts[3])
    
    keyboard = [
        [InlineKeyboardButton(text="✅ Симулировать успешную оплату", callback_query_data=f"pay_success_{days}")],
        [InlineKeyboardButton(text="❌ Отменить операцию", callback_query_data="menu_main")]
    ]
    
    await callback.message.edit_text(
        text=f"💳 <b>Режим тестирования коммерческой подписки</b>\n\n"
             f"• Выбранный тариф: <code>PREMIUM</code>\n"
             f"• Срок действия: <code>{days} дней</code>\n"
             f"• Эквивалент стоимости: <code>{amount} USDT</code>\n\n"
             f"👉 Для проверки полного цикла работы базы данных и API панели нажмите кнопку симуляции платежа:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@user_router.callback_query(F.data.startswith("pay_success_"))
async def cb_process_fake_payment(callback: CallbackQuery, db_session: AsyncSession):
    """
    Симуляция успешного хука оплаты.
    Автоматически продлевает существующие ключи в 3x-ui или нарезает новые по шаблону.
    """
    await callback.answer()
    days = int(callback.data.split("_")[2])
    pay_user_id = callback.from_user.id
    
    # Ищем, есть ли у пользователя уже активная подписка PREMIUM
    res_sub = await db_session.execute(
        select(Subscription).where(
            Subscription.user_id == pay_user_id,
            Subscription.plan_type == SubscriptionType.PREMIUM,
            Subscription.expires_at > datetime.utcnow()
        )
    )
    active_sub = res_sub.scalar()
    
    if active_sub:
        active_sub.expires_at += timedelta(days=days)
        sub_id = active_sub.id
        is_extension = True
    else:
        active_sub = Subscription(
            user_id=pay_user_id,
            plan_type=SubscriptionType.PREMIUM,
            expires_at=datetime.utcnow() + timedelta(days=days)
        )
        db_session.add(active_sub)
        await db_session.flush()
        sub_id = active_sub.id
        is_extension = False
        
    # Вытаскиваем инбаунды, привязанные в админке к тарифу PREMIUM
    res_inbounds = await db_session.execute(
        select(TariffInbound).where(TariffInbound.plan_type == SubscriptionType.PREMIUM)
    )
    premium_inbounds = res_inbounds.scalars().all()
    
    if not premium_inbounds:
        await callback.message.answer(
            "❌ Ошибка: В админке пока не настроены инбаунды для PREMIUM тарифа.\n"
            "Деньги сохранены, обратитесь к администратору."
        )
        return

    issued_keys_text = []
    
    for ib in premium_inbounds:
        if is_extension:
            # Если это продление — находим старый ключ и включаем его в панели по API
            res_key = await db_session.execute(
                select(VPNKey).where(VPNKey.subscription_id == sub_id, VPNKey.inbound_id == ib.inbound_id)
            )
            old_key = res_key.scalar()
            if old_key:
                await xui_client.set_client_status(inbound_id=ib.inbound_id, client_uuid=old_key.client_uuid, enable=True)
                issued_keys_text.append(f"🚀 <b>Ключ {ib.protocol_name.upper()} ({ib.remark}) [Продлен]:</b>\n<code>{old_key.config_data}</code>")
                continue

        # Если это новая покупка — нарезаем чистый 32-значный hex-пароль
        email = f"user_{pay_user_id}_{uuid.uuid4().hex[:4]}"
        client_uuid = uuid.uuid4().hex
        
        # Добавляем клиента в панель по новому API MHSanaei 3.x
        created_uuid = await xui_client.add_client(inbound_id=ib.inbound_id, email=email)
        
        if created_uuid:
            # Задействуем пуленепробиваемые шаблоны админки
            if ib.link_template:
                config_link = ib.link_template.format(uuid=created_uuid, email=email)
            else:
                target_inbound = await xui_client.get_inbound_info(ib.inbound_id)
                config_link = generate_xui_link(target_inbound, created_uuid, email)
                
            if config_link:
                vpn_key = VPNKey(
                    subscription_id=sub_id,
                    protocol_category=ProtocolType.XUI,
                    protocol_name=ib.protocol_name.upper(),
                    client_uuid=created_uuid,
                    inbound_id=ib.inbound_id,
                    config_data=config_link
                )
                db_session.add(vpn_key)
                issued_keys_text.append(f"🚀 <b>Ключ {ib.protocol_name.upper()} ({ib.remark}):</b>\n<code>{config_link}</code>")

    await db_session.commit()
    await callback.message.delete()
    
    expires_str = active_sub.expires_at.strftime("%d.%m.%Y %H:%M")
    success_text = (
        f"👑 <b>PREMIUM подписка успешно активирована!</b>\n"
        f"• Срок действия продлен до: <code>{expires_str}</code>\n\n"
        f"🛒 <b>Ваш доступ к конфигурациям:</b>\n\n" + "\n\n".join(issued_keys_text)
    )
    await callback.message.answer(text=success_text, reply_markup=get_main_menu_keyboard())

@user_router.callback_query(F.data == "menu_profile")
async def cb_menu_profile(callback: CallbackQuery, db_session: AsyncSession):
    """Личный кабинет пользователя с выводом всех его ключей"""
    await callback.answer()
    tg_id = callback.from_user.id
    
    res_sub = await db_session.execute(
        select(Subscription).where(Subscription.user_id == tg_id, Subscription.expires_at > datetime.utcnow())
    )
    active_subs = res_sub.scalars().all()
    
    profile_text = f"👤 <b>Личный кабинет пользователя</b>\n\n• Ваш Telegram ID: <code>{tg_id}</code>\n"
    keyboard = [[InlineKeyboardButton(text="🔙 В главное меню", callback_query_data="menu_main")]]
    await callback.message.edit_text(text=profile_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

    
    if active_subs:
        profile_text += "\n🔑 <b>Ваши активные конфигурации подписок:</b>\n\n"
        for sub in active_subs:
            res_keys = await db_session.execute(select(VPNKey).where(VPNKey.subscription_id == sub.id))
            for k in res_keys.scalars().all():
                profile_text += f"▪️ <b>{k.protocol_name} ({sub.plan_type.value.upper()}) до {sub.expires_at.strftime('%d.%m.%Y')}:</b>\n<code>{k.config_data}</code>\n\n"
    else:
        profile_text += "\nℹ️ У вас пока нет активных платных или тестовых подписок."
        
    await callback.message.edit_text(text=profile_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
