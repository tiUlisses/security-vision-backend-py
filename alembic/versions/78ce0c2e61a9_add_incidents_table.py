"""add incidents table

Revision ID: 78ce0c2e61a9
Revises: c3b2014900bd
Create Date: 2025-12-09 18:13:19.467151

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '78ce0c2e61a9'
down_revision = 'c3b2014900bd'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "device_id",
            sa.Integer,
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "device_event_id",
            sa.Integer,
            sa.ForeignKey("device_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "kind",
            sa.String(length=64),
            nullable=False,
            server_default="CAMERA_ISSUE",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column(
            "severity",
            sa.String(length=32),
            nullable=False,
            server_default="MEDIUM",
        ),
        sa.Column(
            "title",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text,
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "closed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_incidents_device_id",
        "incidents",
        ["device_id"],
    )
    op.create_index(
        "ix_incidents_device_event_id",
        "incidents",
        ["device_event_id"],
    )
    op.create_index(
        "ix_incidents_status",
        "incidents",
        ["status"],
    )
    op.create_index(
        "ix_incidents_closed_at",
        "incidents",
        ["closed_at"],
    )


def downgrade():
    op.drop_index("ix_incidents_closed_at", table_name="incidents")
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_device_event_id", table_name="incidents")
    op.drop_index("ix_incidents_device_id", table_name="incidents")
    op.drop_table("incidents")