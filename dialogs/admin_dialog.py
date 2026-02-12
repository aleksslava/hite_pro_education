import datetime
import operator
import os
import tempfile

from aiogram.types import CallbackQuery, Message, FSInputFile
from aiogram_dialog.widgets.kbd import Button, Column, Multiselect, Group, Start, Back, Row, Cancel, Next, \
    ManagedMultiselect, Radio, ManagedRadio
from aiogram_dialog.widgets.text import Const, Format
from aiogram_dialog import Dialog, Window, DialogManager, StartMode
from aiogram_dialog.widgets.input import MessageInput
from fsm_forms.fsm_models import AdminDialog
from aiogram.enums import ContentType
from aiogram_dialog.widgets.media import StaticMedia
from config.config import BASE_DIR
from service.questions_lexicon import questions_1 as questions
from service.service import pad_right, format_results, format_progress, checking_result
from db.models import User, HpLessonResult as LessonResult
from amo_api.amo_api import AmoCRMWrapper
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from openpyxl import Workbook


async def admin_getter(dialog_manager: DialogManager, **kwargs):
    return {}

async def add_admin_button(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
):
    await dialog_manager.switch_to(AdminDialog.add_admin)

async def add_admin_input(message: Message, _, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data["session"]

    text = (message.text or "").strip()
    try:
        tg_id = int(text)
    except ValueError:
        await message.answer("Нужен числовой tg_id. Попробуйте ещё раз.")
        return

    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        await message.answer(f"Пользователь с tg_id={tg_id} не найден.")
        return

    if user.is_admin:
        await message.answer(f"Пользователь tg_id={tg_id} уже администратор.")
        await dialog_manager.switch_to(AdminDialog.admin_menu)
        return

    user.is_admin = True
    await session.commit()
    await session.refresh(user)

    await message.answer(f"Пользователю tg_id={tg_id} назначены права администратора.")
    await dialog_manager.switch_to(AdminDialog.admin_menu)

async def second_admin_button(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
):
    session: AsyncSession = dialog_manager.middleware_data["session"]

    result = await session.execute(
        select(User)
        .options(selectinload(User.lesson_results))
        .order_by(User.id)
    )
    users = result.scalars().all()

    if not users:
        await callback.message.answer("Пользователи в БД не найдены.")
        return

    lines = ["Результаты уроков по пользователям", ""]
    total_lessons = 0

    for user in users:
        lessons = sorted(user.lesson_results or [], key=lambda l: l.id or 0)
        total_lessons += len(lessons)
        lines.append(
            f"user_id={user.id} tg_id={user.tg_user_id} "
            f"name={user.first_name or '-'} {user.last_name or '-'}"
        )
        if not lessons:
            lines.append("  результатов нет")
            continue

        for lesson in lessons:
            lines.append(
                "  "
                + " | ".join(
                    [
                        f"lesson_id={lesson.id}",
                        f"key={lesson.lesson_key}",
                        f"score={lesson.score if lesson.score is not None else '-'}",
                        f"compleat={lesson.compleat}",
                        f"started_at={lesson.started_at or '-'}",
                        f"completed_at={lesson.completed_at or '-'}",
                    ]
                )
            )

        lines.append("")

    lines.insert(1, f"Всего результатов: {total_lessons}")

    message = "\n".join(lines)

    # Telegram limit ~4096 chars per message
    max_len = 3900
    for i in range(0, len(message), max_len):
        await callback.message.answer(message[i : i + max_len])

async def delete_user_start(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
):
    await dialog_manager.switch_to(AdminDialog.delete_user)

async def delete_user_input(message: Message, _, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data["session"]

    text = (message.text or "").strip()
    try:
        tg_id = int(text)
    except ValueError:
        await message.answer("Нужен числовой tg_id. Попробуйте ещё раз.")
        return

    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        await message.answer(f"Пользователь с tg_id={tg_id} не найден.")
        return

    await session.delete(user)
    await session.commit()

    await message.answer(f"Пользователь tg_id={tg_id} удалён.")
    await dialog_manager.switch_to(AdminDialog.admin_menu)


async def get_converse(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data["session"]

    result = await session.execute(
        select(User)
        .options(selectinload(User.lesson_results))
        .order_by(User.id)
    )
    users = result.scalars().all()

    if not users:
        await callback.message.answer("Пользователи в БД не найдены.")
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "users_results"

    headers = [
        "user_id",
        "tg_id",
        "username",
        "first_name",
        "last_name",
        "phone_number",
        "amo_contact_id",
        "amo_deal_id",
        "lesson_id",
        "lesson_key",
        "score",
        "compleat",
        "started_at",
        "completed_at",
    ]
    ws.append(headers)

    def fmt_dt(value: datetime.datetime | None) -> str:
        if value is None:
            return ""
        return value.strftime("%Y-%m-%d %H:%M:%S")

    for user in users:
        lessons = sorted(user.lesson_results or [], key=lambda l: l.id or 0)
        if not lessons:
            ws.append(
                [
                    user.id,
                    user.tg_user_id,
                    user.username or "",
                    user.first_name or "",
                    user.last_name or "",
                    user.phone_number or "",
                    user.amo_contact_id or "",
                    user.amo_deal_id or "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
            continue

        for lesson in lessons:
            ws.append(
                [
                    user.id,
                    user.tg_user_id,
                    user.username or "",
                    user.first_name or "",
                    user.last_name or "",
                    user.phone_number or "",
                    user.amo_contact_id or "",
                    user.amo_deal_id or "",
                    lesson.id,
                    lesson.lesson_key,
                    lesson.score if lesson.score is not None else "",
                    lesson.compleat,
                    fmt_dt(lesson.started_at),
                    fmt_dt(lesson.completed_at),
                ]
            )

    filename = f"users_results_{datetime.datetime.utcnow():%Y%m%d_%H%M%S}.xlsx"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp_path = tmp.name
        wb.save(tmp_path)

        await callback.message.answer_document(
            document=FSInputFile(tmp_path, filename=filename),
            caption="Таблица пользователей и результатов",
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

admin_menu = Window(
Const('Выберите нужный пункт меню'),
    Group(
        Column(
            Button(Const("Добавить администратора"),
                   id="1",
                   on_click=add_admin_button,
                   ),
            Button(Const("Результаты прохождений"),
                   id="2",
                   on_click=second_admin_button,
                   ),
            Button(Const("Удалить пользователя"),
                   id="3",
                   on_click=delete_user_start,
                   ),
            Button(Const("Получить таблицу пользователей и результатов"),
                   id="4",
                   on_click=get_converse,
                   ),
        ),
        Row(
            Cancel(Const('Назад в главное меню'), id='cancel')
        )
    ),
    getter=admin_getter,
    state=AdminDialog.admin_menu
)

delete_user = Window(
    Const("Отправьте tg_id пользователя для удаления."),
    MessageInput(delete_user_input, ContentType.TEXT),
    Back(Const("Назад"), id="back_to_admin_menu"),
    state=AdminDialog.delete_user,
)

add_admin = Window(
    Const("Отправьте tg_id пользователя для назначения администратором."),
    MessageInput(add_admin_input, ContentType.TEXT),
    Back(Const("Назад"), id="back_to_admin_menu"),
    state=AdminDialog.add_admin,
)

admin_dialog = Dialog(admin_menu, delete_user, add_admin)
