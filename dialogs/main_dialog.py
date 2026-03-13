import datetime
import logging

from aiogram import F
from aiogram.enums import ContentType, ParseMode
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Column, Back, SwitchTo
from aiogram_dialog.widgets.text import Const, Format
from aiogram_dialog import Dialog, Window, DialogManager, StartMode, ShowMode

from amo_api.amo_service import processing_contact, processing_lead
from fsm_forms.fsm_models import MainDialog, HpFirstLessonDialog, HpSecondLessonDialog, HpThirdLessonDialog, \
    AdminDialog, HpFourthLessonDialog, HpFifthLessonDialog, HpSixthLessonDialog, HpSeventhLessonDialog, \
    HpExamLessonDialog
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from db.models import User, HpLessonResult as LessonResult
from amo_api.amo_api import AmoCRMWrapper
from aiogram.utils.chat_action import ChatActionSender

from service.questions_lexicon import welcome_message, exam_in_message
from service.service import get_lessons_buttons, lesson_access, check_push_to_new_status

logger = logging.getLogger(__name__)
EXAM_WEBAPP_URL = "https://aleksslava.github.io/exam_edu.github.io/"


def _resolve_event_user(dialog_manager: DialogManager):
    event = dialog_manager.event
    from_user = getattr(event, "from_user", None)
    if from_user is not None:
        return from_user

    update = getattr(event, "update", None)
    if update is not None:
        callback_query = getattr(update, "callback_query", None)
        if callback_query is not None and callback_query.from_user is not None:
            return callback_query.from_user

        message = getattr(update, "message", None)
        if message is not None and message.from_user is not None:
            return message.from_user

    return dialog_manager.middleware_data.get("event_from_user")


