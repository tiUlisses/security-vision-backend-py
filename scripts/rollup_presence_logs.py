# scripts/rollup_presence_logs.py
import argparse
import asyncio

from app.core.config import settings
from app.services.presence_rollup import rollup_and_purge


async def rollup_and_purge_script(*, retention_days: int) -> None:
    purged = await rollup_and_purge(retention_days=retention_days)
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
    asyncio.run(rollup_and_purge_script(retention_days=args.retention_days))


if __name__ == "__main__":
    main()
