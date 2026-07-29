"""Establece la línea base independiente de migraciones DBI.

Revision ID: dbi_0001_baseline
Revises:
Create Date: 2026-07-29
"""

from typing import Sequence, Union

revision: str = "dbi_0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Registra la línea base sin crear tablas de dominio."""

    pass


def downgrade() -> None:
    """Mantiene la revisión como marcador sin operaciones destructivas."""

    pass
