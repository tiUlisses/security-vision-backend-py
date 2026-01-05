"""create presence_daily_usage table

Revision ID: 20250315120000
Revises: 20250314120000
Create Date: 2025-03-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250315120000"
down_revision = "20250314120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "presence_daily_usage",
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("total_dwell_seconds", sa.BigInteger(), nullable=False),
        sa.Column("sessions_count", sa.Integer(), nullable=False),
        sa.Column("samples_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tag_id", "device_id", "day"),
    )
    op.create_index(
        "ix_presence_daily_usage_day",
        "presence_daily_usage",
        ["day"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_presence_daily_usage_day", table_name="presence_daily_usage")
    op.drop_table("presence_daily_usage")
