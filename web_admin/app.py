from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from config.config import AdminWebConfig
from db import async_session_factory
from web_admin.auth import LoginRateLimiter
from web_admin.repository import BroadcastRepository
from web_admin.routes import create_admin_router
from web_admin.service import BroadcastService
from web_admin.max_client import MaxBroadcastClient


def create_admin_app(bot: Bot, config: AdminWebConfig) -> FastAPI:
    repository = BroadcastRepository(async_session_factory)
    max_client = (
        MaxBroadcastClient(config.max_bot_api_url, config.max_bot_api_secret)
        if config.max_enabled
        else None
    )
    service = BroadcastService(repository, bot, config.data_dir, max_client=max_client)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await service.initialize()
        service.start()
        yield
        await service.stop()

    app = FastAPI(title="HiTE PRO education admin", lifespan=lifespan)
    app.state.admin_config = config
    app.state.admin_service = service
    app.state.admin_rate_limiter = LoginRateLimiter()
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret,
        session_cookie="education_admin_session",
        max_age=12 * 60 * 60,
        path=config.prefix,
        same_site="strict",
        https_only=True,
    )
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount(f"{config.prefix}/static", StaticFiles(directory=static_dir), name="admin-static")
    app.include_router(create_admin_router(config.prefix))
    return app
