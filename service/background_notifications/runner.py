from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from config.config import BASE_DIR
from db import async_session_factory
from service.background_message import get_background_message
from service.background_notifications.repository import (
    get_last_lesson_result,
    get_notification_candidates,
    update_notification_stage,
)
from service.background_notifications.rules import (
    resolve_activity_at,
    resolve_target_stage,
    should_send,
)

logger = logging.getLogger(__name__)
NOTIFICATION_PHOTO_PATH = BASE_DIR / "media" / "photo" / "notification.png"
CONTINUE_EDU_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Продолжить обучение", callback_data="start")],
    ]
)


def _build_stats() -> dict[str, int]:
    return {
        "processed": 0,
        "skipped": 0,
        "sent": 0,
        "errors": 0,
    }


async def run_inactivity_notifications_once(bot: Bot) -> dict[str, int]:
    stats = _build_stats()
    now_utc = datetime.utcnow()

    async with async_session_factory() as session:
        users = await get_notification_candidates(session)

        for user in users:
            stats["processed"] += 1
            try:
                last_result = await get_last_lesson_result(session, user.id)
                last_started_at = last_result.started_at if last_result is not None else None
                last_completed_at = last_result.completed_at if last_result is not None else None

                activity_at = resolve_activity_at(
                    user_created_at=user.created_at,
                    last_started_at=last_started_at,
                    last_completed_at=last_completed_at,
                )
                elapsed = now_utc - activity_at
                target_stage = resolve_target_stage(elapsed)
                current_stage = user.notification_stage

                if current_stage is not None and target_stage < current_stage:
                    await update_notification_stage(session, user.id, None)
                    await session.commit()
                    current_stage = None
                    user.notification_stage = None

                if target_stage == 0:
                    stats["skipped"] += 1
                    continue

                if not should_send(current_stage, target_stage):
                    stats["skipped"] += 1
                    continue

                message = get_background_message(target_stage)
                if not message:
                    logger.error(
                        "Missing inactivity template for stage=%s user_id=%s",
                        target_stage,
                        user.id,
                    )
                    stats["errors"] += 1
                    continue

                try:
                    if user.tg_user_id is not None:
                        await bot.send_message(
                            chat_id=user.tg_user_id,
                            text=message,
                            reply_markup=CONTINUE_EDU_KEYBOARD,
                        )
                            # await bot.send_photo( # пример отправки сообщения с фото, пока что не используется.
                            #     chat_id=user.tg_user_id,
                            #     photo=FSInputFile(NOTIFICATION_PHOTO_PATH),
                            #     caption=message,
                            #     reply_markup=CONTINUE_EDU_KEYBOARD,
                            # )
                except Exception:
                    logger.exception(
                        "Failed to send inactivity message user_id=%s tg_user_id=%s stage=%s",
                        user.id,
                        user.tg_user_id,
                        target_stage,
                    )
                    stats["errors"] += 1
                    continue

                await update_notification_stage(session, user.id, target_stage)
                await session.commit()
                user.notification_stage = target_stage
                stats["sent"] += 1
            except Exception:
                await session.rollback()
                logger.exception(
                    "Unexpected error while processing inactivity notifications for user_id=%s",
                    user.id,
                )
                stats["errors"] += 1

    logger.info(
        "Inactivity notifications run finished: processed=%s skipped=%s sent=%s errors=%s",
        stats["processed"],
        stats["skipped"],
        stats["sent"],
        stats["errors"],
    )
    return stats
