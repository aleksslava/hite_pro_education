from io import BytesIO

import pytest
from openpyxl import Workbook

from web_admin.validation import (
    UploadValidationError,
    parse_recipients,
    render_message,
    validate_buttons,
    validate_telegram_html,
)


def make_xlsx(rows: list[tuple[object, object, object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["telegram_id", "max_id", "Имя"])
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_accepts_supported_telegram_html() -> None:
    message = (
        '<b>Важно</b> <i>сегодня</i> <a href="https://hite-pro.ru">ссылка</a>\n'
        '<blockquote expandable>Подробности</blockquote><pre><code class="language-python">x = 1</code></pre>'
    )
    visible = validate_telegram_html(message, limit=4096)
    assert "Важно" in visible
    assert "Подробности" in visible


@pytest.mark.parametrize(
    "message",
    [
        "<script>alert(1)</script>",
        '<b style="color:red">Текст</b>',
        '<a href="javascript:alert(1)">Текст</a>',
        "<b>Не закрыт",
        "<b><i>Неверно</b></i>",
        "&nbsp;",
        "2 < 3 & test",
    ],
)
def test_rejects_unsafe_or_invalid_html(message: str) -> None:
    with pytest.raises(UploadValidationError):
        validate_telegram_html(message)


def test_personalization_escapes_excel_name() -> None:
    rendered = render_message("Здравствуйте, <b>[Имя]</b>", '<img src=x onerror="alert(1)">')
    assert rendered == "Здравствуйте, <b>&lt;img src=x onerror=\"alert(1)\"&gt;</b>"
    validate_telegram_html(rendered)


def test_excel_marks_duplicates_invalid_ids_and_missing_names() -> None:
    recipients, stats = parse_recipients(
        make_xlsx([
            (123, 9001, "Анна"),
            (123, 9002, "Иван"),
            ("wrong", 9003, "Олег"),
            (456, "", ""),
        ]),
        "Привет, <b>[Имя]</b>!",
        message_limit=4096,
    )
    assert [item["status"] for item in recipients] == ["pending", "skipped", "skipped", "skipped"]
    assert stats == {"ready": 1, "skipped": 3, "duplicates": 1, "invalid": 2}


def test_excel_checks_limit_after_name_substitution() -> None:
    with pytest.raises(UploadValidationError, match="нет корректных получателей"):
        parse_recipients(
            make_xlsx([(123, 9001, "Оченьдлинноеимя")]),
            "Привет, [Имя]",
            message_limit=10,
        )


def test_button_allowlist_and_limit() -> None:
    assert validate_buttons([{"text": "Урок", "action_key": "lesson_1"}]) == [
        {"text": "Урок", "action_key": "lesson_1"}
    ]
    with pytest.raises(UploadValidationError):
        validate_buttons([{"text": "Опасно", "action_key": "admin"}])
    with pytest.raises(UploadValidationError):
        validate_buttons([{"text": str(index), "action_key": "main_menu"} for index in range(9)])
