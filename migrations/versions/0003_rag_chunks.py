"""Chỉ mục RAG và nhật ký lượt gọi embedding. Không sửa dữ liệu người dùng."""
from alembic import op
import sqlalchemy as sa

revision = "0003_rag"
down_revision = "0002_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ai_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_version_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("part", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("embedding_identity", sa.String(100), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector_blob", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["case_version_id"], ["case_versions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("case_version_id", "kind", "source_id", "part"),
        sa.CheckConstraint("kind IN ('FACT','INTENT')", name=op.f("ck_ai_chunks_kind")),
        sa.CheckConstraint("part >= 0 AND dimensions BETWEEN 1 AND 8192", name=op.f("ck_ai_chunks_dimensions")))
    op.create_index("ix_ai_chunks_case_kind", "ai_chunks", ["case_version_id", "kind"])
    with op.batch_alter_table("ai_calls") as batch:
        batch.drop_constraint(op.f("ck_ai_calls_stage"), type_="check")
        batch.create_check_constraint(op.f("ck_ai_calls_stage"), "stage IN ('INTENT','PATIENT','TUTOR','TOKEN_COUNT','EMBEDDING')")


def downgrade():
    # Chỉ cho DB thử nghiệm còn tương thích với schema cũ.
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM ai_calls WHERE stage='EMBEDDING'")).scalar():
        raise RuntimeError("Có nhật ký embedding; không downgrade làm mất lịch sử. Dùng bản sao trước nâng cấp nếu cần.")
    with op.batch_alter_table("ai_calls") as batch:
        batch.drop_constraint(op.f("ck_ai_calls_stage"), type_="check")
        batch.create_check_constraint(op.f("ck_ai_calls_stage"), "stage IN ('INTENT','PATIENT','TUTOR','TOKEN_COUNT')")
    op.drop_index("ix_ai_chunks_case_kind", table_name="ai_chunks")
    op.drop_table("ai_chunks")
