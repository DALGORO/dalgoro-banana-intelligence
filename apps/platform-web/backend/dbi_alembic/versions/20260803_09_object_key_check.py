"""Corrige la validación PostgreSQL de claves de objeto DBI.

Revision ID: dbi_0009_object_key_check
Revises: dbi_0008_scope_hierarchy
Create Date: 2026-08-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "dbi_0009_object_key_check"
down_revision: Union[str, Sequence[str], None] = "dbi_0008_scope_hierarchy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OBJECT_KEY_CHECK = (
    "object_key ~ '^[A-Za-z0-9][A-Za-z0-9._/-]*$' "
    "AND object_key !~ '(^|/)\\.{1,2}(/|$)' "
    "AND object_key NOT LIKE '%//%'"
)
LEGACY_OBJECT_KEY_CHECK = (
    "object_key ~ '^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$' "
    "AND object_key !~ '(^|/)\\.{1,2}(/|$)' "
    "AND object_key NOT LIKE '%//%'"
)
OBJECT_KEY_CONSTRAINTS = (
    (
        "dbi_analysis_input_assets",
        "ck_dbi_analysis_input_assets_object_key",
    ),
    (
        "dbi_analysis_artifacts",
        "ck_dbi_analysis_artifacts_object_key",
    ),
)


def _replace_object_key_checks(condition: str) -> None:
    """Sustituye las dos restricciones conservando sus nombres canónicos."""

    for table_name, constraint_name in OBJECT_KEY_CONSTRAINTS:
        op.drop_constraint(
            constraint_name,
            table_name,
            type_="check",
        )
        op.create_check_constraint(
            constraint_name,
            table_name,
            condition,
        )


def upgrade() -> None:
    """Elimina el límite regex inválido y conserva VARCHAR(512) como máximo."""

    _replace_object_key_checks(OBJECT_KEY_CHECK)


def downgrade() -> None:
    """Restaura exactamente las restricciones de la revisión anterior."""

    _replace_object_key_checks(LEGACY_OBJECT_KEY_CHECK)
