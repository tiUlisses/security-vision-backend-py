import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

logger = logging.getLogger("rtls.presence_rollup")


ROLLUP_SQL = """
INSERT INTO presence_daily_usage (
    tag_id,
    device_id,
    day,
    total_dwell_seconds,
    sessions_count,
    samples_count
)
SELECT
    tag_id,
    device_id,
    DATE(started_at) AS day,
    SUM(duration_seconds) AS total_dwell_seconds,
    COUNT(*) AS sessions_count,
    SUM(samples_count) AS samples_count
FROM presence_sessions
WHERE ended_at < :cutoff
GROUP BY tag_id, device_id, DATE(started_at)
ON CONFLICT (tag_id, device_id, day)
DO UPDATE SET
    total_dwell_seconds = EXCLUDED.total_dwell_seconds,
    sessions_count = EXCLUDED.sessions_count,
    samples_count = EXCLUDED.samples_count;
"""

PURGE_SQL = """
DELETE FROM collection_logs
WHERE created_at < :cutoff;
"""


async def rollup_and_purge(*, retention_days: int) -> int | None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    logger.info(
        "Presence rollup starting (retention_days=%s cutoff=%s)",
        retention_days,
        cutoff.isoformat(),
    )

    async with AsyncSessionLocal() as session:
        await session.execute(text(ROLLUP_SQL), {"cutoff": cutoff})
        purge_result = await session.execute(text(PURGE_SQL), {"cutoff": cutoff})
        await session.commit()

    purged = getattr(purge_result, "rowcount", None)
    logger.info("Presence rollup done (purged_collection_logs=%s)", purged)
    return purged


async def run_rollup_loop(*, retention_days: int, interval_minutes: int) -> None:
    interval_seconds = max(interval_minutes, 1) * 60
    logger.info(
        "Presence rollup loop enabled (interval_minutes=%s retention_days=%s)",
        interval_minutes,
        retention_days,
    )
    while True:
        try:
            await rollup_and_purge(retention_days=retention_days)
        except Exception:
            logger.exception("Presence rollup failed")
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Presence rollup loop cancelled")
            raise
