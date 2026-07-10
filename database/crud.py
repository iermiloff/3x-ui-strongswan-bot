import datetime
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.database.models import User, Subscription, SubscriptionType, VPNKey

# --- РАБОТА С ПОЛЬЗОВАТЕЛЯМИ ---

async def get_or_create_user(
    session: AsyncSession, 
    telegram_id: int, 
    username: Optional[str] = None
) -> User:
    """Получает пользователя из БД или создает нового, если его нет"""
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.flush()  # Фиксируем изменения в сессии, чтобы объект получил дефолтные значения
    elif user.username != username:
        user.username = username  # Обновляем username, если он изменился в Telegram
        
    return user

async def check_free_trial_availability(session: AsyncSession, telegram_id: int) -> bool:
    """Проверяет, может ли пользователь взять бесплатный период (раз в 30 дней)"""
    result = await session.execute(select(User.last_free_trial).where(User.telegram_id == telegram_id))
    last_free_trial = result.scalar()
    
    if last_free_trial is None:
        return True
        
    # Проверяем, прошло ли 30 дней с момента последнего триала
    now = datetime.datetime.utcnow()
    return (now - last_free_trial).days >= 30

async def update_free_trial_timestamp(session: AsyncSession, telegram_id: int):
    """Обновляет временную метку взятия триала на текущее время"""
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user:
        user.last_free_trial = datetime.datetime.utcnow()

# --- РАБОТА С ПОДПИСКАМИ ---

async def create_subscription(
    session: AsyncSession, 
    user_id: int, 
    plan_type: SubscriptionType, 
    duration_days: int
) -> Subscription:
    """Создает новую подписку для пользователя или продлевает текущую активную"""
    now = datetime.datetime.utcnow()
    
    # Ищем, есть ли уже активная подписка такого же типа
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(Subscription.plan_type == plan_type)
        .where(Subscription.is_active == True)
        .where(Subscription.expires_at > now)
    )
    active_sub = result.scalar_one_or_none()
    
    if active_sub:
        # Продлеваем существующую подписку
        active_sub.expires_at += datetime.timedelta(days=duration_days)
        return active_sub
    else:
        # Создаем новую подписку с нуля
        expires_at = now + datetime.timedelta(days=duration_days)
        new_sub = Subscription(user_id=user_id, plan_type=plan_type, expires_at=expires_at)
        session.add(new_sub)
        await session.flush()
        return new_sub

async def get_active_user_subscriptions(session: AsyncSession, user_id: int) -> List[Subscription]:
    """Получает все активные подписки пользователя"""
    now = datetime.datetime.utcnow()
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(Subscription.is_active == True)
        .where(Subscription.expires_at > now)
    )
    return list(result.scalars().all())

from sqlalchemy import func

async def get_total_users_count(session: AsyncSession) -> int:
    """Возвращает общее количество зарегистрированных пользователей"""
    result = await session.execute(select(func.count(User.telegram_id)))
    return result.scalar() or 0

async def get_active_subscriptions_count(session: AsyncSession) -> int:
    """Возвращает количество текущих активных подписок"""
    now = datetime.datetime.utcnow()
    result = await session.execute(
        select(func.count(Subscription.id))
        .where(Subscription.is_active == True)
        .where(Subscription.expires_at > now)
    )
    return result.scalar() or 0
