# scripts/rollup_presence_logs.py
import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.config import settings
from app.db.session import AsyncSessionLocal


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


async def rollup_and_purge(*, retention_days: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    print(f"[presence-rollup] cutoff={cutoff.isoformat()} retention_days={retention_days}")

    async with AsyncSessionLocal() as session:
        await session.execute(text(ROLLUP_SQL), {"cutoff": cutoff})
        purge_result = await session.execute(text(PURGE_SQL), {"cutoff": cutoff})
        await session.commit()

    purged = getattr(purge_result, "rowcount", None)
    print(f"[presence-rollup] purged_collection_logs={purged}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rollup presence logs and purge old data.")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=settings.PRESENCE_LOG_RETENTION_DAYS,
        help="Dias de retenção para collection_logs antes do rollup/purge.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(rollup_and_purge(retention_days=args.retention_days))


if __name__ == "__main__":
    main()
