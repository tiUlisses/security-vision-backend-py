"""add camera stream fields

Revision ID: 20250322120000
Revises: 20250320120000
Create Date: 2025-03-22 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250322120000"
down_revision = "20250320120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("rtsp_url", sa.String(length=512), nullable=True))
    op.add_column("devices", sa.Column("proxy_path", sa.String(length=255), nullable=True))
    op.add_column("devices", sa.Column("central_path", sa.String(length=255), nullable=True))
    op.add_column("devices", sa.Column("record_retention_minutes", sa.Integer(), nullable=True))
    op.add_column("devices", sa.Column("central_media_mtx_ip", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "central_media_mtx_ip")
    op.drop_column("devices", "record_retention_minutes")
    op.drop_column("devices", "central_path")
    op.drop_column("devices", "proxy_path")
    op.drop_column("devices", "rtsp_url")
