import datetime
import logging
import operator
from aiogram.types import CallbackQuery
from aiogram.utils.chat_action import ChatActionSender
from aiogram_dialog.widgets.kbd import Button, Column, Multiselect, Group, Start, Back, Row, Cancel, Next, \
    ManagedMultiselect, Radio, ManagedRadio, SwitchTo, Url
from aiogram_dialog.widgets.text import Const, Format
from aiogram_dialog import Dialog, Window, DialogManager, StartMode, ShowMode
from sqlalchemy.ext.asyncio import AsyncSession

from amo_api.amo_api import AmoCRMWrapper
from db import HpLessonResult as LessonResult

from fsm_forms.fsm_models import HpSeventhLessonDialog
from aiogram.enums import ContentType
from aiogram_dialog.widgets.media import StaticMedia
from config.config import BASE_DIR
from service.questions_lexicon import questions_7 as questions, explan, edu_compleat_text, urls_to_messanger
from service.service import pad_right, format_results, format_progress, checking_result, count_missed_answers, \
    check_push_to_new_status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


# Геттер для вопросов
async def question_answers(dialog_manager: DialogManager, **kwargs):
    current_state = dialog_manager.current_context().state.state
    question_answers = questions.get(current_state).get("answers")
    title = questions.get(current_state).get("title")
    key = questions.get(current_state).get("key")
    dialog_manager.dialog_data[f"{key}_items"] = question_answers
    confirm_stage = dialog_manager.dialog_data.get('confirm_stage', False)
    dont_first_question = False if key[1:] == '1' else True
    dont_last_question = True

    text_answers = '<b>Варианты ответов:</b>\n'
    for index, item in enumerate(question_answers, start=1):
        text_answers += f'{index}) {item[0]}\n\n'

    max_answer_len = len(max(map(lambda x: x[0], question_answers), key=len))
    question_answers = [
        (pad_right(title, max_answer_len), opt_id, is_correct)
        for title, opt_id, is_correct in question_answers
    ]

    return {"question_answers": question_answers,
            "title": title,
            'quest_number': key[1:],
            'count_quest': str(len(questions)),
            'text_answers': text_answers,
            'multi': explan.get('multi'),
            'radio': explan.get('radio'),
            'confirm_stage': confirm_stage,
            'dont_first_question': dont_first_question,
            'dont_last_question': dont_last_question,
            }


# Хендлер для multiselect ответов
async def multiselect_question_answers_checked(
    event: CallbackQuery,
    widget: ManagedMultiselect,
    dialog_manager: DialogManager,
    item_id: str,
):
    checked_ids = set(widget.get_checked())
    state = dialog_manager.current_context().state.state
    key = questions.get(state).get("key")
    # (title, id, should_be_selected)
    items = dialog_manager.dialog_data.get(f"{key}_items", [])

    # Считаем "правильность" по каждому варианту
    per_option_result = {}
    for title, opt_id, should_be_selected in items:
        user_selected = opt_id in checked_ids
        per_option_result[title] = (user_selected == should_be_selected)

    # Записываем в нужном формате
    dialog_manager.dialog_data.setdefault("answers", {})
    dialog_manager.dialog_data["answers"][f"{key}"] = per_option_result

# Хендлер для radio вопросов
async def radio_question_answers_checked(
    event: CallbackQuery,
    widget: ManagedRadio,
    dialog_manager: DialogManager,
    item_id: str,
):
    checked_id = widget.get_checked()
    state = dialog_manager.current_context().state.state
    key = questions.get(state).get("key")
    # (title, id, should_be_selected)
    items = dialog_manager.dialog_data.get(f"{key}_items", [])

    # Считаем "правильность" по каждому варианту
    per_option_result = {}
    for title, opt_id, should_be_selected in items:
        user_selected = checked_id == opt_id
        per_option_result[title] = (user_selected == should_be_selected)

    # Записываем в нужном формате
    dialog_manager.dialog_data.setdefault("answers", {})
    dialog_manager.dialog_data["answers"][f"{key}"] = per_option_result


# Условие дял отображения базовых кнопок Вперед и назад
def show_when_not_confirmed(data, widget, manager) -> bool:
    return not data.get("confirm_stage", False)

# Группа кнопок, отображаемых при достижении этапа "Подтверждение результатов"
confirm_stage_row_buttons: Row = Row(
    SwitchTo(Const('⏪'), id='to_first', when='dont_first_question', state=HpSeventhLessonDialog.first_question),
    Back(Const('⬅️'), id='back', when='dont_first_question'),
    Next(Const('➡️'), id='next', when='dont_last_question'),
    SwitchTo(Const('⏩'), id='to_last', when='dont_last_question', state=HpSeventhLessonDialog.confirm_answers),
    when='confirm_stage',
)

