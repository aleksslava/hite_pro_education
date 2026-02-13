import datetime
import json
import logging

from aiogram.enums import ContentType
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from aiogram_dialog import Dialog, DialogManager, ShowMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Cancel
from aiogram_dialog.widgets.text import Const, Format
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from amo_api.amo_api import AmoCRMWrapper
from db import HpLessonResult as LessonResult
from fsm_forms.fsm_models import HpExamLessonDialog

logger = logging.getLogger(__name__)

WEBAPP_URL = "https://aleksslava.github.io/exam_edu.github.io/"


def _safe_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return value != 0
    return default


def _parse_exam_payload(payload: dict) -> dict:
    total_questions = _safe_int(
        payload.get("total_questions")
        or payload.get("totalQuestions")
        or payload.get("questions_count")
        or payload.get("questionsCount")
    )
    correct_answers = _safe_int(
        payload.get("correct_answers")
        or payload.get("correctAnswers")
        or payload.get("correct")
    )

    score = payload.get("score")
    if score is None:
        score = payload.get("percent")
    if score is None:
        score = payload.get("percentage")
    if score is None and total_questions > 0:
        score = round((correct_answers / total_questions) * 100)
    score = _safe_int(score, 0)

    passed = payload.get("passed")
    if passed is None:
        passed = payload.get("isPassed")
    if passed is None:
        passed = payload.get("compleat")
    if passed is None:
        passed = score >= 80
    passed = _safe_bool(passed, default=score >= 80)

    text_result = payload.get("result_text") or payload.get("resultText")
    if text_result is None:
        if total_questions > 0:
            text_result = (
                f"Верных ответов: {correct_answers}/{total_questions} ({score}%). "
                f"{'Экзамен пройден.' if passed else 'Экзамен не пройден.'}"
            )
        else:
            text_result = f"Результат: {score}%. {'Экзамен пройден.' if passed else 'Экзамен не пройден.'}"

    return {
        "score": score,
        "passed": passed,
        "total_questions": total_questions,
        "correct_answers": correct_answers,
        "result_text": str(text_result),
    }


async def exam_webapp_getter(dialog_manager: DialogManager, **kwargs):
    if dialog_manager.dialog_data.get("webapp_kb_sent"):
        return {}

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Открыть экзамен",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

    event = dialog_manager.event
    sent = False
    if isinstance(event, CallbackQuery) and event.message is not None:
        await event.message.answer(
            "Нажмите кнопку ниже, чтобы открыть WebApp с экзаменом.",
            reply_markup=keyboard,
        )
        sent = True
    elif isinstance(event, Message):
        await event.answer(
            "Нажмите кнопку ниже, чтобы открыть WebApp с экзаменом.",
            reply_markup=keyboard,
        )
        sent = True

    if sent:
        dialog_manager.dialog_data["webapp_kb_sent"] = True

    return {}


async def on_webapp_data(message: Message, _, dialog_manager: DialogManager):
    raw_data = (message.web_app_data.data or "").strip()
    if not raw_data:
        await message.answer("Не удалось получить данные из WebApp. Пройдите экзамен еще раз.")
        return

    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError:
        logger.exception("Invalid WEB_APP_DATA payload: %s", raw_data)
        await message.answer("Данные пришли в неверном формате. Попробуйте пройти экзамен еще раз.")
        return

    if not isinstance(payload, dict):
        await message.answer("Некорректный формат данных из WebApp. Ожидался JSON-объект.")
        return
    await message.answer(text=str(payload))
    parsed_payload = _parse_exam_payload(payload)
    dialog_manager.dialog_data["exam_payload_raw"] = raw_data
    dialog_manager.dialog_data["exam_payload"] = parsed_payload

    await message.answer("Ответы получены. Выполняю проверку.", reply_markup=ReplyKeyboardRemove())
    await dialog_manager.switch_to(HpExamLessonDialog.result_exam_lesson, show_mode=ShowMode.SEND)


async def result_getter(dialog_manager: DialogManager, **kwargs):
    amo_api: AmoCRMWrapper = dialog_manager.middleware_data["amo_api"]
    session: AsyncSession = dialog_manager.middleware_data["session"]
    status_fields: dict = dialog_manager.middleware_data["amo_fields"].get("statuses")
    pipelines: dict = dialog_manager.middleware_data["amo_fields"].get("pipelines")
    tg_id = dialog_manager.event.from_user.id
    lesson_id = dialog_manager.start_data.get("lesson_id")

    payload = dialog_manager.dialog_data.get("exam_payload", {})
    score = _safe_int(payload.get("score"), 0)
    passed = bool(payload.get("passed", False))
    result_text = str(payload.get("result_text", "Результат экзамена получен."))

    logger.info(
        "Получен результат экзамена для пользователя tg_id=%s. score=%s, passed=%s",
        tg_id,
        score,
        passed,
    )

    if lesson_id is not None:
        lesson_result = await session.execute(
            select(LessonResult)
            .options(selectinload(LessonResult.user))
            .where(LessonResult.id == lesson_id)
        )
        lesson = lesson_result.scalar_one_or_none()
        if lesson is not None:
            lesson.score = score
            lesson.compleat = passed
            lesson.result = result_text[:128]
            lesson.completed_at = datetime.datetime.utcnow()

            user = lesson.user
            await session.commit()
            await session.refresh(lesson)
            await session.refresh(user)

            if user is not None and user.amo_deal_id is not None:
                amo_api.add_new_note_to_lead(
                    lead_id=user.amo_deal_id,
                    text=f"Результаты экзамена: {result_text}",
                )
                if passed:
                    amo_api.push_lead_to_status(
                        pipeline_id=pipelines.get("hite_pro_education"),
                        status_id=status_fields.get("compleat_exam"),
                        lead_id=str(user.amo_deal_id),
                    )

    return {
        "result_text": result_text,
        "score": score,
        "passed_text": "Экзамен пройден" if passed else "Экзамен не пройден",
    }


vebinar_1 = Window(
    Const(
        text=(
            "<b>Экзамен HiTE PRO</b>\n\n"
            "Откройте экзамен через кнопку на клавиатуре ниже. "
            "После завершения WebApp автоматически отправит ваши ответы в бот."
        )
    ),
    MessageInput(on_webapp_data, ContentType.WEB_APP_DATA),
    Cancel(Const("Назад"), id="go_cancel_dialog"),
    state=HpExamLessonDialog.vebinar_1,
    getter=exam_webapp_getter,
)


result = Window(
    Const("Результаты экзамена:"),
    Format("{result_text}\n\nИтог: {passed_text}\nБаллы: {score}%"),
    Cancel(Const("В главное меню"), id="cancel", show_mode=ShowMode.SEND),
    state=HpExamLessonDialog.result_exam_lesson,
    getter=result_getter,
)


hp_exam_lesson_dialog = Dialog(vebinar_1, result)
