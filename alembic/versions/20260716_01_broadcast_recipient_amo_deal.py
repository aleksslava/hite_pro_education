"""add amo deal source to broadcast recipients

Revision ID: 20260716_01
Revises: 20260715_02
Create Date: 2026-07-16 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260716_01"
down_revision = "20260715_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("broadcast_recipients", sa.Column("amo_deal_id", sa.BigInteger(), nullable=True))
    op.add_column("broadcast_recipients", sa.Column("raw_amo_deal_id", sa.String(length=128), nullable=True))
    op.create_index("ix_users_amo_deal_id", "users", ["amo_deal_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_amo_deal_id", table_name="users")
    op.drop_column("broadcast_recipients", "raw_amo_deal_id")
    op.drop_column("broadcast_recipients", "amo_deal_id")
