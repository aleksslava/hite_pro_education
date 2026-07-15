from unittest.mock import AsyncMock
from types import SimpleNamespace
import re

import pytest

from db.models import Broadcast, BroadcastButton, BroadcastDelivery, BroadcastRecipient
from web_admin.service import BroadcastService


@pytest.mark.asyncio
async def test_sends_personalized_html_with_action_buttons(tmp_path) -> None:
    bot = AsyncMock()
    repository = AsyncMock()
    service = BroadcastService(repository, bot, tmp_path)
    broadcast = Broadcast(
        id=1,
        message="Здравствуйте, <b>[Имя]</b>!",
        source_filename="users.xlsx",
        status="running",
        scheduled_at=None,
        created_at=None,
    )
    broadcast.buttons = [
        BroadcastButton(position=0, text="Начать урок", action_key="lesson_1"),
        BroadcastButton(position=1, text="Главное меню", action_key="main_menu"),
    ]
    recipient = BroadcastRecipient(name="Анна & Co", row_number=2, broadcast_id=1)
    delivery = BroadcastDelivery(id=10, target_id=123, platform="telegram", status="sending")
    delivery.recipient = recipient

    await service._send_telegram(broadcast, delivery)

    bot.send_message.assert_awaited_once()
    call = bot.send_message.await_args.kwargs
    assert call["text"] == "Здравствуйте, <b>Анна &amp; Co</b>!"
    assert [row[0].callback_data for row in call["reply_markup"].inline_keyboard] == [
        "broadcast:lesson_1",
        "broadcast:main_menu",
    ]


def test_admin_app_exposes_expected_routes(tmp_path) -> None:
    from aiogram import Bot

    from config.config import AdminWebConfig
    from web_admin.app import create_admin_app

    bot = Bot("123456:ABCDEF_fake_token_for_tests")
    app = create_admin_app(
        bot,
        AdminWebConfig("password", "session-secret" * 3, tmp_path),
    )
    paths = {route.path for route in app.routes}
    assert "/education/admin" in paths
    assert "/education/admin/new" in paths
    assert "/education/admin/preview" in paths


def test_web_editor_rejects_unsafe_html(tmp_path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.middleware.sessions import SessionMiddleware

    from config.config import AdminWebConfig
    from tests.test_web_admin_validation import make_xlsx
    from web_admin.auth import LoginRateLimiter
    from web_admin.routes import create_admin_router

    config = AdminWebConfig("password", "session-secret" * 3, tmp_path)
    repository = AsyncMock()
    service = SimpleNamespace(repository=repository, media_dir=tmp_path, wake=lambda: None)
    app = FastAPI()
    app.state.admin_config = config
    app.state.admin_rate_limiter = LoginRateLimiter()
    app.state.admin_service = service
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret,
        https_only=True,
        same_site="strict",
        path=config.prefix,
    )
    app.include_router(create_admin_router(config.prefix))

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/education/admin/login",
            data={"password": "password"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        editor = client.get("/education/admin/new")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', editor.text).group(1)
        invalid = client.post(
            "/education/admin/preview",
            data={
                "csrf_token": csrf,
                "message": "<script>alert(1)</script>",
                "scheduled_at": "",
                "button_text": "",
                "button_action": "main_menu",
            },
            files={
                "recipients_file": (
                    "users.xlsx",
                    make_xlsx([(123, 9001, "Анна")]),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert invalid.status_code == 422
    assert "не поддерживается Telegram" in invalid.text
