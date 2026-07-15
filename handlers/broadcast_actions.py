from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from dialogs.main_dialog import (
    back_to_main_menu,
    exam_lesson_start,
    fifth_lesson_start,
    first_lesson_start,
    fourth_lesson_start,
    process_education,
    second_lesson_start,
    seventh_lesson_start,
    sixth_lesson_start,
    third_lesson_start,
)


broadcast_actions_router = Router()

ACTION_HANDLERS = {
    "main_menu": back_to_main_menu,
    "stat": process_education,
    "lesson_1": first_lesson_start,
    "lesson_2": second_lesson_start,
    "lesson_3": third_lesson_start,
    "lesson_4": fourth_lesson_start,
    "lesson_5": fifth_lesson_start,
    "lesson_6": sixth_lesson_start,
    "lesson_7": seventh_lesson_start,
    "exam": exam_lesson_start,
}


@broadcast_actions_router.callback_query(F.data.startswith("broadcast:"))
async def run_broadcast_action(callback: CallbackQuery, dialog_manager: DialogManager) -> None:
    action_key = (callback.data or "").partition(":")[2]
    handler = ACTION_HANDLERS.get(action_key)
    if handler is None:
        await callback.answer("Действие недоступно.", show_alert=True)
        return
    if action_key != "main_menu":
        session: AsyncSession = dialog_manager.middleware_data["session"]
        result = await session.execute(select(User).where(User.tg_user_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if user is None or user.amo_contact_id is None or not user.client_type:
            await callback.answer(
                "Сначала пройдите авторизацию в главном меню бота.",
                show_alert=True,
            )
            return
    if action_key in {"main_menu", "stat"}:
        await callback.answer()
    await handler(callback, None, dialog_manager)