base_row_buttons: Row = Row(
    Back(Const('Назад'), id='go_back_dialog'),
            Next(Const('Вперед'), id='go_next_dialog'),
    when=show_when_not_confirmed
)
async def checking_missed_answers(callback: CallbackQuery, button: Button, dialog_manager: DialogManager):
    lesson_result = dialog_manager.dialog_data.get('answers', {})
    if await count_missed_answers(answers=lesson_result, total_questions=len(questions)) > 0:
        await callback.answer('❗️Ответьте на все вопросы❗️', show_alert=True)
    else:
        await dialog_manager.switch_to(HpSeventhLessonDialog.result_seventh_lesson)

result_row_button: Row = Row(
    Button(Const('Отправить результат на проверку'), id='ti_result',
             # state=KeywayThirdLessonDialog.result_third_lesson,
             on_click=checking_missed_answers,
             when='confirm_stage'),
)


vebinar_1 = Window(
    Const(text="<b>Запись седьмого урока HiTE PRO!</b>\n"
               "Не грузится видео? Посмотри по ссылке: <a href='https://peertube.hite-pro.ru/w/bf9K9oNbJo43AoLsqUzjkZ'>Урок 7</a>"),
    StaticMedia(
        path=BASE_DIR / "media" / "video" / "hp_lesson_7.mp4",
        type=ContentType.VIDEO,
        media_params={"supports_streaming": True,
                      "width": 1920,
                      "height": 1080,
                      },
    ),
    Group(
        Row(
            Cancel(Const('Назад'), id='go_cancel_dialog'),
            Next(Const('Вперед'), id='next', show_mode=ShowMode.SEND),
        ))
    ,
    state=HpSeventhLessonDialog.vebinar_1,
    )


