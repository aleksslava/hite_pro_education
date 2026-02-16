import datetime
import json
import logging
from ast import literal_eval

from aiogram.enums import ContentType
from aiogram.types import (
    Message,
    ReplyKeyboardRemove,
)
from aiogram_dialog import Dialog, DialogManager, ShowMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Cancel, Url, Column
from aiogram_dialog.widgets.media import StaticMedia
from aiogram_dialog.widgets.text import Const, Format
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from amo_api.amo_api import AmoCRMWrapper
from config.config import BASE_DIR
from db import HpLessonResult as LessonResult
from fsm_forms.fsm_models import HpExamLessonDialog
from service.questions_lexicon import exam_lesson, edu_compleat_text, urls_to_messanger
from service.service import check_push_to_new_status

logger = logging.getLogger(__name__)


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


def _evaluate_exam_answers(user_answers: dict) -> dict:
    user_result_lines: list[str] = []
    amo_note_lines: list[str] = []
    correct_questions = 0

    for question_number, (q_key, expected_map) in enumerate(exam_lesson.items(), start=1):
        incoming_map = user_answers.get(q_key, {})
        if not isinstance(incoming_map, dict):
            incoming_map = {}

        question_is_correct = True
        amo_note_lines.append(f"Вопрос {question_number}:")

        for expected_key, expected_value in expected_map.items():
            actual_value = incoming_map.get(expected_key)
            is_correct = _safe_int(actual_value, default=-999999) == _safe_int(expected_value)
            if not is_correct:
                question_is_correct = False

            actual_value_text = str(actual_value) if actual_value is not None else "не указан"
            amo_note_lines.append(f"{expected_key} - {actual_value_text} {is_correct}")

        extra_keys = [key for key in incoming_map.keys() if key not in expected_map]
        for extra_key in extra_keys:
            question_is_correct = False
            amo_note_lines.append(f"{extra_key} - {incoming_map.get(extra_key)} False")

        if question_is_correct:
            correct_questions += 1

        user_result_lines.append(f"Вопрос {question_number} {'✅' if question_is_correct else '❌'}")

    passed = correct_questions == len(exam_lesson)
    result_text = "\n".join(user_result_lines)
    amo_note_text = "\n".join(amo_note_lines)
    return {
        "score": correct_questions,
        "passed": passed,
        "total_questions": len(exam_lesson),
        "result_text": result_text,
        "amo_note_text": amo_note_text,
    }


async def exam_webapp_getter(dialog_manager: DialogManager, **kwargs):
    return {}


async def on_webapp_data(message: Message, _, dialog_manager: DialogManager):
    raw_data = (message.web_app_data.data or "").strip()
    if not raw_data:
        await message.answer(
            "Не удалось получить данные из WebApp. Пройдите экзамен еще раз.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError:
        try:
            payload = literal_eval(raw_data)
        except (ValueError, SyntaxError):
            logger.exception("Invalid WEB_APP_DATA payload: %s", raw_data)
            await message.answer(
                "Данные пришли в неверном формате. Попробуйте пройти экзамен еще раз.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

    if not isinstance(payload, dict):
        await message.answer(
            "Некорректный формат данных из WebApp. Ожидался JSON-объект.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    answers = payload.get("answers")
    if not isinstance(answers, dict):
        await message.answer(
            "В данных из WebApp отсутствует поле 'answers' или оно некорректно.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    parsed_payload = _evaluate_exam_answers(answers)
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
    passed = _safe_bool(payload.get("passed"), default=False)
    result_text = str(payload.get("result_text", "Результат экзамена получен."))
    amo_note_text = str(payload.get("amo_note_text", ""))

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
            lesson.completed_at = datetime.datetime.utcnow()

            user = lesson.user
            await session.commit()
            await session.refresh(lesson)
            await session.refresh(user)

            if user is not None and user.amo_deal_id is not None:
                amo_api.add_new_note_to_lead(
                    lead_id=user.amo_deal_id,
                    text=amo_note_text or result_text,
                )
                user_lead_id = user.amo_deal_id
                status_id_in_amo = amo_api.get_lead_by_id(lead_id=user_lead_id).get('status_id')
                push_to_new_status = await check_push_to_new_status(lesson_key='compleat_exam',
                                                              lead_status=status_id_in_amo)
                if passed:
                    if push_to_new_status:
                        amo_api.push_lead_to_status(
                            pipeline_id=pipelines.get("hite_pro_education"),
                            status_id=status_fields.get("compleat_exam"),
                            lead_id=str(user.amo_deal_id),
                        )
                    result_text = '<b>Экзамен пройден!</b>\n\n' + result_text
                    await dialog_manager.event.bot.send_message(text=result_text, chat_id=tg_id)

    return {
        "result_text": result_text if not passed else "",
        "passed": passed,
        "compleat_text": edu_compleat_text,
        'url_tg': urls_to_messanger.get('tg'),
        'url_wa': urls_to_messanger.get('whatsapp'),
        'url_max': urls_to_messanger.get('max'),
    }


vebinar_1 = Window(
    Const(
        text=(
            "<b>🎓 Экзамен HiTE PRO</b>\n\n"
            "👇Откройте экзамен через кнопку на клавиатуре ниже👇"
        )
    ),
    MessageInput(on_webapp_data, ContentType.WEB_APP_DATA),
    state=HpExamLessonDialog.vebinar_1,
    getter=exam_webapp_getter,
)


result = Window(
    StaticMedia(
        path=BASE_DIR / "media" / "photo" / "exam_1.jpg",
        type=ContentType.PHOTO,
        when='passed',
    ),
    StaticMedia(
        path=BASE_DIR / "media" / "photo" / "exam_2.png",
        type=ContentType.PHOTO,
        when='passed',
    ),
    Format(text="<b>Экзамен не пройден!</b>🥹\n\n", when='result_text'),
    Format(text="{result_text}", when='result_text'),
    Format(text="{compleat_text}", when='passed'),
    Format(text='Смотрите <a href="https://vk.com/video-140176277_456239582?list=ln-ZzlVOBtZszjuNCd61Z&clckid=1d2b9df5">видеопоздравление</a> от основателя компании Анатолия Кайибханова!',
           when='passed'),
    Column(
        Url(Const('🔵 Сообщить в Telegram'), url=Format("{url_tg}"), when='passed'),
        Url(Const('🟢 Сообщить в WhatsApp'), url=Format("{url_wa}"), when='passed'),
        Url(Const('🟣 Сообщить в Max'), url=Format("{url_max}"), when='passed'),
        Cancel(Const("В главное меню"), id="cancel", show_mode=ShowMode.SEND),
    ),
    state=HpExamLessonDialog.result_exam_lesson,
    getter=result_getter,
)


hp_exam_lesson_dialog = Dialog(vebinar_1, result)
