"""add incident_messages table

Revision ID: 80e453e2a75a
Revises: 78ce0c2e61a9
Create Date: 2025-12-10 08:45:17.943117

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '80e453e2a75a'
down_revision = '78ce0c2e61a9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "incident_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "incident_id",
            sa.Integer,
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_type",
            sa.String(length=32),
            nullable=False,
            server_default="TEXT",
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_incident_messages_incident_id",
        "incident_messages",
        ["incident_id"],
    )
    op.create_index(
        "ix_incident_messages_created_at",
        "incident_messages",
        ["created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_incident_messages_created_at",
        table_name="incident_messages",
    )
    op.drop_index(
        "ix_incident_messages_incident_id",
        table_name="incident_messages",
    )
    op.drop_table("incident_messages")