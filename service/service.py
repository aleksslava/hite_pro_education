import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import async_session_factory
from db.models import User, HpLessonResult as LessonResult
from service.questions_lexicon import lessons

logger = logging.getLogger(__name__)

def pad_right(s: str, width: int) -> str:
    # обычные пробелы иногда “съедаются”/выглядят странно в кнопках,
    # поэтому лучше NBSP (неразрывный пробел)
    return s + ("\u2800" * 50)

def format_results(answers: dict, total_questions: int) -> str:
    def q_num(q_key: str) -> int:
        return int(q_key[1:])  # 'q10' -> 10

    lines = []
    correct_cnt = 0

    for n in range(1, total_questions + 1):
        q_key = f"q{n}"

        # пропущенный вопрос = неверно
        if q_key not in answers or not isinstance(answers.get(q_key), dict) or not answers[q_key]:
            is_correct = False
        else:
            is_correct = all(answers[q_key].values())

        if is_correct:
            correct_cnt += 1

        status = "✅ Верно" if is_correct else "❌ Не верно"
        lines.append(f"Вопрос {n} - {status};")

    percent = round((correct_cnt / total_questions) * 100, 1) if total_questions else 0.0
    passed = percent > 80  # строго "более 80", как ты написал

    lines.append("")
    lines.append(f"Верных ответов: {correct_cnt}/{total_questions} ({percent}%)")
    lines.append("Урок пройден ✅" if passed else "Урок не пройден ❌")

    return "\n".join(lines)


def format_progress(answers: dict, total_questions: int) -> str:
    """
    answers: {'q1': {'вариант': True/False, ...}, ...}
    total_questions: общее число вопросов (например 23)

    Отвечен, если есть хотя бы один True.
    Пропущен, если:
      - нет ключа qN
      - или answers[qN] пустой/не dict
      - или все значения False
    """
    answered_nums = []
    missed_nums = []

    for n in range(1, total_questions + 1):
        q_key = f"q{n}"
        q_data = answers.get(q_key)

        if not isinstance(q_data, dict) or not q_data:
            missed_nums.append(n)
            continue
        else:
            answered_nums.append(n)

        # has_selection = any(bool(v) for v in q_data.values())
        # (answered_nums if has_selection else missed_nums).append(n)

    answered_cnt = len(answered_nums)
    missed_cnt = len(missed_nums)

    def fmt_nums(nums: list[int]) -> str:
        return ", ".join(map(str, nums)) if nums else "—"

    lines = [
        "🧾 Прогресс перед проверкой:",
        f"✅ Отвечено: {answered_cnt}/{total_questions}",
        f"❓ Пропущено: {missed_cnt}/{total_questions}",
        "",
        f"Пропущенные вопросы: {fmt_nums(missed_nums)}",
    ]

    # если есть пропуски — мягкий призыв
    if missed_nums:
        lines.append("")
        lines.append("Можно вернуться и ответить на пропущенные вопросы.\n"
                     "Для отправки результатов, нужно ответить на все вопросы теста!")

    return "\n".join(lines)

async def count_missed_answers(answers: dict, total_questions: int) -> int:
    answered_nums = []
    missed_nums = []

    for n in range(1, total_questions + 1):
        q_key = f"q{n}"
        q_data = answers.get(q_key)

        if not isinstance(q_data, dict) or not q_data:
            missed_nums.append(n)
        else:
            answered_nums.append(n)

        # has_selection = any(bool(v) for v in q_data.values())
        # (answered_nums if has_selection else missed_nums).append(n)

    answered_cnt = len(answered_nums)
    missed_cnt = len(missed_nums)

    return missed_cnt


# Функция обработки ответов и отправки результата
def checking_result(answers: dict, total_questions: int) -> dict:
    def q_num(q_key: str) -> int:
        return int(q_key[1:])  # 'q10' -> 10

    lines = []
    correct_cnt = 0

    for n in range(1, total_questions + 1):
        q_key = f"q{n}"

        # пропущенный вопрос = неверно
        if q_key not in answers or not isinstance(answers.get(q_key), dict) or not answers[q_key]:
            is_correct = False
        else:
            is_correct = all(answers[q_key].values())

        if is_correct:
            correct_cnt += 1


    percent = int(round((correct_cnt / total_questions) * 100, 1) if total_questions else 0.0)
    passed = percent >= 80  # строго "более 80", как ты написал


    return {
        'score': percent,
        'passed': passed,
    }


