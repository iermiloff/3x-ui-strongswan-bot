import logging
import json
import uuid
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.config import config
from bot.database.models import User, Subscription, VPNKey, ProtocolType, SubscriptionType, TariffInbound
from bot.services.xui import xui_client
from bot.services.link_generator import generate_xui_link, create_qr_code_file
from bot.services.crypto_pay import crypto_pay_client

logger = logging.getLogger(__name__)
user_router = Router()

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🎁 Бесплатный тест (1 день)", callback_query_data="menu_trial")],
        [InlineKeyboardButton(text="💎 Купить подписку", callback_query_data="menu_tariffs")],
        [InlineKeyboardButton(text="👤 Мой профиль / Ключи", callback_query_data="menu_profile")],
        [InlineKeyboardButton(text="📊 Статистика", callback_query_data="menu_stats")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@user_router.message(CommandStart())
async def cmd_start(message: Message, db_session: AsyncSession):
    tg_id = message.from_user.id
    res = await db_session.execute(select(User).where(User.telegram_id == tg_id))
    db_user = res.scalar_or_none()
    
    if not db_user:
        db_user = User(telegram_id=tg_id, username=message.from_user.username)
        db_session.add(db_user)
        await db_session.commit()
        
    welcome_text = (
        f"👋 <b>Приветствуем вас в Overlord VPN!</b>\n\n"
        f"Мы развернули стабильные ноды в Финляндии с маскировкой <b>Reality gRPC</b>, "
        f"которая полностью защищена от любых блокировок ТСПУ и глубокого анализа пакетов (DPI).\n\n"
        f"👉 Выберите нужное действие в меню ниже:"
    )
    await message.answer(text=welcome_text, reply_markup=get_main_menu_keyboard())

@user_router.callback_query(F.data == "menu_main")
async def cb_menu_main(callback: CallbackQuery):
    await callback.answer()
    welcome_text = "👉 Выберите нужное действие в меню ниже:"
    await callback.message.edit_text(text=welcome_text, reply_markup=get_main_menu_keyboard())

@user_router.callback_query(F.data == "menu_trial")
async def cb_menu_trial(callback: CallbackQuery, db_session: AsyncSession):
    await callback.answer()
    tg_id = callback.from_user.id
    res_user = await db_session.execute(select(User).where(User.telegram_id == tg_id))
    db_user = res_user.scalar_or_none()
    
    if db_user.free_trial_used_at:
        delta = datetime.utcnow() - db_user.free_trial_used_at
        if delta.days < 30:
            await callback.message.answer("❌ Вы уже брали тестовый период в этом месяце!\nПовторный тест будет доступен через 30 дней.")
            return

    res_inbounds = await db_session.execute(select(TariffInbound).where(TariffInbound.plan_type == SubscriptionType.BASE))
    active_tariff_inbounds = res_inbounds.scalars().all()
    
    if not active_tariff_inbounds:
        await callback.message.answer("❌ Ошибка: В админке пока не настроены порты для базового тарифа.")
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
        
        expires_str = sub.expires_at.strftime("%d.%m.%Y %H:%M")
        success_msg = (
            f"✅ <b>Тестовый период успешно активирован!</b>\n"
            f"• Срок действия: до <code>{expires_str}</code> (1 день)\n\n"
            f"🛒 <b>Ваш доступ к конфигурации:</b>\n\n" + "\n\n".join(issued_keys_info)
        )
        await callback.message.delete()
        await callback.message.answer(text=success_msg, reply_markup=get_main_menu_keyboard())
        
        res_key = await db_session.execute(select(VPNKey).where(VPNKey.subscription_id == sub.id))
        first_key = res_key.scalars().first()
        if first_key:
            qr_file = create_qr_code_file(first_key.config_data, filename="vpn_trial_qr.png")
            await callback.message.answer_photo(photo=qr_file, caption="📱 Сканируйте QR-код для импорта:")
    else:
        await db_session.rollback()
        await callback.message.answer("❌ Техническая ошибка 3x-ui. Попробуйте позже.")

@user_router.callback_query(F.data == "menu_tariffs")
async def cb_menu_tariffs(callback: CallbackQuery):
    await callback.answer()
    keyboard = [
        [InlineKeyboardButton(text="💎 PREMIUM (Все ноды Reality gRPC)", callback_query_data="buy_premium")],
        [InlineKeyboardButton(text="🔙 Назад", callback_query_data="menu_main")]
    ]
    await callback.message.edit_text(
        text="🛒 <b>Доступные тарифные планы:</b>\n\n"
             "• <b>PREMIUM-тариф</b> открывает доступ к высокоскоростным нодам с минимальным пингом. "
             "Маскировка Reality gRPC полностью обходит блокировки DPI.\n\n"
             "👉 Выберите вариант подписки:", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@user_router.callback_query(F.data == "buy_premium")
async def cb_select_period(callback: CallbackQuery):
    await callback.answer()
    keyboard = [
        [InlineKeyboardButton(text="1 месяц — 3.00 USDT", callback_query_data="period_premium_30_3")],
        [InlineKeyboardButton(text="3 месяца — 8.00 USDT", callback_query_data="period_premium_90_8")],
        [InlineKeyboardButton(text="🔙 Назад", callback_query_data="menu_tariffs")]
    ]
    await callback.message.edit_text(text="📅 <b>Выберите период действия подписки:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@user_router.callback_query(F.data.startswith("period_premium_"))
async def cb_create_invoice(callback: CallbackQuery, db_session: AsyncSession):
    await callback.answer()
    parts = callback.data.split("_")
    days = int(parts[2])
    amount = float(parts[3])
    pay_user_id = callback.from_user.id
    
    # Генерируем счет в Crypto Pay
    invoice = await crypto_pay_client.create_invoice(amount=amount, asset="USDT", description=f"Overlord VPN Premium ({days} дней)")
    if not invoice:
        await callback.message.answer("❌ Ошибка платежного шлюза. Попробуйте позже.")
        return
        
    pay_url = invoice.get("bot_invoice_url")
    invoice_id = invoice.get("invoice_id")
    
    keyboard = [
        [InlineKeyboardButton(text="💵 Оплатить через CryptoBot", url=pay_url)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_query_data=f"check_{invoice_id}_{days}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_query_data="menu_main")]
    ]
    await callback.message.edit_text(
        text=f"💳 <b>Счёт на оплату сформирован!</b>\n\n"
             f"• Тариф: <code>PREMIUM</code>\n"
             f"• Срок: <code>{days} дней</code>\n"
             f"• К оплате: <code>{amount} USDT</code>\n\n"
             f"👉 Нажмите кнопку ниже для перехода к оплате. После транзакции вернитесь и нажмите кнопку проверки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@user_router.callback_query(F.data.startswith("check_"))
async def cb_check_invoice(callback: CallbackQuery, db_session: AsyncSession):
    parts = callback.data.split("_")
    invoice_id = int(parts[1])
    days = int(parts[2])
    pay_user_id = callback.from_user.id
    
    is_paid = await crypto_pay_client.check_invoice_paid(invoice_id)
    if not is_paid:
        await callback.answer("❌ Оплата пока не зафиксирована сетью. Попробуйте через пару секунд!", show_alert=True)
        return
        
    await callback.answer("🎉 Оплата успешно подтверждена!", show_alert=True)
    
    # Оформляем или продлеваем подписку в СУБД
    res_sub = await db_session.execute(
        select(Subscription).where(
            Subscription.user_id == pay_user_id, 
            Subscription.plan_type == SubscriptionType.PREMIUM,
            Subscription.expires_at > datetime.utcnow()
        )
    )
    active_sub = res_sub.scalar_or_none()
    
    if active_sub:
        active_sub.expires_at += timedelta(days=days)
        sub_id = active_sub.id
        is_extension = True
    else:
        active_sub = Subscription(user_id=pay_user_id, plan_type=SubscriptionType.PREMIUM, expires_at=datetime.utcnow() + timedelta(days=days))
        db_session.add(active_sub)
        await db_session.flush()
        sub_id = active_sub.id
        is_extension = False
        
    # Вытаскиваем инбаунды тарифа PREMIUM
    res_inbounds = await db_session.execute(select(TariffInbound).where(TariffInbound.plan_type == SubscriptionType.PREMIUM))
    premium_inbounds = res_inbounds.scalars().all()
    
    issued_keys_text = []
    
    for ib in premium_inbounds:
        if is_extension:
            # Если это продление, находим старый ключ и включаем его в 3x-ui
            res_key = await db_session.execute(select(VPNKey).where(VPNKey.subscription_id == sub_id, VPNKey.inbound_id == ib.inbound_id))
            old_key = res_key.scalar_or_none()
            if old_key:
                await xui_client.set_client_status(inbound_id=ib.inbound_id, client_uuid=old_key.client_uuid, enable=True)
                issued_keys_text.append(f"🚀 <b>Ключ {ib.protocol_name.upper()} ({ib.remark}) [Продлен]:</b>\n<code>{old_key.config_data}</code>")
                continue

        # Выдаем новый ключ по сохраненному шаблону админки
        email = f"user_{pay_user_id}_{uuid.uuid4().hex[:4]}"
        client_uuid = await xui_client.add_client(inbound_id=ib.inbound_id, email=email)
        
        if client_uuid:
            if ib.link_template:
                config_link = ib.link_template.format(uuid=client_uuid, email=email)
            else:
                target_inbound = await xui_client.get_inbound_info(ib.inbound_id)
                config_link = generate_xui_link(target_inbound, client_uuid, email)
                
            if config_link:
                vpn_key = VPNKey(
                    subscription_id=sub_id, protocol_category=ProtocolType.XUI,
                    protocol_name=ib.protocol_name.upper(), client_uuid=client_uuid,
                    inbound_id=ib.inbound_id, config_data=config_link
                )
                db_session.add(vpn_key)
                issued_keys_text.append(f"🚀 <b>Ключ {ib.protocol_name.upper()} ({ib.remark}):</b>\n<code>{config_link}</code>")

    await db_session.commit()
    expires_str = active_sub.expires_at.strftime("%d.%m.%Y %H:%M")
    
    success_text = (
        f"👑 <b>PREMIUM подписка успешно активирована!</b>\n"
        f"• Действует до: <code>{expires_str}</code>\n\n"
        f"🛒 <b>Ваши доступы к конфигурациям:</b>\n\n" + "\n\n".join(issued_keys_text)
    )
    await callback.message.delete()
    await callback.message.answer(text=success_text, reply_markup=get_main_menu_keyboard())

@user_router.callback_query(F.data == "menu_profile")
async def cb_menu_profile(callback: CallbackQuery, db_session: AsyncSession):
    await callback.answer()
    tg_id = callback.from_user.id
    
    res_sub = await db_session.execute(select(Subscription).where(Subscription.user_id == tg_id, Subscription.expires_at > datetime.utcnow()))
    active_subs = res_sub.scalars().all()
    
    profile_text = f"👤 <b>Личный кабинет пользователя</b>\n\n• Ваш ID: <code>{tg_id}</code>\n"
    keyboard = [[InlineKeyboardButton(text="🔙 В главное меню", callback_query_data="menu_main")]]
    
    if active_subs:
        profile_text += "\n🔑 <b>Ваши активные конфигурации:</b>\n\n"
        for sub in active_subs:
            res_keys = await db_session.execute(select(VPNKey).where(VPNKey.subscription_id == sub.id))
            keys = res_keys.scalars().all()
            for k in keys:
                profile_text += f"▪️ <b>{k.protocol_name} ({sub.plan_type.value.upper()}) до {sub.expires_at.strftime('%d.%m.%Y')}:</b>\n<code>{k.config_data}</code>\n\n"
    else:
        profile_text += "\nℹ️ У вас пока нет активных платных или тестовых подписок."
        
    await callback.message.edit_text(text=profile_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

