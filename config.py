from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field
from typing import List, Optional

class Settings(BaseSettings):
    # Флаги доступности протоколов
    ENABLE_XUI: bool = True
    ENABLE_STRONGSWAN: bool = True

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

    # 3x-ui (Опционально, если ENABLE_XUI=True)
    XUI_URL: Optional[str] = None
    XUI_USER: Optional[str] = None
    XUI_PASSWORD: Optional[SecretStr] = None

    # StrongSwan (Опционально, если ENABLE_STRONGSWAN=True)
    SSH_HOST: Optional[str] = None
    SSH_PORT: Optional[int] = 22
    SSH_USER: Optional[str] = None
    SSH_KEY_PATH: Optional[str] = None

    # CryptoBot
    CRYPTO_BOT_TOKEN: SecretStr
    IS_NET_TEST: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

config = Settings()
