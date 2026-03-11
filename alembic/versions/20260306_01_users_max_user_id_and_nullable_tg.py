"""users: add max_user_id and make tg_user_id nullable

Revision ID: 20260306_01
Revises:
Create Date: 2026-03-06 13:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260306_01"
down_revision = None
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "users", "max_user_id"):
        op.add_column("users", sa.Column("max_user_id", sa.BigInteger(), nullable=True))

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "users", "ix_users_max_user_id"):
        op.create_index("ix_users_max_user_id", "users", ["max_user_id"], unique=True)

    columns = {column["name"]: column for column in inspector.get_columns("users")}
    tg_column = columns.get("tg_user_id")
    if tg_column is not None and tg_column.get("nullable") is False:
        op.alter_column(
            "users",
            "tg_user_id",
            existing_type=sa.BigInteger(),
            nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "users", "ix_users_max_user_id"):
        op.drop_index("ix_users_max_user_id", table_name="users")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "users", "max_user_id"):
        op.drop_column("users", "max_user_id")

    null_tg_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE tg_user_id IS NULL")
    ).scalar_one()
    if null_tg_count:
        raise RuntimeError(
            "Cannot downgrade: users.tg_user_id contains NULL values."
        )

    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("users")}
    tg_column = columns.get("tg_user_id")
    if tg_column is not None and tg_column.get("nullable") is True:
        op.alter_column(
            "users",
            "tg_user_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
