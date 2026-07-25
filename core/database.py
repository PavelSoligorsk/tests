from __future__ import annotations

import os
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL not set. Provide a PostgreSQL URL in the environment.\n"
        'Example: DATABASE_URL="postgresql://user:pass@localhost:5432/education_platform"\n'
        "You can set it in .env file or via export."
    )


def _to_async_url(url: str) -> str:
    """Convert a sync database URL to the async driver equivalent."""
    if "+asyncpg" in url or "+aiosqlite" in url:
        return url
    if url.startswith("sqlite"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


ASYNC_DATABASE_URL = _to_async_url(DATABASE_URL)

engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,
    future=True,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async dependency that yields an SQLAlchemy AsyncSession."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
