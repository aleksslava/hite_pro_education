from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import HpLessonResult, User


async def get_notification_candidates(session: AsyncSession) -> list[User]:
    exam_completed_exists = (
        select(HpLessonResult.id)
        .where(
            HpLessonResult.user_id == User.id,
            HpLessonResult.lesson_key == "exam",
            HpLessonResult.compleat.is_(True),
        )
        .exists()
    )
    result = await session.execute(
        select(User)
        .where(User.tg_user_id.is_not(None))
        .where(~exam_completed_exists)
        .order_by(User.id)
    )
    return result.scalars().all()


async def get_last_lesson_result(
    session: AsyncSession,
    user_id: int,
) -> HpLessonResult | None:
    result = await session.execute(
        select(HpLessonResult)
        .where(HpLessonResult.user_id == user_id)
        .order_by(HpLessonResult.started_at.desc().nullslast(), HpLessonResult.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_notification_stage(
    session: AsyncSession,
    user_id: int,
    stage: int | None,
) -> None:
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(notification_stage=stage)
    )
