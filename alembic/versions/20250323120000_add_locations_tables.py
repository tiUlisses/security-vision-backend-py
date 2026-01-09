"""add locations tables

Revision ID: 20250323120000
Revises: 20250322120000
Create Date: 2025-03-23 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250323120000"
down_revision = "20250322120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_locations_id", "locations", ["id"])
    op.create_table(
        "location_floors",
        sa.Column(
            "location_id",
            sa.Integer(),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "floor_id",
            sa.Integer(),
            sa.ForeignKey("floors.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "location_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "location_id",
            sa.Integer(),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("avaliable_days", sa.String(length=64), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column(
            "validate",
            sa.Boolean(),
            server_default=sa.text("TRUE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_location_rules_id", "location_rules", ["id"])
    op.create_index("ix_location_rules_location_id", "location_rules", ["location_id"])


def downgrade() -> None:
    op.drop_index("ix_location_rules_location_id", table_name="location_rules")
    op.drop_index("ix_location_rules_id", table_name="location_rules")
    op.drop_table("location_rules")
    op.drop_table("location_floors")
    op.drop_index("ix_locations_id", table_name="locations")
    op.drop_table("locations")
