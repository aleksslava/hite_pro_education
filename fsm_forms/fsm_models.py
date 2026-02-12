from aiogram.filters.state import StatesGroup, State



class MainDialog(StatesGroup):
    main = State()
    # keyway_lessons = State()
    phone = State()
    process_edu = State()


class HpFirstLessonDialog(StatesGroup):
    vebinar = State()
    first_question = State()
    second_question = State()
    third_question = State()
    fourth_question = State()
    fifth_question = State()
    sixth_question = State()
    seventh_question = State()
    eighth_question = State()
    ninth_question = State()
    tenth_question = State()
    confirm_answers = State()
    result_first_lesson = State()



class HpSecondLessonDialog(StatesGroup):
    vebinar_1 = State()
    first_question = State()
    second_question = State()
    third_question = State()
    fourth_question = State()
    fifth_question = State()
    sixth_question = State()
    seventh_question = State()
    eighth_question = State()
    confirm_answers = State()
    result_second_lesson = State()




class HpThirdLessonDialog(StatesGroup):
    vebinar_1 = State()
    first_question = State()
    second_question = State()
    third_question = State()
    fourth_question = State()
    fifth_question = State()
    confirm_answers = State()
    result_third_lesson = State()

class HpFourthLessonDialog(StatesGroup):
    vebinar_1 = State()
    first_question = State()
    second_question = State()
    third_question = State()
    fourth_question = State()
    fifth_question = State()
    sixth_question = State()
    seventh_question = State()
    eighth_question = State()
    confirm_answers = State()
    result_fourth_lesson = State()

class HpFifthLessonDialog(StatesGroup):
    vebinar_1 = State()
    first_question = State()
    second_question = State()
    third_question = State()
    fourth_question = State()
    fifth_question = State()
    sixth_question = State()
    seventh_question = State()
    eighth_question = State()
    ninth_question = State()
    confirm_answers = State()
    result_fifth_lesson = State()

class HpSixthLessonDialog(StatesGroup):
    vebinar_1 = State()
    first_question = State()
    second_question = State()
    third_question = State()
    fourth_question = State()
    fifth_question = State()
    confirm_answers = State()
    sixth_question = State()
    result_sixth_lesson = State()

class HpSeventhLessonDialog(StatesGroup):
    vebinar_1 = State()
    first_question = State()
    second_question = State()
    third_question = State()
    fourth_question = State()
    fifth_question = State()
    sixth_question = State()
    seventh_question = State()
    eighth_question = State()
    ninth_question = State()
    tenth_question = State()
    eleventh_question = State()
    confirm_answers = State()
    result_seventh_lesson = State()

class HpExamLessonDialog(StatesGroup):
    vebinar_1 = State()
    first_question = State()
    second_question = State()
    third_question = State()
    fourth_question = State()
    fifth_question = State()
    confirm_answers = State()
    result_exam_lesson = State()

class AdminDialog(StatesGroup):
    admin_menu = State()
    delete_user = State()
    add_admin = State()
