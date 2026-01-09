"""add person phone user type

Revision ID: 20250324120000
Revises: 20250323120000
Create Date: 2025-03-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250324120000"
down_revision = "20250323120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("people", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("people", sa.Column("user_type", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("people", "user_type")
    op.drop_column("people", "phone")
