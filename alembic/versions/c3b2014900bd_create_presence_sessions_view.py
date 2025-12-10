"""create presence_sessions view

Revision ID: c3b2014900bd
Revises: 
Create Date: 2025-11-21 15:39:18.866593

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3b2014900bd'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW presence_sessions AS
        WITH logs AS (
            SELECT
                id,
                device_id,
                tag_id,
                created_at,
                LAG(created_at) OVER (
                    PARTITION BY tag_id, device_id
                    ORDER BY created_at
                ) AS prev_created_at
            FROM collection_logs
        ),
        marked AS (
            SELECT
                *,
                CASE
                    WHEN prev_created_at IS NULL
                         OR created_at - prev_created_at > INTERVAL '60 seconds'
                    THEN 1
                    ELSE 0
                END AS is_new_session
            FROM logs
        ),
        sessioned AS (
            SELECT
                *,
                SUM(is_new_session) OVER (
                    PARTITION BY tag_id, device_id
                    ORDER BY created_at
                ) AS session_seq
            FROM marked
        )
        SELECT
            MIN(id) AS id,
            device_id,
            tag_id,
            MIN(created_at) AS started_at,
            MAX(created_at) AS ended_at,
            EXTRACT(EPOCH FROM (MAX(created_at) - MIN(created_at)))::BIGINT
                AS duration_seconds,
            COUNT(*) AS samples_count
        FROM sessioned
        GROUP BY device_id, tag_id, session_seq;
        """
    )



def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS presence_sessions;")
