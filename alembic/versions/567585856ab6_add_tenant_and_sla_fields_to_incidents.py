"""add tenant and sla fields to incidents

Revision ID: 567585856ab6
Revises: 80e453e2a75a
Create Date: 2025-12-10 09:41:54.411942

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '567585856ab6'
down_revision = '80e453e2a75a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "incidents",
        sa.Column("tenant", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("sla_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_incidents_tenant", "incidents", ["tenant"])
    op.create_index("ix_incidents_due_at", "incidents", ["due_at"])
    op.create_index(
        "ix_incidents_status_severity_created_at",
        "incidents",
        ["status", "severity", "created_at"],
    )
    op.create_index(
        "ix_incidents_device_id_status",
        "incidents",
        ["device_id", "status"],
    )


def downgrade():
    op.drop_index("ix_incidents_device_id_status", table_name="incidents")
    op.drop_index("ix_incidents_status_severity_created_at", table_name="incidents")
    op.drop_index("ix_incidents_due_at", table_name="incidents")
    op.drop_index("ix_incidents_tenant", table_name="incidents")

    op.drop_column("incidents", "due_at")
    op.drop_column("incidents", "sla_minutes")
    op.drop_column("incidents", "tenant")