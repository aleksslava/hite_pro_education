"""add web-admin broadcasts

Revision ID: 20260715_01
Revises: 20260410_01
Create Date: 2026-07-15 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260715_01"
down_revision = "20260410_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("media_path", sa.String(length=1024), nullable=True),
        sa.Column("media_kind", sa.String(length=16), nullable=True),
        sa.Column("media_original_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("send_telegram", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("send_max", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_broadcasts_status", "broadcasts", ["status"])
    op.create_index("ix_broadcasts_scheduled_at", "broadcasts", ["scheduled_at"])
    op.create_table(
        "broadcast_buttons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broadcast_id", sa.Integer(), sa.ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=64), nullable=False),
        sa.Column("action_key", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_broadcast_buttons_broadcast_id", "broadcast_buttons", ["broadcast_id"])
    op.create_table(
        "broadcast_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broadcast_id", sa.Integer(), sa.ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_telegram_id", sa.String(length=128), nullable=True),
        sa.Column("max_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_max_id", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
    )
    op.create_index("ix_broadcast_recipients_broadcast_id", "broadcast_recipients", ["broadcast_id"])
    op.create_table(
        "broadcast_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broadcast_id", sa.Integer(), sa.ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("broadcast_recipients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_target_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_broadcast_deliveries_broadcast_id", "broadcast_deliveries", ["broadcast_id"])
    op.create_index("ix_broadcast_deliveries_recipient_id", "broadcast_deliveries", ["recipient_id"])
    op.create_index("ix_broadcast_deliveries_status", "broadcast_deliveries", ["status"])
    op.create_index("ix_broadcast_deliveries_broadcast_platform_status", "broadcast_deliveries", ["broadcast_id", "platform", "status"])


def downgrade() -> None:
    op.drop_table("broadcast_deliveries")
    op.drop_table("broadcast_recipients")
    op.drop_table("broadcast_buttons")
    op.drop_table("broadcasts")
