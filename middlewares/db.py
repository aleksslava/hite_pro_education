from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from db import async_session_factory


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        async with async_session_factory() as session:
            data["session"] = session
            return await handler(event, data)
