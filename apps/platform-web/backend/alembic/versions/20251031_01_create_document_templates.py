"""create document_templates table"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20251031_01"
down_revision = None  # ajusta según tu historial
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "document_templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, index=True),
        sa.Column("activity", sa.String(60), nullable=False, index=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("version", sa.String(20), nullable=False, server_default="1.0"),
        sa.Column("fields_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_document_templates_code_activity", "document_templates", ["code","activity"], unique=False)

def downgrade():
    op.drop_index("ix_document_templates_code_activity", table_name="document_templates")
    op.drop_table("document_templates")
