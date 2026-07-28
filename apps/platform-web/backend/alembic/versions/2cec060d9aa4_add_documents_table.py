# backend/alembic/versions/2cec060d9aa4_add_documents_table.py
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "2cec060d9aa4"
down_revision = None  # o la última revision real que tengas
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_documents_company_id", "documents", ["company_id"])
    op.create_index("ix_documents_kind", "documents", ["kind"])

def downgrade():
    op.drop_index("ix_documents_kind", table_name="documents")
    op.drop_index("ix_documents_company_id", table_name="documents")
    op.drop_table("documents")
