"""add device users table

Revision ID: 20250326120000
Revises: 20250325120000
Create Date: 2025-03-26 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250326120000"
down_revision = "20250325120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("device_user_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
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
    op.create_index("ix_device_users_device_id", "device_users", ["device_id"])
    op.create_index("ix_device_users_person_id", "device_users", ["person_id"])
    op.create_index("ix_device_users_device_user_id", "device_users", ["device_user_id"])
    op.create_foreign_key(
        "fk_device_users_device_id_devices",
        "device_users",
        "devices",
        ["device_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_device_users_person_id_people",
        "device_users",
        "people",
        ["person_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_device_users_person_id_people", "device_users", type_="foreignkey")
    op.drop_constraint("fk_device_users_device_id_devices", "device_users", type_="foreignkey")
    op.drop_index("ix_device_users_device_user_id", table_name="device_users")
    op.drop_index("ix_device_users_person_id", table_name="device_users")
    op.drop_index("ix_device_users_device_id", table_name="device_users")
    op.drop_table("device_users")
