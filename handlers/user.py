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

from sqlalchemy.orm import selectinload
from sqlalchemy import select
from bot.keyboards.user import (
    get_profile_keyboard, 
    get_instructions_main_keyboard, 
    get_platform_keyboard
)

# --- ЛОГИКА ПРОФИЛЯ И ВЫГРУЗКИ КЛЮЧЕЙ ---

@user_router.callback_query(F.data == "menu_profile")
async def cb_menu_profile(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    """Вывод личного кабинета пользователя со всеми его активными ключами"""
    now = datetime.datetime.utcnow()
    
    # Загружаем пользователя вместе с его активными подписками и ключами (используем selectinload для асинхронности)
    stmt = (
        select(User)
        .where(User.telegram_id == db_user.telegram_id)
        .options(
            selectinload(User.subscriptions).selectinload(Subscription.keys)
        )
    )
    result = await db_session.execute(stmt)
    user_with_relations = result.scalar_one()

    # Фильтруем только действующие подписки
    active_subs = [s for s in user_with_relations.subscriptions if s.is_active and s.expires_at > now]
    
    profile_text = f"👤 <b>Личный кабинет</b>\n\n• Твой Telegram ID: <code>{db_user.telegram_id}</code>\n"
    
    if not active_subs:
        profile_text += "• Статус подписки: ❌ <b>Не активна</b>\n\nУ тебя пока нет активных подключений. Ты можешь купить доступ или взять бесплатный тест в главном меню."
    else:
        profile_text += "• Статус подписки: ✅ <b>Активна</b>\n\n🔑 <b>Твои доступные ключи:</b>\n"
        
        for sub in active_subs:
            # Отображаем тип тарифа и срок действия
            tariff_name = "💎 PREMIUM (IKEv2 + XUI)" if sub.plan_type == SubscriptionType.PREMIUM else "🚀 БАЗОВЫЙ (Только XUI)"
            expires_str = sub.expires_at.strftime("%d.%m.%Y %H:%M")
            profile_text += f"\nТариф: <b>{tariff_name}</b> (До: <code>{expires_str}</code>)\n"
            
            if not sub.keys:
                profile_text += "<i>Ключи еще не сгенерированы. Они появятся здесь автоматически после оплаты.</i>\n"
            else:
                for key in sub.keys:
                    if key.protocol_category == ProtocolType.XUI:
                        profile_text += f"├ <code>{key.config_data}</code>\n"
                    elif key.protocol_category == ProtocolType.IKEV2:
                        # Для IKEv2 разделяем логин и пароль для удобства копирования
                        try:
                            l, p = key.config_data.split(":", 1)
                            profile_text += f"├ <b>IKEv2</b> Сервер: <code>{config.SSH_HOST}</code>\n├ Логин: <code>{l}</code>\n├ Пароль: <code>{p}</code>\n"
                        except ValueError:
                            profile_text += f"├ <b>IKEv2:</b> <code>{key.config_data}</code>\n"
                            
        profile_text += "\n💡 <i>Нажми на код ключа или параметры, чтобы мгновенно скопировать их.</i>"

    await callback.message.edit_text(text=profile_text, reply_markup=get_profile_keyboard())

@user_router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery, db_user: User):
    """Возврат в главное меню"""
    await callback.message.delete()
    username_str = f", {db_user.username}" if db_user.username else ""
    welcome_text = (
        f"👋 Приветствуем{username_str} в нашем VPN-сервисе!\n\n"
        f"⚙️ Выберите интересующий раздел в меню ниже:"
    )
    await callback.message.answer(text=welcome_text, reply_markup=get_main_menu_keyboard())

# --- ДЕРЕВО МЕНЮ ИНСТРУКЦИЙ ---

@user_router.callback_query(F.data == "instructions_main")
async def cb_instructions_main(callback: CallbackQuery):
    """Главный экран выбора инструкций"""
    text = "📚 <b>Инструкции по настройке VPN</b>\n\nВыберите тип вашего подключения, чтобы получить пошаговое руководство по установке:"
    await callback.message.edit_text(text=text, reply_markup=get_instructions_main_keyboard())

