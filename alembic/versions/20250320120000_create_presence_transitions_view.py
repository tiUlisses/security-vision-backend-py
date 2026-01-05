"""create presence_transitions view

Revision ID: 20250320120000
Revises: 20250314120000
Create Date: 2025-03-20 12:00:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20250320120000"
down_revision = "20250314120000"
branch_labels = None
depends_on = None

VIEW_SQL = """
CREATE OR REPLACE VIEW presence_transitions AS
WITH ordered AS (
    SELECT
        id AS session_id,
        tag_id,
        device_id,
        started_at,
        ended_at,
        LAG(id) OVER (
            PARTITION BY tag_id
            ORDER BY started_at, id
        ) AS previous_session_id,
        LAG(device_id) OVER (
            PARTITION BY tag_id
            ORDER BY started_at, id
        ) AS previous_device_id,
        LAG(ended_at) OVER (
            PARTITION BY tag_id
            ORDER BY started_at, id
        ) AS previous_ended_at,
        LEAD(id) OVER (
            PARTITION BY tag_id
            ORDER BY started_at, id
        ) AS next_session_id,
        LEAD(device_id) OVER (
            PARTITION BY tag_id
            ORDER BY started_at, id
        ) AS next_device_id,
        LEAD(started_at) OVER (
            PARTITION BY tag_id
            ORDER BY started_at, id
        ) AS next_started_at
    FROM presence_sessions
)
SELECT
    session_id AS id,
    tag_id,
    previous_session_id AS from_session_id,
    session_id AS to_session_id,
    previous_device_id AS from_device_id,
    device_id AS to_device_id,
    previous_ended_at AS transition_start_at,
    started_at AS transition_end_at,
    GREATEST(
        EXTRACT(EPOCH FROM started_at - previous_ended_at),
        0
    )::BIGINT AS transition_seconds
FROM ordered
WHERE previous_session_id IS NOT NULL;
"""


def upgrade() -> None:
    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS presence_transitions")
