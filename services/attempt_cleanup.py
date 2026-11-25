"""Раз в сутки снимает незаконченные попытки, которые не трогали 10 дней."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import TestResult, UserAnswer

log = logging.getLogger(__name__)

STALE_DAYS = 10
INTERVAL_SECONDS = 24 * 60 * 60


async def delete_stale_incomplete_attempts(
    db: AsyncSession, *, now: datetime | None = None, days: int = STALE_DAYS,
) -> int:
    """Удаляет попытки без completed_at, если started_at старше days или пустой."""
    moment = now or datetime.utcnow()
    cutoff = moment - timedelta(days=days)
    stale_ids = select(TestResult.id).where(
        TestResult.completed_at.is_(None),
        or_(TestResult.started_at.is_(None), TestResult.started_at < cutoff),
    )
    await db.execute(delete(UserAnswer).where(UserAnswer.result_id.in_(stale_ids)))
    result = await db.execute(delete(TestResult).where(TestResult.id.in_(stale_ids)))
    await db.commit()
    return int(result.rowcount or 0)


async def stale_attempt_loop(
    session_factory: async_sessionmaker[AsyncSession], stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            async with session_factory() as db:
                removed = await delete_stale_incomplete_attempts(db)
            log.info("Удалено незаконченных попыток старше %s дней: %s", STALE_DAYS, removed)
        except Exception:
            log.exception("Не удалось удалить старые незаконченные попытки")
        try:
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue
