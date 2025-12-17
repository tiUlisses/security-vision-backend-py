"""add role to users

Revision ID: 67583856d231
Revises: 38c2c8e3f69c
Create Date: 2025-12-10 13:34:54.672610

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '67583856d231'
down_revision = '38c2c8e3f69c'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
            server_default="OPERATOR",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "role")