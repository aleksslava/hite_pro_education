from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
import re

import pytest

from db.models import Broadcast, BroadcastButton, BroadcastDelivery, BroadcastRecipient
from web_admin.service import BroadcastService
from web_admin.max_client import MaxServiceUnavailable


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
    assert "/tg_education/admin" in paths
    assert "/tg_education/admin/new" in paths
    assert "/tg_education/admin/preview" in paths


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
            "/tg_education/admin/login",
            data={"password": "password"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        editor = client.get("/tg_education/admin/new")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', editor.text).group(1)
        invalid = client.post(
            "/tg_education/admin/preview",
            data={
                "csrf_token": csrf,
                "message": "<script>alert(1)</script>",
                "send_telegram": "1",
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


def test_web_editor_creates_dual_channel_draft(tmp_path) -> None:
    from datetime import datetime, timezone

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.middleware.sessions import SessionMiddleware

    from config.config import AdminWebConfig
    from tests.test_web_admin_validation import make_xlsx
    from web_admin.auth import LoginRateLimiter
    from web_admin.routes import create_admin_router

    config = AdminWebConfig(
        "password",
        "session-secret" * 3,
        tmp_path,
        max_bot_api_secret="max-secret",
    )
    repository = AsyncMock()
    repository.create_draft.return_value = 1
    broadcast = Broadcast(
        id=1,
        message="Привет, [Имя]!",
        source_filename="users.xlsx",
        status="draft",
        scheduled_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        send_telegram=True,
        send_max=True,
    )
    broadcast.buttons = []
    repository.get.return_value = broadcast
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
        client.post(
            "/tg_education/admin/login",
            data={"password": "password"},
            follow_redirects=False,
        )
        editor = client.get("/tg_education/admin/new")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', editor.text).group(1)
        assert re.search(r'name="send_telegram"[^>]+checked', editor.text)
        assert re.search(r'name="send_max"[^>]+checked', editor.text)
        response = client.post(
            "/tg_education/admin/preview",
            data={
                "csrf_token": csrf,
                "message": "Привет, <tg-spoiler>[Имя]</tg-spoiler>!",
                "send_telegram": "1",
                "send_max": "1",
                "scheduled_at": "",
                "button_text": "Урок",
                "button_action": "lesson_1",
            },
            files={
                "recipients_file": (
                    "users.xlsx",
                    make_xlsx([(123, 9001, "Анна")]),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    assert response.status_code == 200
    assert "Telegram" in response.text and "MAX" in response.text
    assert repository.create_draft.await_args.kwargs["targets"] == {"telegram", "max"}


@pytest.mark.asyncio
async def test_sends_adapted_html_and_buttons_to_max(tmp_path) -> None:
    max_client = AsyncMock()
    repository = AsyncMock()
    service = BroadcastService(repository, AsyncMock(), tmp_path, max_client=max_client)
    broadcast = Broadcast(
        id=2,
        message='<b>Привет, [Имя]</b> <tg-spoiler>секрет</tg-spoiler> <a href="tg://user?id=1">профиль</a>',
        source_filename="users.xlsx",
        status="running",
        scheduled_at=None,
        created_at=None,
    )
    broadcast.buttons = [BroadcastButton(position=0, text="Урок", action_key="lesson_1")]
    broadcast.max_media_type = None
    broadcast.max_media_token = None
    recipient = BroadcastRecipient(name="Анна & Co", row_number=2, broadcast_id=2)
    delivery = BroadcastDelivery(id=11, target_id=9001, platform="max", status="sending")
    delivery.recipient = recipient

    await service._send_max(broadcast, delivery)

    max_client.send_message.assert_awaited_once_with(
        max_id=9001,
        text="<b>Привет, Анна &amp; Co</b> секрет профиль",
        buttons=[{"text": "Урок", "action_key": "lesson_1"}],
        media_type=None,
        media_token=None,
    )


@pytest.mark.asyncio
async def test_max_media_is_uploaded_once_for_multiple_deliveries(tmp_path) -> None:
    media_path = tmp_path / "photo.jpg"
    media_path.write_bytes(b"image")
    max_client = AsyncMock()
    max_client.upload_media.return_value = {"media_type": "image", "token": "token"}
    repository = AsyncMock()
    repository.mark_sending.return_value = True
    service = BroadcastService(repository, AsyncMock(), tmp_path, max_client=max_client)
    broadcast = Broadcast(
        id=3,
        message="Привет, [Имя]!",
        source_filename="users.xlsx",
        media_kind="photo",
        media_path=str(media_path),
        status="running",
        scheduled_at=None,
        created_at=None,
    )
    broadcast.buttons = []
    broadcast.max_media_type = None
    broadcast.max_media_token = None
    deliveries = []
    for delivery_id, max_id, name in ((1, 9001, "Анна"), (2, 9002, "Иван")):
        recipient = BroadcastRecipient(name=name, row_number=delivery_id + 1, broadcast_id=3)
        delivery = BroadcastDelivery(
            id=delivery_id,
            target_id=max_id,
            platform="max",
            status="pending",
        )
        delivery.recipient = recipient
        deliveries.append(delivery)

    with patch("web_admin.service.asyncio.sleep", new=AsyncMock()):
        await service._process_max(broadcast, deliveries)

    max_client.upload_media.assert_awaited_once_with(str(media_path))
    assert max_client.send_message.await_count == 2
    repository.set_max_media.assert_awaited_once_with(3, media_type="image", token="token")


@pytest.mark.asyncio
async def test_max_outage_marks_remaining_max_deliveries_without_raising(tmp_path) -> None:
    max_client = AsyncMock()
    max_client.send_message.side_effect = MaxServiceUnavailable("MAX offline")
    repository = AsyncMock()
    repository.mark_sending.return_value = True
    service = BroadcastService(repository, AsyncMock(), tmp_path, max_client=max_client)
    broadcast = Broadcast(
        id=4,
        message="Сообщение",
        source_filename="users.xlsx",
        status="running",
        scheduled_at=None,
        created_at=None,
    )
    broadcast.buttons = []
    broadcast.max_media_type = None
    broadcast.max_media_token = None
    delivery = BroadcastDelivery(id=1, target_id=9001, platform="max", status="pending")
    delivery.recipient = BroadcastRecipient(name="Анна", row_number=2, broadcast_id=4)

    await service._process_max(broadcast, [delivery])

    repository.mark_result.assert_awaited_once_with(1, success=False, error="MAX offline")
    repository.fail_pending_platform.assert_awaited_once_with(4, "max", "MAX offline")
