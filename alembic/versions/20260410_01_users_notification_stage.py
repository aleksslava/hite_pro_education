"""users: add notification_stage

Revision ID: 20260410_01
Revises: 20260306_01
Create Date: 2026-04-10 15:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260410_01"
down_revision = "20260306_01"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "users", "notification_stage"):
        op.add_column("users", sa.Column("notification_stage", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "users", "notification_stage"):
        op.drop_column("users", "notification_stage")
