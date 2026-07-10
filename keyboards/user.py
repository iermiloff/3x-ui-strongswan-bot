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