@user_router.callback_query(F.data.in_(["instructions_xui", "instructions_ikev2"]))
async def cb_instructions_protocol(callback: CallbackQuery):
    """Выбор платформы для конкретного протокола"""
    protocol = "xui" if callback.data == "instructions_xui" else "ikev2"
    p_name = "3x-ui (Xray/Trojan/VLESS)" if protocol == "xui" else "Premium (IKEv2)"
    
    text = f"📱 <b>Инструкции для {p_name}</b>\n\nВыберите операционную систему вашего устройства:"
    await callback.message.edit_text(text=text, reply_markup=get_platform_keyboard(protocol))

@user_router.callback_query(F.data.startswith("inst_"))
async def cb_show_concrete_instruction(callback: CallbackQuery):
    """Вывод финального текста инструкции на основе выбранного протокола и ОС"""
    parts = callback.data.split("_") # Формат: inst_xui_ios или inst_ikev2_android
    protocol = parts[1]
    os_type = parts[2]
    
    # Словарь текстов инструкций (в будущем можно вынести в базу или JSON)
    instructions = {
        "xui": {
            "ios": "🍏 <b>Настройка XUI на iPhone (VLESS/Trojan)</b>\n\n1. Скачайте приложение <b>v2rayTUN</b> или <b>FoXray</b> из App Store.\n2. Скопируйте ключ из профиля бота (начинается на vless:// или trojan://).\n3. Откройте приложение, нажмите значок '+' и выберите 'Import from Clipboard'.\n4. Нажмите кнопку подключения (Power) и разрешите добавление VPN-конфигурации.",
            "android": "🤖 <b>Настройка XUI на Android (VLESS/Trojan)</b>\n\n1. Скачайте приложение <b>v2rayNG</b> из Google Play.\n2. Скопируйте ключ из бота.\n3. Откройте приложение, нажмите '+' вверху и выберите 'Импортировать профиль из буфера обмена'.\n4. Нажмите на круглую кнопку подключения в правом нижнем углу.",
            "macos": "💻 <b>Настройка XUI на macOS</b>\n\n1. Скачайте приложение <b>V2rayU</b> или <b>FoXray</b>.\n2. Скопируйте ключ подключения.\n3. Импортируйте его через буфер обмена в программу.\n4. Переключите режим на Global или Rule и активируйте соединение.",
            "windows": "🪟 <b>Настройка XUI на Windows</b>\n\n1. Скачайте программу <b>v2rayN</b> (с GitHub).\n2. Скопируйте ваш ключ.\n3. В программе нажмите 'Servers' -> 'Import bulk URL from clipboard'.\n4. Нажмите правой кнопкой мыши по иконке программы в трее, выберите 'System proxy' -> 'Set system proxy'."
        },
        "ikev2": {
            "ios": "🍏 <b>Настройка Premium IKEv2 на iPhone (Без программ!)</b>\n\n1. Откройте <b>Настройки</b> -> <b>Основные</b> -> <b>VPN и управление устройством</b> -> <b>VPN</b>.\n2. Нажмите <b>Добавить конфигурацию VPN</b>.\n3. Выберите тип: <b>IKEv2</b>.\n4. Заполните поля:\n• Описание: Любое имя (например, MyVPN)\n• Сервер: Адрес сервера из профиля бота\n• Удаленный ID: Тот же адрес сервера\n5. В блоке Аутентификация выберите <b>Имя пользователя</b>:\n• Логин и Пароль возьмите из профиля бота.\n6. Готово! Включайте тумблер.",
            "android": "🤖 <b>Настройка Premium IKEv2 на Android</b>\n\n1. Скачайте официальное приложение <b>strongSwan VPN Client</b> из Google Play.\n2. Нажмите <b>Add VPN profile</b>.\n3. В поле Server введите адрес сервера из бота.\n4. VPN Type выберите: <b>IKEv2 EAP (Username/Password)</b>.\n5. Введите ваши Логин и Пароль из профиля бота.\n6. Сохраните профиль и нажмите для подключения.",
            "macos": "💻 <b>Настройка Premium IKEv2 на macOS (Нативно)</b>\n\n1. Откройте Системные настройки -> Сеть.\n2. Нажмите значок '+' (или 'Добавить интерфейс'), выберите Интерфейс: <b>VPN</b>, Тип VPN: <b>IKEv2</b>.\n3. Введите адрес сервера в поля 'Адрес сервера' и 'Удаленный ID'.\n4. Нажмите 'Настройки аутентификации', выберите 'Имя пользователя/пароль' и скопируйте данные из бота.\n5. Нажмите 'Подключить'.",
            "windows": "🪟 <b>Настройка Premium IKEv2 на Windows</b>\n\n1. Откройте Параметры -> Сеть и Интернет -> VPN -> Добавить VPN.\n2. Поставщик VPN: Windows (встроенное).\n3. Имя подключения: Любое.\n4. Имя или адрес сервера: Скопируйте адрес из бота.\n5. Тип VPN: <b>IKEv2</b>.\n6. Тип данных для входа: Имя пользователя и пароль.\n7. Сохраните и нажмите 'Подключиться'."
        }
    }
    
    text = instructions[protocol][os_type]
    
    # Для удобства юзера возвращаем его на экран выбора платформ этого же протокола
    await callback.message.edit_text(text=text, reply_markup=get_platform_keyboard(protocol))

