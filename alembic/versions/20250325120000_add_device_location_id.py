"""add device location id

Revision ID: 20250325120000
Revises: 20250324120000
Create Date: 2025-03-25 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250325120000"
down_revision = "20250324120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("location_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_devices_location_id", "devices", ["location_id"])
    op.create_foreign_key(
        "fk_devices_location_id_locations",
        "devices",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_devices_location_id_locations", "devices", type_="foreignkey")
    op.drop_index("ix_devices_location_id", table_name="devices")
    op.drop_column("devices", "location_id")
