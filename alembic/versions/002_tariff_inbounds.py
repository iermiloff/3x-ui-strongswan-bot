"""add tariff inbounds

Revision ID: 002
Revises: 001
Create Date: 2026-07-11 12:00:00.000000

"""
from typing import Sequence, Optional
from alembic import op
import sqlalchemy as sa

revision: str = '002'
down_revision: Optional[str] = '001'

def upgrade() -> None:
    op.create_table(
        'tariff_inbounds',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('plan_type', sa.String(length=20), nullable=False),
        sa.Column('inbound_id', sa.Integer(), nullable=False),
        sa.Column('protocol_name', sa.String(length=50), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('remark', sa.String(length=255), nullable=False),
        sa.Column('link_template', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('inbound_id')
    )

def downgrade() -> None:
    op.drop_table('tariff_inbounds')
