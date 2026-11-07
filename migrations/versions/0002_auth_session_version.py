"""Add session revocation counter without rebuilding the users table.

Revision ID: 0002_auth
Revises: 0001_p0
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_auth"
down_revision = "0001_p0"
branch_labels = None
depends_on = None


def upgrade():
    # ADD COLUMN giữ nguyên ID, password_hash và mọi FK từ dữ liệu bước 2.
    op.add_column("users", sa.Column("auth_version", sa.Integer(), server_default="1", nullable=False))


def downgrade():
    # SQLite đi kèm Python 3.12 hỗ trợ DROP COLUMN; không rebuild bảng cha.
    op.drop_column("users", "auth_version")
