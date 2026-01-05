"""create presence_sessions view

Revision ID: 20250314120000
Revises: 
Create Date: 2025-03-14 12:00:00.000000
"""

from alembic import op

from app.core.config import settings

# revision identifiers, used by Alembic.
revision = "20250314120000"
down_revision = None
branch_labels = None
depends_on = None


def _gap_seconds() -> int:
    return getattr(
        settings,
        "PRESENCE_SESSION_GAP_SECONDS",
        settings.POSITION_STALE_THRESHOLD_SECONDS,
    )


VIEW_SQL_TEMPLATE = """
CREATE OR REPLACE VIEW presence_sessions AS
WITH ordered AS (
    SELECT
        id,
        device_id,
        tag_id,
        created_at,
        LAG(created_at) OVER (
            PARTITION BY tag_id, device_id
            ORDER BY created_at, id
        ) AS previous_created_at
    FROM collection_logs
),
marked AS (
    SELECT
        *,
        CASE
            WHEN previous_created_at IS NULL THEN 1
            WHEN created_at - previous_created_at > INTERVAL '{gap_seconds} seconds' THEN 1
            ELSE 0
        END AS new_session
    FROM ordered
),
segmented AS (
    SELECT
        *,
        SUM(new_session) OVER (
            PARTITION BY tag_id, device_id
            ORDER BY created_at, id
            ROWS UNBOUNDED PRECEDING
        ) AS session_group
    FROM marked
)
SELECT
    MIN(id) AS id,
    device_id,
    tag_id,
    MIN(created_at) AS started_at,
    MAX(created_at) AS ended_at,
    EXTRACT(EPOCH FROM MAX(created_at) - MIN(created_at))::BIGINT AS duration_seconds,
    COUNT(*)::INT AS samples_count
FROM segmented
GROUP BY device_id, tag_id, session_group;
"""


def upgrade() -> None:
    gap_seconds = _gap_seconds()
    op.execute(VIEW_SQL_TEMPLATE.format(gap_seconds=gap_seconds))


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS presence_sessions")