async def main_menu_getter(dialog_manager: DialogManager, **kwargs):
    session: AsyncSession = dialog_manager.middleware_data['session']
    admin_id = int(dialog_manager.middleware_data['admin_id'])
    if dialog_manager.start_data is not None:
        utm_data = dialog_manager.start_data.get("utm_data", {})
    else:
        utm_data = {}
    from_user = _resolve_event_user(dialog_manager)
    if from_user is None:
        raise ValueError("Cannot resolve user from dialog event")
    tg_id = from_user.id
    logger.info(f'Запущен бот пользователем tg_ID:{tg_id}')
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    lessons_text = {}
    if user is None:
        logger.info(f'Для пользователя tg_id:{tg_id} не найдена запись в БД, создаю новую запись!')

        user = User(
            tg_user_id=tg_id,
            username=from_user.username,
            first_name=from_user.first_name,
            last_name=from_user.last_name,
            utm_campaign=utm_data.get("utm_campaign", ''),
            utm_medium=utm_data.get("utm_medium", ''),
            utm_content=utm_data.get("utm_content", ''),
            utm_term=utm_data.get("utm_term", ''),
            utm_source=utm_data.get("utm_source", ''),
            yclid=utm_data.get("yclid", ''),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info(f'Создана новая запись в таблице USERS: tg_id: {user.tg_user_id}, '
                    f' username: {user.username}, '
                    f' first_name: {user.first_name}')
    else:
        logger.info(f'Получена запись user из БД: tg_id: {user.tg_user_id}, '
                    f' username: {user.username}, '
                    f' first_name: {user.first_name}')
    if user.amo_contact_id is None:
        user_authorized = dialog_manager.dialog_data.get("user_authorized", False)
        button_to_authorized = dialog_manager.dialog_data.get("button_to_authorized", True)
    else:
        user_authorized = dialog_manager.dialog_data.get("user_authorized", True)
        button_to_authorized = dialog_manager.dialog_data.get("button_to_authorized", False)
        lessons_text = await get_lessons_buttons(user, session)

    if tg_id == admin_id:
        user.is_admin = True
        await session.commit()
        await session.refresh(user)

    return {'user_authorized': user_authorized,
            'button_to_authorized': button_to_authorized,
            'is_admin': user.is_admin,
            'lessons_text': lessons_text}


async def send_contact_keyboard(callback: CallbackQuery, _, dialog_manager):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    # отправляем отдельным сообщением, т.к. aiogram-dialog работает с inline-клавиатурами
    msg = await callback.message.answer("Отправьте номер кнопкой", reply_markup=kb)
    dialog_manager.dialog_data["contact_kb_msg_id"] = msg.message_id
    # Не отправляем отдельное сообщение окна, т.к. уже отправили сообщение с reply-клавиатурой
    await dialog_manager.switch_to(MainDialog.phone, show_mode=ShowMode.NO_UPDATE)


def _is_empty(value):
    return value is None or (isinstance(value, str) and value == "")


async def _merge_user_by_amo_contact_id(
    session: AsyncSession,
    current_user: User,
    amo_contact_id: int,
) -> None:
    if current_user.amo_contact_id == amo_contact_id:
        return

    result = await session.execute(
        select(User).where(User.amo_contact_id == amo_contact_id, User.id != current_user.id)
    )
    duplicate_user = result.scalar_one_or_none()
    if duplicate_user is None:
        return

    logger.warning(
        "Найден дубль пользователя по amo_contact_id=%s: keep user_id=%s, merge user_id=%s",
        amo_contact_id,
        current_user.id,
        duplicate_user.id,
    )

    await session.execute(
        update(LessonResult)
        .where(LessonResult.user_id == duplicate_user.id)
        .values(user_id=current_user.id)
    )

    fields_to_fill = (
        "username",
        "max_user_id",
        "first_name",
        "last_name",
        "amo_deal_id",
        "utm_campaign",
        "utm_medium",
        "utm_content",
        "utm_term",
        "utm_source",
        "yclid",
        "client_type",
        "phone_number",
    )
    for field_name in fields_to_fill:
        current_value = getattr(current_user, field_name)
        duplicate_value = getattr(duplicate_user, field_name)
        if _is_empty(current_value) and not _is_empty(duplicate_value):
            setattr(current_user, field_name, duplicate_value)

    if duplicate_user.is_admin and not current_user.is_admin:
        current_user.is_admin = True

    if duplicate_user.start_edu and (
        current_user.start_edu is None or duplicate_user.start_edu < current_user.start_edu
    ):
        current_user.start_edu = duplicate_user.start_edu

    if duplicate_user.created_at < current_user.created_at:
        current_user.created_at = duplicate_user.created_at

    await session.delete(duplicate_user)
    await session.flush()


async def admin_menu(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    await dialog_manager.start(AdminDialog.admin_menu)

async def process_education(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    await dialog_manager.start(MainDialog.process_edu)



async def back_to_main_menu(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    await dialog_manager.start(MainDialog.main, mode=StartMode.NORMAL)

async def first_lesson_start(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data['session']
    tg_id = dialog_manager.event.from_user.id
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f'Пользователь не найден при переходе в урок 1, tg_id: {tg_id}')
    if user.start_edu is None:
        user.start_edu = datetime.datetime.utcnow()
    lesson = LessonResult(
        user_id=user.id,
        lesson_key='lesson_1',
    )
    session.add(lesson)
    await session.commit()
    await session.refresh(lesson)
    logger.info(f'Запущен первый урок пользователем tg_ID:{tg_id}. ID урока в БД - {lesson.id}')
    await callback.answer()
    async with ChatActionSender.upload_video(
            bot=dialog_manager.middleware_data['bot'],
            chat_id=callback.message.chat.id,
            interval=4.0,
            initial_sleep=0.0,
    ):
        await dialog_manager.start(HpFirstLessonDialog.vebinar, mode=StartMode.NORMAL, data={'lesson_id': lesson.id})

async def second_lesson_start(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data['session']
    tg_id = dialog_manager.event.from_user.id
    logger.info(f'Запущен второй урок пользователем tg_ID:{tg_id}')
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f'Пользователь не найден при переходе в урок 2, tg_id: {tg_id}')
    lesson_deny = await lesson_access(user=user, session=session, lesson_key='lesson_2')
    if not lesson_deny:
        await callback.answer('Доступ закрыт!😢\n\nТребуется успешное прохождение урока №1!', show_alert=True)
    else:
        lesson = LessonResult(
            user_id=user.id,
            lesson_key='lesson_2',
        )
        session.add(lesson)
        await session.commit()
        await session.refresh(lesson)
        logger.info(f'Запущен второй урок пользователем tg_ID:{tg_id}. ID урока в БД - {lesson.id}')
        await callback.answer()
        async with ChatActionSender.upload_video(
                bot=dialog_manager.middleware_data['bot'],
                chat_id=callback.message.chat.id,
                interval=4.0,
                initial_sleep=0.0,
        ):
            await dialog_manager.start(HpSecondLessonDialog.vebinar_1, mode=StartMode.NORMAL, data={'lesson_id': lesson.id})

async def third_lesson_start(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data['session']
    tg_id = dialog_manager.event.from_user.id
    logger.info(f'Запущен третий урок пользователем tg_ID:{tg_id}')
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f'Пользователь не найден при переходе в урок 3, tg_id: {tg_id}')
    lesson_deny = await lesson_access(user=user, session=session, lesson_key='lesson_3')
    if not lesson_deny:
        await callback.answer('Доступ закрыт!😢\n\nТребуется успешное прохождение урока №2!', show_alert=True)
    else:
        lesson = LessonResult(
            user_id=user.id,
            lesson_key='lesson_3',
        )
        session.add(lesson)
        await session.commit()
        await session.refresh(lesson)
        logger.info(f'Запущен третий урок пользователем tg_ID:{tg_id}. ID урока в БД - {lesson.id}')
        await callback.answer()
        async with ChatActionSender.upload_video(
                bot=dialog_manager.middleware_data['bot'],
                chat_id=callback.message.chat.id,
                interval=4.0,
                initial_sleep=0.0,
        ):
            await dialog_manager.start(HpThirdLessonDialog.vebinar_1, mode=StartMode.NORMAL, data={'lesson_id': lesson.id})

async def fourth_lesson_start(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data['session']
    tg_id = dialog_manager.event.from_user.id
    logger.info(f'Запущен четвертый урок пользователем tg_ID:{tg_id}')
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f'Пользователь не найден при переходе в урок 4, tg_id: {tg_id}')
    lesson_deny = await lesson_access(user=user, session=session, lesson_key='lesson_4')
    if not lesson_deny:
        await callback.answer('Доступ закрыт!😢\n\nТребуется успешное прохождение урока №3!', show_alert=True)
    else:
        lesson = LessonResult(
            user_id=user.id,
            lesson_key='lesson_4',
        )
        session.add(lesson)
        await session.commit()
        await session.refresh(lesson)
        logger.info(f'Запущен четвертый урок пользователем tg_ID:{tg_id}. ID урока в БД - {lesson.id}')
        await callback.answer()
        async with ChatActionSender.upload_video(
                bot=dialog_manager.middleware_data['bot'],
                chat_id=callback.message.chat.id,
                interval=4.0,
                initial_sleep=0.0,
        ):
            await dialog_manager.start(HpFourthLessonDialog.vebinar_1, mode=StartMode.NORMAL, data={'lesson_id': lesson.id})

async def fifth_lesson_start(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data['session']
    tg_id = dialog_manager.event.from_user.id
    logger.info(f'Запущен пятый урок пользователем tg_ID:{tg_id}')
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f'Пользователь не найден при переходе в урок 5, tg_id: {tg_id}')
    lesson_deny = await lesson_access(user=user, session=session, lesson_key='lesson_5')
    if not lesson_deny:
        await callback.answer('Доступ закрыт!😢\n\nТребуется успешное прохождение урока №4!', show_alert=True)
    else:
        lesson = LessonResult(
            user_id=user.id,
            lesson_key='lesson_5',
        )
        session.add(lesson)
        await session.commit()
        await session.refresh(lesson)
        logger.info(f'Запущен пятый урок пользователем tg_ID:{tg_id}. ID урока в БД - {lesson.id}')
        await callback.answer()
        async with ChatActionSender.upload_video(
                bot=dialog_manager.middleware_data['bot'],
                chat_id=callback.message.chat.id,
                interval=4.0,
                initial_sleep=0.0,
        ):
            await dialog_manager.start(HpFifthLessonDialog.vebinar_1, mode=StartMode.NORMAL, data={'lesson_id': lesson.id})

async def sixth_lesson_start(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data['session']
    tg_id = dialog_manager.event.from_user.id
    logger.info(f'Запущен шестой урок пользователем tg_ID:{tg_id}')
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f'Пользователь не найден при переходе в урок 6, tg_id: {tg_id}')
    lesson_deny = await lesson_access(user=user, session=session, lesson_key='lesson_6')
    if not lesson_deny:
        await callback.answer('Доступ закрыт!😢\n\nТребуется успешное прохождение урока №5!', show_alert=True)
    else:
        lesson = LessonResult(
            user_id=user.id,
            lesson_key='lesson_6',
        )
        session.add(lesson)
        await session.commit()
        await session.refresh(lesson)
        logger.info(f'Запущен шестой урок пользователем tg_ID:{tg_id}. ID урока в БД - {lesson.id}')
        await callback.answer()
        async with ChatActionSender.upload_video(
                bot=dialog_manager.middleware_data['bot'],
                chat_id=callback.message.chat.id,
                interval=4.0,
                initial_sleep=0.0,
        ):
            await dialog_manager.start(HpSixthLessonDialog.vebinar_1, mode=StartMode.NORMAL, data={'lesson_id': lesson.id})

async def seventh_lesson_start(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data['session']
    tg_id = dialog_manager.event.from_user.id
    logger.info(f'Запущен седьмой урок пользователем tg_ID:{tg_id}')
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f'Пользователь не найден при переходе в урок 7, tg_id: {tg_id}')
    lesson_deny = await lesson_access(user=user, session=session, lesson_key='lesson_7')
    if not lesson_deny:
        await callback.answer('Доступ закрыт!😢\n\nТребуется успешное прохождение урока №6!', show_alert=True)
    else:
        lesson = LessonResult(
            user_id=user.id,
            lesson_key='lesson_7',
        )
        session.add(lesson)
        await session.commit()
        await session.refresh(lesson)
        logger.info(f'Запущен шестой урок пользователем tg_ID:{tg_id}. ID урока в БД - {lesson.id}')
        await callback.answer()
        async with ChatActionSender.upload_video(
                bot=dialog_manager.middleware_data['bot'],
                chat_id=callback.message.chat.id,
                interval=4.0,
                initial_sleep=0.0,
        ):
            await dialog_manager.start(HpSeventhLessonDialog.vebinar_1, mode=StartMode.NORMAL, data={'lesson_id': lesson.id})

async def exam_lesson_start(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    session: AsyncSession = dialog_manager.middleware_data['session']
    amo_api: AmoCRMWrapper = dialog_manager.middleware_data["amo_api"]
    status_fields: dict = dialog_manager.middleware_data["amo_fields"].get("statuses")
    pipelines: dict = dialog_manager.middleware_data["amo_fields"].get("pipelines")
    tg_id = dialog_manager.event.from_user.id
    logger.info(f'Запущен экзамен пользователем tg_ID:{tg_id}')
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f'Пользователь не найден при переходе в экзамен, tg_id: {tg_id}')
    lesson_deny = await lesson_access(user=user, session=session, lesson_key='exam')
    if not lesson_deny:
        await callback.answer('Доступ закрыт!😢\n\nТребуется успешное прохождение урока №7!', show_alert=True)
    else:
        lesson = LessonResult(
            user_id=user.id,
            lesson_key='exam',
        )
        session.add(lesson)
        await session.commit()
        await session.refresh(lesson)
        logger.info(f'Запущен экзамен пользователем tg_ID:{tg_id}. ID урока в БД - {lesson.id}')
        await callback.answer()
        kb = ReplyKeyboardMarkup(
            keyboard=[[
                KeyboardButton(
                    text="Открыть экзамен",
                    web_app=WebAppInfo(url=EXAM_WEBAPP_URL),
                )
            ]],
            resize_keyboard=True,
            one_time_keyboard=False,
        )
        if callback.message is not None:
            try:
                await callback.message.delete()
            except Exception:
                logger.exception("Не удалось удалить предыдущее сообщение перед стартом экзамена")

            await callback.message.answer(
                text=exam_in_message,
                reply_markup=kb,
            )
        status_id_in_amo = amo_api.get_lead_by_id(lead_id=user.amo_deal_id).get('status_id')
        push_to_new_status = await check_push_to_new_status(lesson_key='ready_to_exam',
                                                            lead_status=status_id_in_amo)
        if push_to_new_status:
            try:
                amo_api.push_lead_to_status(
                    pipeline_id=pipelines.get("hite_pro_education"),
                    status_id=status_fields.get("ready_to_exam"),
                    lead_id=str(user.amo_deal_id),
                )
            except Exception as error:
                logger.error(f'Не получилось перевести сделку в этап "Приступил к экзамену"')
                logger.exception(error)

        await dialog_manager.start(
            HpExamLessonDialog.vebinar_1,
            mode=StartMode.NORMAL,
            data={'lesson_id': lesson.id},
            show_mode=ShowMode.NO_UPDATE,
        )

# Стартовое меню бота
main_window = Window(
    Const(welcome_message, when="user_authorized"),
    Const("Для доступа к обучению, нажмите на кнопку авторизоваться и поделитесь номером телефона!",
          when="button_to_authorized"),
    Column(
Button(Format("{lessons_text[lesson_1]}"),
               id="1",
               on_click=first_lesson_start,
               when="user_authorized"),
        Button(Format("{lessons_text[lesson_2]}"),
               id="2",
               on_click=second_lesson_start,
               when="user_authorized"),
        Button(Format("{lessons_text[lesson_3]}"),
               id="3",
               on_click=third_lesson_start,
               when="user_authorized"),
        Button(Format("{lessons_text[lesson_4]}"),
                       id="4",
                       on_click=fourth_lesson_start,
                       when="user_authorized"),
        Button(Format("{lessons_text[lesson_5]}"),
                       id='5',
                       on_click=fifth_lesson_start,
                       when="user_authorized"),
        Button(Format("{lessons_text[lesson_6]}"),
                       id="6",
                       on_click=sixth_lesson_start,
                       when="user_authorized"),
        Button(Format("{lessons_text[lesson_7]}"),
                       id="7",
                       on_click=seventh_lesson_start,
                       when="user_authorized"),
        Button(Format("{lessons_text[exam]}"),
                       id="exam",
                       on_click=exam_lesson_start,
                       when="user_authorized"),
        Button(Format("📖 Статистика обучения"),
               id="8",
               on_click=process_education,
               when="user_authorized"),
        Button(Const("Авторизация"),
               id="9",
               on_click=send_contact_keyboard,
               when='button_to_authorized'),
        Button(Const('Личный кабинет администратора'),
               id='10',
               on_click=admin_menu,
               when='is_admin'),
    ),
    state=MainDialog.main,
    getter=main_menu_getter,
    parse_mode=ParseMode.HTML
    )


async def on_contact(message: Message, _, dialog_manager):
    amo_api: AmoCRMWrapper = dialog_manager.middleware_data['amo_api']
    session: AsyncSession = dialog_manager.middleware_data['session']
    status_fields: dict = dialog_manager.middleware_data['amo_fields'].get('statuses')
    pipelines: dict = dialog_manager.middleware_data['amo_fields'].get('pipelines')
    utm_metriks = dialog_manager.middleware_data['amo_fields'].get('fields_id').get('utm_metriks')
    tg_id = dialog_manager.event.from_user.id
    tg_field_id = dialog_manager.middleware_data['amo_fields'].get('fields_id').get('tg_id')
    username_field_id = dialog_manager.middleware_data['amo_fields'].get('fields_id').get('tg_username')
    username = '@' + dialog_manager.event.from_user.username if dialog_manager.event.from_user.username is not None else ''
    phone_number = message.contact.phone_number
    logger.info(f'Пользователь tg_id: {tg_id} поделился номером телефона: {phone_number}')
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    user = result.scalar_one_or_none()
    user.phone_number = phone_number
    contact_data = processing_contact(amo_api=amo_api, contact_phone_number=str(phone_number))

    if contact_data: # Данные контакта найдены в амосрм
        if not contact_data['tg_id']: # Если tg_id нет в контакте, то добавляем
            amo_api.add_tg_to_contact(contact_id=contact_data["amo_contact_id"], tg_id=tg_id, tg_id_field=tg_field_id,
                                      username_id=username_field_id, username=username)
            logger.info('попытка записать данные tg_id')
        await _merge_user_by_amo_contact_id(
            session=session,
            current_user=user,
            amo_contact_id=contact_data["amo_contact_id"],
        )
        user.first_name = contact_data["first_name"]
        user.last_name = contact_data["last_name"]
        user.amo_contact_id = contact_data["amo_contact_id"]
        logger.info(f'Пользователь tg_id: {tg_id} найден в амосрм: {user.first_name} {user.last_name}')
        lead_data = processing_lead(amo_api=amo_api, contact_id=contact_data["amo_contact_id"],
                                    pipeline_id=pipelines["hite_pro_education"], status_id=status_fields['admitted_to_training'],)
        if lead_data: # Данные сделки найдены в амосрм
            user.amo_deal_id = lead_data["amo_deal_id"]
            logger.info(f'Для пользователя{user.first_name} {user.last_name} tg_id: {tg_id} найдена сделка в амосрм')

        else: # Сделка не найдена, создаём новую
            logger.info(f'Для пользователя{user.first_name} {user.last_name} tg_id: {tg_id} не найдена сделка в амосрм')
            new_lead_id = amo_api.send_lead_to_amo(pipeline_id=pipelines.get('hite_pro_education'),
                                                   status_id=status_fields.get('admitted_to_training'),
                                                   contact_id=contact_data.get("amo_contact_id"),
                                                   utm_metriks_fields=utm_metriks,
                                                   user=user
                                                   )
            user.amo_deal_id = new_lead_id
            logger.info(f'Для пользователя{user.first_name} {user.last_name} tg_id: {tg_id} создана сделка {new_lead_id}')

    else: # данные контакта не найдены в амосрм, создаём контакт и сделку
        first_name = dialog_manager.event.from_user.first_name if dialog_manager.event.from_user.first_name is not None else ''
        last_name = dialog_manager.event.from_user.last_name if dialog_manager.event.from_user.last_name is not None else ''
        logger.info(f'В амо не найден контакт для пользователя tg_id: {tg_id}, телефон: {phone_number}')
        new_contact_id = amo_api.create_new_contact(first_name=first_name,
                                                    last_name=last_name,
                                                    phone=message.contact.phone_number,
                                                    tg_id_field=tg_field_id, tg_id=tg_id,
                                                    username_id=username_field_id, username=username)
        new_lead_id = amo_api.send_lead_to_amo(pipeline_id=pipelines.get('hite_pro_education'),
                                               status_id=status_fields.get('admitted_to_training'),
                                               contact_id=new_contact_id,
                                               utm_metriks_fields=utm_metriks,
                                               user=user
                                               )
        await _merge_user_by_amo_contact_id(
            session=session,
            current_user=user,
            amo_contact_id=new_contact_id,
        )
        user.amo_deal_id = new_lead_id
        user.amo_contact_id = new_contact_id
        logger.info(f'Для пользователя tg_id: {tg_id}, телефон: {phone_number} создан новый контакт {new_contact_id} и '
                    f'новая сделка {new_lead_id}')

    await session.commit()
    await session.refresh(user)
    response = amo_api.push_lead_to_status(pipeline_id=pipelines.get('hite_pro_education'),
                                           status_id=status_fields.get('authorized_in_bot'),
                                           lead_id=str(user.amo_deal_id))
    if response:
        logger.info(f'Сделка {user.amo_deal_id} перемещена в следующий этап - Авторизовался в боте')
    else:
        logger.info(f'Не получилось переместить сделку id: {user.amo_deal_id} дальше по воронке')

    await message.answer("Спасибо! Номер получен ✅", reply_markup=ReplyKeyboardRemove())
    dialog_manager.dialog_data.update(user_authorized=True, button_to_authorized=False)
    await dialog_manager.switch_to(MainDialog.main)

phone = Window(
        Const("Отправь контакт кнопкой на клавиатуре ниже."),
        MessageInput(on_contact, ContentType.CONTACT),
        state=MainDialog.phone,
    )

async def process_edu_getter(dialog_manager: DialogManager, **kwargs):
    session: AsyncSession = dialog_manager.middleware_data["session"]
    tg_id = dialog_manager.event.from_user.id

    result = await session.execute(
        select(User)
        .options(selectinload(User.lesson_results))
        .where(User.tg_user_id == tg_id)
    )
    user = result.scalar_one_or_none()

    lesson_names = {
        "lesson_1": "Урок №1",
        "lesson_2": "Урок №2",
        "lesson_3": "Урок №3",
        "lesson_4": "Урок №4",
        "lesson_5": "Урок №5",
        "lesson_6": "Урок №6",
        "lesson_7": "Урок №7",
        "exam": "Экзамен",
    }

    if user is None:
        return {"message": "Пользователь не найден."}

    results_by_key: dict[str, list[LessonResult]] = {}
    for lesson in user.lesson_results or []:
        results_by_key.setdefault(lesson.lesson_key, []).append(lesson)

    lines: list[str] = []
    for lesson_key in lesson_names.keys():
        lesson_title = lesson_names.get(lesson_key, lesson_key)
        lines.append(f"{lesson_title}:")

        attempts = results_by_key.get(lesson_key, [])
        attempts_sorted = sorted(attempts, key=lambda l: l.id or 0)
        total_attempts = len(attempts_sorted)
        successful_attempts = sum(1 for attempt in attempts_sorted if attempt.compleat)

        completed_attempts = [attempt for attempt in attempts_sorted if attempt.completed_at is not None]
        if completed_attempts:
            last_completed_attempt = max(
                completed_attempts,
                key=lambda attempt: (attempt.completed_at, attempt.id or 0),
            )
            if last_completed_attempt.score is not None:
                last_result_text = f"{last_completed_attempt.score} баллов."
            else:
                last_result_text = "нет данных."
        else:
            last_result_text = "нет данных."

        lines.append(f"📖 Всего попыток - {total_attempts}")
        lines.append(f"✅ Успешных - {successful_attempts}")
        lines.append(f"⏩ Результат последней попытки - {last_result_text}")

        lines.append("")
    lines.append("Успешной попыткой считается результат: более 80% правильных ответов.")
    message = "\n".join(lines).strip()
    return {"message": message}

process_edu_message = Window(
    Format('{message}'),
    SwitchTo(Const('Назад'), id='go_back_dialog', state=MainDialog.main),
    getter=process_edu_getter,
    state=MainDialog.process_edu,
)

main_menu_dialog = Dialog(main_window, process_edu_message, phone)
