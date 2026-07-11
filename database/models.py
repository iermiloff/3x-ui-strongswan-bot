import datetime
from enum import Enum
from typing import List, Optional
from sqlalchemy import BigInteger, ForeignKey, String, DateTime, Boolean, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class SubscriptionType(str, Enum):
    BASE = "base"         # Например, только XUI (любые протоколы)
    PREMIUM = "premium"   # Доступ и к XUI, и к StrongSwan (IKEv2)

class ProtocolType(str, Enum):
    XUI = "xui"           # Универсальный тип для всех ключей из 3x-ui
    IKEV2 = "ikev2"       # Для StrongSwan

class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    registered_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    
    # Отметка времени для проверки "Раз в месяц" (триал)
    last_free_trial: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    # Связи
    subscriptions: Mapped[List["Subscription"]] = relationship(back_populates="user", cascade="all, delete-orphan")

class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    
    plan_type: Mapped[SubscriptionType] = mapped_column(String(20), default=SubscriptionType.BASE)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    # Связи
    user: Mapped["User"] = relationship(back_populates="subscriptions")
    keys: Mapped[List["VPNKey"]] = relationship(back_populates="subscription", cascade="all, delete-orphan")

class VPNKey(Base):
    __tablename__ = "vpn_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    
    # Категория: xui или ikev2
    protocol_category: Mapped[ProtocolType] = mapped_column(String(20))
    
    # Конкретное название для вывода юзеру (например: "Trojan gRPC", "VLESS Reality", "IKEv2 iOS")
    protocol_name: Mapped[str] = mapped_column(String(50))
    
    # Идентификатор клиента внутри 3x-ui (обычно UUID или email) или логин в StrongSwan
    client_uuid: Mapped[str] = mapped_column(String(255), unique=True)
    
    # ID инбаунда в 3x-ui (чтобы знать, к какому порту/протоколу привязан ключ в панели)
    inbound_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    
    # Готовая ссылка подключения (vless://..., trojan://...) или данные для IKEv2
    config_data: Mapped[str] = mapped_column(String(2048))
    
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    # Связи
    subscription: Mapped["Subscription"] = relationship(back_populates="keys")

class TariffInbound(Base):
    __tablename__ = "tariff_inbounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_type: Mapped[SubscriptionType] = mapped_column(String(20)) # base или premium
    inbound_id: Mapped[int] = mapped_column(unique=True)            # ID инбаунда из 3x-ui
    protocol_name: Mapped[str] = mapped_column(String(50))         # VLESS, TROJAN и т.д.
    port: Mapped[int] = mapped_column()
    remark: Mapped[str] = mapped_column(String(255))               # Название из панели
    link_template = Column(Text, nullable=True) 
