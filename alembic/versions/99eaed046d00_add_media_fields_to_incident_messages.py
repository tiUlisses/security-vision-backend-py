"""add media fields to incident_messages

Revision ID: 99eaed046d00
Revises: 567585856ab6
Create Date: 2025-12-10 09:52:54.209773

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '99eaed046d00'
down_revision = '567585856ab6'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column(
        "incident_messages",
        sa.Column("media_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "incident_messages",
        sa.Column("media_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "incident_messages",
        sa.Column("media_thumb_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "incident_messages",
        sa.Column("media_name", sa.String(length=255), nullable=True),
    )


def downgrade():
    op.drop_column("incident_messages", "media_name")
    op.drop_column("incident_messages", "media_thumb_url")
    op.drop_column("incident_messages", "media_url")
    op.drop_column("incident_messages", "media_type")