from __future__ import annotations

from datetime import datetime, timedelta


def resolve_activity_at(
    user_created_at: datetime,
    last_started_at: datetime | None,
    last_completed_at: datetime | None,
) -> datetime:
    if last_completed_at is not None:
        return last_completed_at
    if last_started_at is not None:
        return last_started_at
    return user_created_at


def resolve_target_stage(elapsed_timedelta: timedelta) -> int:
    if elapsed_timedelta < timedelta(days=2):
        return 0
    if elapsed_timedelta < timedelta(days=5):
        return 1
    if elapsed_timedelta < timedelta(days=10):
        return 2
    if elapsed_timedelta < timedelta(days=20):
        return 3
    return 4


def should_send(stage_current: int | None, stage_target: int) -> bool:
    if stage_target == 1:
        return stage_current is None
    if stage_target == 2:
        return stage_current in (None, 1)
    if stage_target == 3:
        return stage_current in (None, 2)
    if stage_target == 4:
        return stage_current in (None, 3)
    return False
