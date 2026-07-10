from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Генерирует инлайн-клавиатуру главного меню"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Мой профиль / Ключи", callback_data="menu_profile")
        ],
        [
            InlineKeyboardButton(text="💎 Купить подписку", callback_data="menu_buy"),
            InlineKeyboardButton(text="🎁 Бесплатный тест (1 день)", callback_data="menu_trial")
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats"),
            InlineKeyboardButton(text="❓ Поддержка", callback_data="menu_support")
        ]
    ])
    return keyboard

def get_profile_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура внутри личного кабинета"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📚 Инструкции по настройке", callback_data="instructions_main")
        ],
        [
            InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")
        ]
    ])
    return keyboard

def get_instructions_main_keyboard() -> InlineKeyboardMarkup:
    """Выбор протокола для инструкций"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Инструкции для 3x-ui (Xray/Trojan)", callback_data="instructions_xui")
        ],
        [
            InlineKeyboardButton(text="🔐 Инструкции для Premium (IKEv2)", callback_data="instructions_ikev2")
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад в профиль", callback_data="menu_profile")
        ]
    ])
    return keyboard

def get_platform_keyboard(protocol_type: str) -> InlineKeyboardMarkup:
    """Выбор операционной системы для конкретного протокола"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🍏 iOS (iPhone)", callback_data=f"inst_{protocol_type}_ios"),
            InlineKeyboardButton(text="🤖 Android", callback_data=f"inst_{protocol_type}_android")
        ],
        [
            InlineKeyboardButton(text="💻 macOS", callback_data=f"inst_{protocol_type}_macos"),
            InlineKeyboardButton(text="🪟 Windows", callback_data=f"inst_{protocol_type}_windows")
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад к протоколам", callback_data="instructions_main")
        ]
    ])
    return keyboard