first_question = Window(
    Format(text="<b>Вопрос #{quest_number} из {count_quest}:\n\n{title}</b>\n{radio}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 {item[0]}'),
                unchecked_text=Format('⚪ {item[0]}'),
                id='first_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.first_question,
    getter=question_answers
    )


second_question = Window(
    Format(text="<b>Вопрос #{quest_number}: из {count_quest}\n\n{title}</b>\n{radio}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 {item[0]}'),
                unchecked_text=Format('⚪ {item[0]}'),
                id='second_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.second_question,
    getter=question_answers
    )

third_question = Window(
    Format(text="<b>Вопрос #{quest_number} из {count_quest}:\n\n{title}</b>\n{radio}\n\n{text_answers}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 Вариант {item[1]}'),
                unchecked_text=Format('⚪ Вариант {item[1]}'),
                id='third_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.third_question,
    getter=question_answers
    )


fourth_question = Window(
    Format(text="<b>Вопрос #{quest_number} из {count_quest}:\n\n{title}</b>\n{radio}\n\n{text_answers}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 Вариант {item[1]}'),
                unchecked_text=Format('⚪ Вариант {item[1]}'),
                id='fourth_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.fourth_question,
    getter=question_answers
    )

fifth_question = Window(
    Format(text="<b>Вопрос #{quest_number} из {count_quest}:\n\n{title}</b>\n{radio}\n\n{text_answers}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 Вариант {item[1]}'),
                unchecked_text=Format('⚪ Вариант {item[1]}'),
                id='fifth_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.fifth_question,
    getter=question_answers
    )

sixth_question = Window(
    Format(text="<b>Вопрос #{quest_number} из {count_quest}:\n\n{title}</b>\n{radio}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 {item[0]}'),
                unchecked_text=Format('⚪ {item[0]}'),
                id='sixth_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.sixth_question,
    getter=question_answers
    )

seventh_question = Window(
    Format(text="<b>Вопрос #{quest_number} из {count_quest}:\n\n{title}</b>\n{radio}\n\n{text_answers}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 Вариант {item[1]}'),
                unchecked_text=Format('⚪ Вариант {item[1]}'),
                id='seventh_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.seventh_question,
    getter=question_answers
    )

eighth_question = Window(
    Format(text="<b>Вопрос #{quest_number} из {count_quest}:\n\n{title}</b>\n{radio}\n\n{text_answers}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 Вариант {item[1]}'),
                unchecked_text=Format('⚪ Вариант {item[1]}'),
                id='eighth_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.eighth_question,
    getter=question_answers
    )

ninth_question = Window(
    Format(text="<b>Вопрос #{quest_number} из {count_quest}:\n\n{title}</b>\n{radio}\n\n{text_answers}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 Вариант {item[1]}'),
                unchecked_text=Format('⚪ Вариант {item[1]}'),
                id='ninth_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.ninth_question,
    getter=question_answers
    )

tenth_question = Window(
    Format(text="<b>Вопрос #{quest_number} из {count_quest}:\n\n{title}</b>\n{radio}\n\n{text_answers}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 Вариант {item[1]}'),
                unchecked_text=Format('⚪ Вариант {item[1]}'),
                id='tenth_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.tenth_question,
    getter=question_answers
    )

eleventh_question = Window(
    Format(text="<b>Вопрос #{quest_number} из {count_quest}:\n\n{title}</b>\n{radio}\n\n{text_answers}"),
    Group(
        Column(
            Radio(
                checked_text=Format('🟢 Вариант {item[1]}'),
                unchecked_text=Format('⚪ Вариант {item[1]}'),
                id='eleventh_question_answers_checked',
                item_id_getter=operator.itemgetter(1),
                items="question_answers",
                on_state_changed=radio_question_answers_checked,
            )),
        base_row_buttons,
        confirm_stage_row_buttons,
        result_row_button,
    ),
    state=HpSeventhLessonDialog.eleventh_question,
    getter=question_answers
    )



async def confirm_answers_getter(dialog_manager: DialogManager, **kwargs):
    lesson_answers = dialog_manager.dialog_data.get('answers', {})
    message = format_progress(lesson_answers, total_questions=len(questions))
    dialog_manager.dialog_data['confirm_stage'] = True
    return {'message': message,
            'dont_first_question': True,
            'dont_last_question': False,
            'confirm_stage': True
            }

confirm_answers = Window(
    Format(text='{message}'),
    Group(
        confirm_stage_row_buttons,
        result_row_button
    ),
    state = HpSeventhLessonDialog.confirm_answers,
    getter=confirm_answers_getter
)

async def result_getter(dialog_manager: DialogManager, **kwargs):
    amo_api: AmoCRMWrapper = dialog_manager.middleware_data['amo_api']
    session: AsyncSession = dialog_manager.middleware_data['session']
    status_fields: dict = dialog_manager.middleware_data['amo_fields'].get('statuses')
    pipelines: dict = dialog_manager.middleware_data['amo_fields'].get('pipelines')
    tg_id = dialog_manager.event.from_user.id
    lesson_id = dialog_manager.start_data.get('lesson_id')
    lesson_result = dialog_manager.dialog_data.get('answers', {})

    checking = checking_result(answers=lesson_result, total_questions=len(questions))
    score = checking.get('score')
    compleat = checking.get('passed')
    result = format_results(lesson_result, total_questions=len(questions))

    logger.info(
        f'Запущена проверка результатов седьмого урока keyway. Пользователь tg_id {tg_id}. Результат проверки: баллов - {score}')

    lesson = None
    user = None
    if lesson_id is not None:
        lesson_result = await session.execute(
            select(LessonResult)
            .options(selectinload(LessonResult.user))
            .where(LessonResult.id == lesson_id)
        )
        lesson = lesson_result.scalar_one_or_none()
        lesson.score = score
        lesson.compleat = compleat
        lesson.completed_at = datetime.datetime.utcnow()
        if lesson is not None:
            user = lesson.user

        await session.commit()
        await session.refresh(lesson)
        await session.refresh(user)

        # Отправляем примечание в сделку с обучением
        amo_api.add_new_note_to_lead(lead_id=user.amo_deal_id, text=f'Результаты урока №7: {result}')

        user_lead_id = user.amo_deal_id
        status_id_in_amo = amo_api.get_lead_by_id(lead_id=user_lead_id).get('status_id')
        push_to_new_status = await check_push_to_new_status(lesson_key='compleat_lesson_7',
                                                      lead_status=status_id_in_amo)


        # Перемещаем сделку далее по воронке обучения, если успешно. В сделку записываем примечание с результатами
        if compleat and push_to_new_status:
            amo_api.push_lead_to_status(pipeline_id=pipelines.get('hite_pro_education'),
                                        status_id=status_fields.get('compleat_lesson_7'),
                                        lead_id=str(user.amo_deal_id))
    return {'result': result,
            'compleat_edu': compleat,
            'url_tg': urls_to_messanger.get('tg'),
            'url_wa': urls_to_messanger.get('whatsapp'),
            'url_max': urls_to_messanger.get('max'),}

result = Window(
    Const(text='Ваши результаты прохождения седьмого урока:'),
    Format(text="{result}"),
    Column(
        Cancel(Const('В главное меню'), id='cancel', show_mode=ShowMode.SEND),
    ),
    state=HpSeventhLessonDialog.result_seventh_lesson,
    getter=result_getter,
)

hp_seventh_lesson_dialog = Dialog(vebinar_1, first_question, second_question, third_question, fourth_question,
                                    fifth_question, sixth_question, seventh_question, eighth_question, ninth_question,
                                  tenth_question, eleventh_question, confirm_answers, result)