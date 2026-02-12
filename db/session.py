from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.config import load_config
from db.base import Base
import db.models  # noqa: F401  # Ensures models are registered on Base


def create_engine() -> AsyncEngine:
    config = load_config()
    return create_async_engine(
        config.db.url,
        echo=False,
        pool_pre_ping=True,
    )


engine = create_engine()
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def shutdown_db() -> None:
    await engine.dispose()
