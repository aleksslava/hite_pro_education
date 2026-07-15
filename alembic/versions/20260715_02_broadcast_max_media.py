"""add cached MAX media token to broadcasts

Revision ID: 20260715_02
Revises: 20260715_01
Create Date: 2026-07-15 00:00:01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260715_02"
down_revision = "20260715_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("broadcasts", sa.Column("max_media_token", sa.String(length=1024), nullable=True))
    op.add_column("broadcasts", sa.Column("max_media_type", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("broadcasts", "max_media_type")
    op.drop_column("broadcasts", "max_media_token")
