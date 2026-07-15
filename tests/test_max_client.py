from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from web_admin.max_client import MaxBroadcastClient, MaxDeliveryError


@pytest.mark.asyncio
async def test_max_client_retries_temporary_errors() -> None:
    attempts = 0

    async def send(_: web.Request) -> web.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return web.json_response({"detail": "temporary"}, status=503)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/broadcast/send", send)
    server = TestServer(app)
    await server.start_server()
    client = MaxBroadcastClient(str(server.make_url("/")), "secret")
    try:
        with patch("web_admin.max_client.asyncio.sleep", new=AsyncMock()):
            await client.send_message(
                max_id=9001,
                text="Сообщение",
                buttons=[],
                media_type=None,
                media_token=None,
            )
    finally:
        await client.close()
        await server.close()
    assert attempts == 3


@pytest.mark.asyncio
async def test_max_client_does_not_retry_permanent_error() -> None:
    attempts = 0

    async def send(_: web.Request) -> web.Response:
        nonlocal attempts
        attempts += 1
        return web.json_response({"detail": "max_send_rejected"}, status=422)

    app = web.Application()
    app.router.add_post("/broadcast/send", send)
    server = TestServer(app)
    await server.start_server()
    client = MaxBroadcastClient(str(server.make_url("/")), "secret")
    try:
        with pytest.raises(MaxDeliveryError, match="max_send_rejected"):
            await client.send_message(
                max_id=9001,
                text="Сообщение",
                buttons=[],
                media_type=None,
                media_token=None,
            )
    finally:
        await client.close()
        await server.close()
    assert attempts == 1
