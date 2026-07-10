from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr
from typing import List

class Settings(BaseSettings):
    # Telegram
    BOT_TOKEN: SecretStr
    ADMIN_IDS: List[int]
    REQUIRED_CHANNEL_ID: int

    # Database
    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASSWORD: SecretStr
    DB_NAME: str

    # 3x-ui
    XUI_URL: str
    XUI_USER: str
    XUI_PASSWORD: SecretStr

    # CryptoBot
    CRYPTO_BOT_TOKEN: SecretStr
    IS_NET_TEST: bool = True

    # Автоматическое чтение из .env файла
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

# Инициализируем объект конфига для импорта в другие модули
config = Settings()