# Функция определяет результаты прохождения уроков и выдаёт наименования кнопок в зависимости от результата
async def get_lessons_buttons(user: User, session: AsyncSession) -> dict:
    lessons_access: dict[str, str|bool] = {}

    compleat_icon = '✅ '
    ready_icon = '▶️ '
    close_icon = '🔒 '

    if user is None or user.id is None:
        return {
            "lesson_1": '▶️ Первый урок',
            "lesson_2": "🔒 Второй урок",
            "lesson_3": "🔒 Третий урок",
        }

    result = await session.execute(
        select(LessonResult)
        .where(LessonResult.user_id == user.id)
    )
    lesson_results = result.scalars().all()

    # completed = {"lesson_1": False, "lesson_2": False, "lesson_3": False}
    completed = {lesson['title']: False for lesson in lessons}
    for lesson in lesson_results:
        if lesson.compleat and lesson.lesson_key in completed:
            completed[lesson.lesson_key] = True
            if all(completed.values()):
                break

    for index, lesson in enumerate(lessons):
        if index == 0:
            lessons_access[lesson['title']] = compleat_icon + lesson['descr'] if completed[lesson['title']] else ready_icon + lesson['descr']
        else:
            if completed[lesson['title']]:
                lessons_access[lesson['title']] = compleat_icon + lesson['descr']
            else:
                if completed[lessons[index-1]['title']]:
                    lessons_access[lesson['title']] = ready_icon + lesson['descr']
                else:
                    lessons_access[lesson['title']] = close_icon + lesson['descr']


    # lessons_access["lesson_1"] = '✅ Первый урок' if completed["lesson_1"] else '▶️ Первый урок'
    #
    # if completed["lesson_2"]:
    #     lessons_access["lesson_2"] = "✅ Второй урок"
    # elif completed["lesson_1"]:
    #     lessons_access["lesson_2"] = '▶️ Второй урок'
    # else:
    #     lessons_access["lesson_2"] = "🔒 Второй урок"
    #
    # if completed["lesson_3"]:
    #     lessons_access["lesson_3"] = "✅ Третий урок"
    # elif completed["lesson_2"]:
    #     lessons_access["lesson_3"] = '▶️ Третий урок'
    # else:
    #     lessons_access["lesson_3"] = "🔒 Третий урок"

    return lessons_access

async def lesson_access(user: User, session: AsyncSession, lesson_key: str) -> bool:
    if user is None or user.id is None:
        return False
    required_key = ''
    for index, lesson in enumerate(lessons):
        if lesson['title'] == lesson_key:
            required_key = lessons[index-1].get('title')
    # if lesson_key == "lesson_2":
    #     required_key = "lesson_1"
    # elif lesson_key == "lesson_3":
    #     required_key = "lesson_2"
    # else:
    #     return True

    result = await session.execute(
        select(LessonResult.id)
        .where(
            LessonResult.user_id == user.id,
            LessonResult.lesson_key == required_key,
            LessonResult.compleat.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def check_push_to_new_status(lesson_key: str, lead_status: int) -> bool:
    lead_status = int(lead_status)
    logger.info(f'Входящие lesson_key: {lesson_key}, lead_status: {lead_status}')
    statuses_list = [
        {'key':'admitted_to_training',
         'id': 47244117},
        {'key': 'authorized_in_bot',
         'id': 65758021},
        {'key': 'compleat_lesson_1',
         'id': 35444481},
        {'key': 'compleat_lesson_2',
         'id': 35444484},
        {'key': 'compleat_lesson_3',
         'id': 41608782},
        {'key': 'compleat_lesson_4',
         'id': 41608785},
        {'key': 'compleat_lesson_5',
         'id': 41608788},
        {'key': 'compleat_lesson_6',
         'id': 41608791},
        {'key': 'compleat_lesson_7',
         'id': 58699973},
        {'key': 'ready_to_exam',
         'id': 41608797},
        {'key': 'compleat_exam',
         'id': 41608800},
        {'key': 'compleat_training',
         'id': 35440800}
        ]
    lesson_index = 0
    lead_index = 0

    for index, lesson in enumerate(statuses_list):
        if lesson['key'] == lesson_key:
            lesson_index = index

        if lesson['id'] == lead_status:
            lead_index = index
    logger.info(f'Индекс lesson_key: {lesson_key}, lead_status: {lead_status}')

    if lead_index >= lesson_index:
        logger.info('Функция возвратила False')
        return False
    else:
        logger.info('Функция возвратила True')
        return True