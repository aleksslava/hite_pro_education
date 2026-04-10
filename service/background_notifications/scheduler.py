from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot

from service.background_notifications.runner import run_inactivity_notifications_once

logger = logging.getLogger(__name__)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
RUN_HOUR = 18
RUN_MINUTE = 0


def _seconds_until_next_run(now: datetime) -> float:
    next_run = now.replace(
        hour=RUN_HOUR,
        minute=RUN_MINUTE,
        second=0,
        microsecond=0,
    )
    if now > next_run:
        next_run += timedelta(minutes=5)
    return max((next_run - now).total_seconds(), 0.0)


async def _scheduler_loop(bot: Bot) -> None:
    logger.info(
        "Inactivity scheduler started. timezone=%s run_time=%02d:%02d",
        MOSCOW_TZ.key,
        RUN_HOUR,
        RUN_MINUTE,
    )
    try:
        while True:
            now = datetime.now(MOSCOW_TZ)
            sleep_seconds = _seconds_until_next_run(now)
            next_run_at = now + timedelta(seconds=sleep_seconds)
            logger.info("Next inactivity notifications run at %s", next_run_at.isoformat())

            await asyncio.sleep(sleep_seconds)

            try:
                await run_inactivity_notifications_once(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unhandled error in inactivity notifications run")
    except asyncio.CancelledError:
        logger.info("Inactivity scheduler stopped")
        raise


def start_inactivity_scheduler(bot: Bot) -> asyncio.Task:
    return asyncio.create_task(
        _scheduler_loop(bot),
        name="inactivity-notifications-scheduler",
    )


async def stop_inactivity_scheduler(task: asyncio.Task | None) -> None:
    if task is None:
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
