"""update user model with hashed_password and role

Revision ID: 2ec5ab266184
Revises: 4d66e61222f5
Create Date: 2025-10-25 00:24:37.734517

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ec5ab266184'
down_revision: Union[str, Sequence[str], None] = '4d66e61222f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
