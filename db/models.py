from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Boolean, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    max_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amo_contact_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    amo_deal_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_content: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_term: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    yclid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    start_edu: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notification_stage: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    lesson_results: Mapped[list["HpLessonResult"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class HpLessonResult(Base):
    __tablename__ = "lesson_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lesson_key: Mapped[str] = mapped_column(String(64))
    result: Mapped[str | None] = mapped_column(String(128), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compleat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="lesson_results")


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message: Mapped[str] = mapped_column(Text)
    source_filename: Mapped[str] = mapped_column(String(255))
    media_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    media_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    media_original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_telegram: Mapped[bool] = mapped_column(Boolean, default=True)
    send_max: Mapped[bool] = mapped_column(Boolean, default=False)

    buttons: Mapped[list["BroadcastButton"]] = relationship(
        back_populates="broadcast", cascade="all, delete-orphan", order_by="BroadcastButton.position"
    )
    recipients: Mapped[list["BroadcastRecipient"]] = relationship(
        back_populates="broadcast", cascade="all, delete-orphan"
    )
    deliveries: Mapped[list["BroadcastDelivery"]] = relationship(
        back_populates="broadcast", cascade="all, delete-orphan"
    )


class BroadcastButton(Base):
    __tablename__ = "broadcast_buttons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(64))
    action_key: Mapped[str] = mapped_column(String(32))

    broadcast: Mapped[Broadcast] = relationship(back_populates="buttons")


class BroadcastRecipient(Base):
    __tablename__ = "broadcast_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_telegram_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    max_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_max_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(255), default="")

    broadcast: Mapped[Broadcast] = relationship(back_populates="recipients")
    deliveries: Mapped[list["BroadcastDelivery"]] = relationship(
        back_populates="recipient", cascade="all, delete-orphan"
    )


class BroadcastDelivery(Base):
    __tablename__ = "broadcast_deliveries"
    __table_args__ = (
        Index("ix_broadcast_deliveries_broadcast_platform_status", "broadcast_id", "platform", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("broadcast_recipients.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    broadcast: Mapped[Broadcast] = relationship(back_populates="deliveries")
    recipient: Mapped[BroadcastRecipient] = relationship(back_populates="deliveries")
