from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260411_01"
down_revision = "20251031_01"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "documents",
        "storage_path",
        existing_type=sa.String(length=512),
        nullable=True,
    )


def downgrade():
    op.alter_column(
        "documents",
        "storage_path",
        existing_type=sa.String(length=512),
        nullable=False,
    )