from io import BytesIO

import pytest
from openpyxl import Workbook

from web_admin.validation import (
    UploadValidationError,
    parse_recipients,
    render_message,
    adapt_telegram_html_for_max,
    validate_buttons,
    validate_telegram_html,
)


def make_xlsx(rows: list[tuple[object, ...]], *, include_amo: bool = False) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    headers = ["telegram_id", "max_id", "Имя"]
    if include_amo:
        headers.append("amo_deal_id")
    sheet.append(headers)
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
    assert {key: stats[key] for key in ("ready", "skipped", "duplicates", "invalid")} == {
        "ready": 1, "skipped": 3, "duplicates": 1, "invalid": 2
    }


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


def test_adapts_telegram_html_for_max() -> None:
    source = (
        '<strike>Старое</strike> <tg-spoiler>секрет</tg-spoiler> '
        '<blockquote expandable>цитата</blockquote> '
        '<pre><code class="language-python">x = 1</code></pre> '
        '<a href="tg://user?id=42">профиль</a> '
        '<a href="https://hite-pro.ru">сайт</a>'
    )
    assert adapt_telegram_html_for_max(source) == (
        '<s>Старое</s> секрет <blockquote>цитата</blockquote> '
        '<pre><code>x = 1</code></pre> профиль '
        '<a href="https://hite-pro.ru">сайт</a>'
    )


def test_excel_validates_platforms_independently() -> None:
    recipients, stats = parse_recipients(
        make_xlsx([
            (123, 9001, "Анна"),
            (123, 9002, "Иван"),
            ("", 9003, "Олег"),
            (456, 9002, "Мария"),
        ]),
        "Привет, [Имя]!",
        message_limit=4096,
        targets={"telegram", "max"},
    )
    assert [item["deliveries"]["telegram"]["status"] for item in recipients] == [
        "pending", "skipped", "skipped", "pending"
    ]
    assert [item["deliveries"]["max"]["status"] for item in recipients] == [
        "pending", "pending", "pending", "skipped"
    ]
    assert stats["platforms"]["telegram"]["ready"] == 2
    assert stats["platforms"]["max"]["ready"] == 3


def test_excel_allows_max_only_without_telegram_id() -> None:
    recipients, stats = parse_recipients(
        make_xlsx([("", 9001, "Анна")]),
        "Привет, [Имя]!",
        message_limit=4096,
        targets={"max"},
    )
    assert recipients[0]["deliveries"]["max"]["status"] == "pending"
    assert stats["ready"] == 1


def test_excel_resolves_both_ids_by_amo_deal_id() -> None:
    recipients, stats = parse_recipients(
        make_xlsx([("", "", "Анна", 501)], include_amo=True),
        "Привет, [Имя]!",
        message_limit=4096,
        targets={"telegram", "max"},
        amo_users={501: [{"telegram_id": 123, "max_id": 9001}]},
    )
    recipient = recipients[0]
    assert recipient["amo_deal_id"] == 501
    assert (recipient["telegram_id"], recipient["max_id"]) == (123, 9001)
    assert recipient["deliveries"]["telegram"]["status"] == "pending"
    assert recipient["deliveries"]["max"]["status"] == "pending"
    assert stats["ready"] == 2


def test_excel_marks_missing_database_platform_id_as_skipped() -> None:
    recipients, stats = parse_recipients(
        make_xlsx([("", "", "Анна", 502)], include_amo=True),
        "Привет!",
        message_limit=4096,
        targets={"telegram", "max"},
        amo_users={502: [{"telegram_id": 124, "max_id": None}]},
    )
    assert recipients[0]["deliveries"]["telegram"]["status"] == "pending"
    assert recipients[0]["deliveries"]["max"]["status"] == "skipped"
    assert "max_user_id" in recipients[0]["deliveries"]["max"]["error"]
    assert stats["ready"] == 1


@pytest.mark.parametrize(
    ("amo_users", "error_text"),
    [
        ({}, "не найден"),
        (
            {503: [{"telegram_id": 125, "max_id": None}, {"telegram_id": 126, "max_id": None}]},
            "несколько пользователей",
        ),
    ],
)
def test_excel_skips_missing_or_ambiguous_amo_deal(
    amo_users: dict[int, list[dict[str, int | None]]],
    error_text: str,
) -> None:
    recipients, _ = parse_recipients(
        make_xlsx([
            (777, "", "Рабочая строка", ""),
            ("", "", "Анна", 503),
        ], include_amo=True),
        "Привет!",
        message_limit=4096,
        amo_users=amo_users,
    )
    assert recipients[1]["status"] == "skipped"
    assert error_text in recipients[1]["error"]


def test_direct_id_disables_amo_fallback_even_when_invalid() -> None:
    recipients, _ = parse_recipients(
        make_xlsx([
            (777, "", "Рабочая строка", ""),
            ("wrong", "", "Анна", 504),
        ], include_amo=True),
        "Привет!",
        message_limit=4096,
        amo_users={504: [{"telegram_id": 128, "max_id": 9004}]},
    )
    assert recipients[1]["telegram_id"] is None
    assert recipients[1]["error"] == "Некорректный telegram_id"


def test_invalid_amo_deal_id_is_skipped() -> None:
    recipients, _ = parse_recipients(
        make_xlsx([
            (777, "", "Рабочая строка", ""),
            ("", "", "Анна", "not-a-number"),
        ], include_amo=True),
        "Привет!",
        message_limit=4096,
    )
    assert recipients[1]["status"] == "skipped"
    assert recipients[1]["error"] == "Некорректный amo_deal_id"


def test_amo_resolution_respects_selected_channels() -> None:
    recipients, stats = parse_recipients(
        make_xlsx([("", "", "Анна", 506)], include_amo=True),
        "Привет!",
        message_limit=4096,
        targets={"max"},
        amo_users={506: [{"telegram_id": 131, "max_id": 9011}]},
    )
    assert set(recipients[0]["deliveries"]) == {"max"}
    assert recipients[0]["deliveries"]["max"]["status"] == "pending"
    assert stats["ready"] == 1


def test_duplicates_are_checked_after_amo_resolution() -> None:
    recipients, stats = parse_recipients(
        make_xlsx([
            (130, 9010, "Прямой", ""),
            ("", "", "По сделке", 505),
        ], include_amo=True),
        "Привет!",
        message_limit=4096,
        targets={"telegram", "max"},
        amo_users={505: [{"telegram_id": 130, "max_id": 9010}]},
    )
    assert recipients[1]["deliveries"]["telegram"]["error"] == "Повторный telegram_id"
    assert recipients[1]["deliveries"]["max"]["error"] == "Повторный max_id"
    assert stats["duplicates"] == 2
