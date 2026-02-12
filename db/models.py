from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
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
