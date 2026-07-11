"""initial

Revision ID: 001
Revises: 
Create Date: 2026-07-10 12:00:00.000000

"""
from typing import Sequence, Optional
from alembic import op
import sqlalchemy as sa

# ID миграции
revision: str = '001'
down_revision: Optional[str] = None
branch_labels: Optional[Sequence[str]] = None
depends_on: Optional[Sequence[str]] = None

def upgrade() -> None:
    # 1. Создаем таблицу users
    op.create_table(
        'users',
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(length=32), nullable=True),
        sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('registered_at', sa.DateTime(), nullable=False),
        sa.Column('last_free_trial', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('telegram_id')
    )
    
    # 2. Создаем таблицу subscriptions
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('plan_type', sa.String(length=20), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # 3. Создаем таблицу vpn_keys
    op.create_table(
        'vpn_keys',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('protocol_category', sa.String(length=20), nullable=False),
        sa.Column('protocol_name', sa.String(length=50), nullable=False),
        sa.Column('client_uuid', sa.String(length=255), nullable=False),
        sa.Column('inbound_id', sa.Integer(), nullable=True),
        sa.Column('config_data', sa.String(length=2048), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade() -> None:
    op.drop_table('vpn_keys')
    op.drop_table('subscriptions')
    op.drop_table('users')