def get_tariffs_keyboard() -> InlineKeyboardMarkup:
    """Выбор типа подписки"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 БАЗОВЫЙ (Только 3x-ui / Xray)", callback_data="buy_plan_base")
        ],
        [
            InlineKeyboardButton(text="💎 PREMIUM (3x-ui + IKEv2 для iOS/Mac)", callback_data="buy_plan_premium")
        ],
        [
            InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")
        ]
    ])
    return keyboard

def get_periods_keyboard(plan_type: str) -> InlineKeyboardMarkup:
    """Выбор длительности подписки"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗓 1 Месяц", callback_data=f"buy_time_{plan_type}_30"),
            InlineKeyboardButton(text="🗓 3 Месяца (-10%)", callback_data=f"buy_time_{plan_type}_90")
        ],
        [
            InlineKeyboardButton(text="🗓 6 Месяцев (-20%)", callback_data=f"buy_time_{plan_type}_180")
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад к тарифам", callback_data="menu_buy")
        ]
    ])
    return keyboard

def get_assets_keyboard(plan_type: str, days: str) -> InlineKeyboardMarkup:
    """Выбор криптовалюты для оплаты"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 USDT (Tether)", callback_data=f"pay_{plan_type}_{days}_USDT"),
            InlineKeyboardButton(text="💎 TON (Toncoin)", callback_data=f"pay_{plan_type}_{days}_TON")
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад к выбору срока", callback_data=f"buy_plan_{plan_type}")
        ]
    ])
    return keyboard

from bot.keyboards.user import get_tariffs_keyboard, get_periods_keyboard, get_assets_keyboard
from bot.services.cryptobot import cryptobot_client

# Фиксированные цены в USD
PRICES = {
    "base": {30: 3.0, 90: 8.0, 180: 14.0},     # Базовый тариф (скидки на 3 и 6 месяцев)
    "premium": {30: 5.0, 90: 13.5, 180: 24.0}  # Премиум тариф
}

@user_router.callback_query(F.data == "menu_buy")
async def cb_menu_buy(callback: CallbackQuery):
    """Экран выбора тарифа"""
    text = (
        "💎 <b>Покупка подписки VPN</b>\n\n"
        "Выберите желаемый уровень доступа:\n\n"
        "🚀 <b>БАЗОВЫЙ (3x-ui):</b>\n"
        "• Доступ к быстрым обходам блокировок (VLESS/Trojan)\n"
        "• Работает через сторонние приложения\n"
        "• От 3$ в месяц\n\n"
        "💎 <b>PREMIUM (3x-ui + IKEv2):</b>\n"
        "• Всё, что есть в базовом тарифе\n"
        "• + Нативный быстрый протокол <b>IKEv2 StrongSwan</b>\n"
        "• Идеально для iOS/macOS (настройка прямо в системе за 1 минуту без стороннего софта!)\n"
        "• От 5$ в месяц"
    )
    await callback.message.edit_text(text=text, reply_markup=get_tariffs_keyboard())

@user_router.callback_query(F.data.startswith("buy_plan_"))
async def cb_buy_plan(callback: CallbackQuery):
    """Экран выбора периода подписки"""
    plan_type = callback.data.split("_")[2] # base или premium
    text = "🗓 <b>Выберите срок действия подписки:</b>\n\nЧем длиннее период, тем больше скидка!"
    await callback.message.edit_text(text=text, reply_markup=get_periods_keyboard(plan_type))

@user_router.callback_query(F.data.startswith("buy_time_"))
async def cb_buy_time(callback: CallbackQuery):
    """Экран выбора криптовалюты"""
    parts = callback.data.split("_")
    plan_type = parts[2]
    days = int(parts[3])
    
    price = PRICES[plan_type][days]
    text = f"💳 <b>Стоимость подписки: {price}$</b>\n\nВыберите криптовалюту, в которой хотите произвести оплату через CryptoBot:"
    await callback.message.edit_text(text=text, reply_markup=get_assets_keyboard(plan_type, str(days)))

@user_router.callback_query(F.data.startswith("pay_"))
async def cb_generate_invoice(callback: CallbackQuery, db_user: User):
    """Генерация счета в CryptoBot"""
    parts = callback.data.split("_")
    plan_type = parts[1]
    days = int(parts[2])
    asset = parts[3]
    
    price = PRICES[plan_type][days]
    
    await callback.message.edit_text("⏳ <i>Формирую счет на оплату, пожалуйста, подождите...</i>")
    
    # В payload зашиваем ключевую информацию для распознавания платежа: user_id, тип тарифа и дни
    payload = f"{db_user.telegram_id}:{plan_type}:{days}"
    description = f"Оплата VPN: тариф {plan_type.upper()} на {days} дней"
    
    # Вызываем наш ранее написанный клиент CryptoBot
    invoice = await cryptobot_client.create_invoice(
        amount=price,
        asset=asset,
        description=description,
        payload=payload
    )
    
    if invoice and invoice.get("bot_invoice_url"):
        invoice_url = invoice["bot_invoice_url"]
        invoice_id = invoice["invoice_id"]
        
        # Создаем интерактивную кнопку для перехода к оплате
        pay_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="💸 Оплатить счет", url=invoice_url)
            ],
            [
                # Кнопка ручной проверки (на случай, если юзер оплатил и вернулся)
                InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_invoice_{invoice_id}")
            ],
            [
                InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu_buy")
            ]
        ])
        
        text = (
            f"🧾 <b>Счет успешно выставлен!</b>\n\n"
            f"• <b>Тариф:</b> {plan_type.upper()}\n"
            f"• <b>Срок:</b> {days} дней\n"
            f"• <b>К оплате:</b> <code>{invoice['amount']}</code> {asset}\n\n"
            f"Нажмите кнопку ниже, чтобы перейти в @CryptoBot и совершить платеж. "
            f"После успешной транзакции бот мгновенно активирует вашу подписку."
        )
        await callback.message.edit_text(text=text, reply_markup=pay_keyboard)
    else:
        await callback.message.edit_text(
            text="❌ Не удалось связаться с платежной системой CryptoBot. Пожалуйста, попробуйте позже.",
            reply_markup=get_tariffs_keyboard()
        )

