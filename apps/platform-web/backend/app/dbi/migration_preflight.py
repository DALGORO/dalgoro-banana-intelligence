"""Preflight de solo lectura para migraciones DBI controladas.

Este módulo no crea motores ni administra credenciales. Recibe una conexión ya
abierta por el operador y ejecuta únicamente consultas ``SELECT`` para validar
el destino antes de cualquier posible ``apply``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Collection

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.dbi.migration_control import (
    DBIMigrationControlError,
    DBIMigrationTarget,
)

IDENTITY_SQL = """
SELECT
  current_database() AS database_name,
  current_user AS username,
  session_user AS session_username,
  current_setting('search_path') AS search_path
"""

ROLE_SQL = """
SELECT
  role.rolsuper,
  role.rolcreatedb,
  role.rolcreaterole,
  role.rolreplication,
  role.rolbypassrls,
  EXISTS (
    SELECT 1
    FROM pg_auth_members membership
    WHERE membership.member = role.oid
  ) AS has_role_memberships,
  EXISTS (
    SELECT 1
    FROM pg_database database_entry
    WHERE database_entry.datname = current_database()
      AND database_entry.datdba = role.oid
  ) AS owns_database,
  EXISTS (
    SELECT 1
    FROM pg_namespace namespace_entry
    WHERE namespace_entry.nspname = 'dbi'
      AND namespace_entry.nspowner = role.oid
  ) AS owns_dbi_schema
FROM pg_roles role
WHERE role.rolname = current_user
"""

CAPABILITIES_SQL = """
SELECT
  EXISTS (
    SELECT 1 FROM pg_extension WHERE extname = 'postgis'
  ) AS postgis_available,
  EXISTS (
    SELECT 1 FROM pg_namespace WHERE nspname = 'dbi'
  ) AS dbi_schema_available,
  to_regclass('dbi.alembic_version_dbi') IS NOT NULL AS version_table_available
"""

REVISION_SQL = "SELECT version_num FROM dbi.alembic_version_dbi"

READ_ONLY_STATEMENTS = (
    IDENTITY_SQL,
    ROLE_SQL,
    CAPABILITIES_SQL,
    REVISION_SQL,
)

FORBIDDEN_ROLE_CAPABILITIES = (
    "rolsuper",
    "rolcreatedb",
    "rolcreaterole",
    "rolreplication",
    "rolbypassrls",
    "has_role_memberships",
    "owns_database",
    "owns_dbi_schema",
)


@dataclass(frozen=True)
class DBIMigrationPreflight:
    """Evidencia segura obtenida mediante consultas de solo lectura."""

    target: DBIMigrationTarget
    search_path: tuple[str, ...]
    postgis_available: bool
    dbi_schema_available: bool
    version_table_available: bool
    current_revision: str | None
    head_revision: str

    @property
    def database_is_empty(self) -> bool:
        """Indica que Alembic todavía no creó su tabla de versión DBI."""

        return not self.version_table_available

    @property
    def is_at_head(self) -> bool:
        """Indica que la revisión actual coincide con la cabeza aprobada."""

        return self.current_revision == self.head_revision


def _normalize_search_path(raw: str) -> tuple[str, ...]:
    return tuple(
        item.strip().strip('"')
        for item in raw.split(",")
        if item.strip()
    )


def _validate_read_only_contract() -> None:
    for statement in READ_ONLY_STATEMENTS:
        if not statement.lstrip().upper().startswith("SELECT"):
            raise DBIMigrationControlError(
                "El preflight contiene una sentencia que no es de solo lectura."
            )


def run_migration_preflight(
    connection: Connection,
    *,
    target: DBIMigrationTarget,
    known_revisions: Collection[str],
    head_revision: str,
) -> DBIMigrationPreflight:
    """Valida base, rol, PostGIS, esquema e historial mediante ``SELECT``.

    Se permite una base vacía sin tabla de versión. Cuando la tabla existe, debe
    contener exactamente una revisión conocida del linaje DBI.
    """

    _validate_read_only_contract()

    identity = connection.execute(text(IDENTITY_SQL)).mappings().one()
    if identity["database_name"] != target.database_name:
        raise DBIMigrationControlError(
            "La conexión abierta apunta a una base DBI distinta de la autorizada."
        )
    if (
        identity["username"] != target.expected_migrator_role
        or identity["session_username"] != target.expected_migrator_role
    ):
        raise DBIMigrationControlError(
            "La conexión debe autenticar y usar directamente el rol migrador autorizado."
        )

    search_path = _normalize_search_path(str(identity["search_path"]))
    if search_path[:2] != ("dbi", "public"):
        raise DBIMigrationControlError(
            "El search_path del migrador debe comenzar con dbi, public."
        )

    role = connection.execute(text(ROLE_SQL)).mappings().one_or_none()
    if role is None:
        raise DBIMigrationControlError(
            "El rol migrador actual no existe en pg_roles."
        )
    if any(
        bool(role.get(field, False))
        for field in FORBIDDEN_ROLE_CAPABILITIES
    ):
        raise DBIMigrationControlError(
            "El rol migrador posee privilegios, membresías o propiedad no autorizados."
        )

    capabilities = connection.execute(text(CAPABILITIES_SQL)).mappings().one()
    postgis_available = bool(capabilities["postgis_available"])
    dbi_schema_available = bool(capabilities["dbi_schema_available"])
    version_table_available = bool(capabilities["version_table_available"])

    if not postgis_available:
        raise DBIMigrationControlError(
            "PostGIS debe estar instalado antes de aplicar migraciones DBI."
        )
    if not dbi_schema_available:
        raise DBIMigrationControlError(
            "El esquema dbi debe existir antes de aplicar migraciones."
        )

    current_revision: str | None = None
    if version_table_available:
        revisions = connection.execute(text(REVISION_SQL)).scalars().all()
        if len(revisions) != 1:
            raise DBIMigrationControlError(
                "La tabla de versión DBI debe contener exactamente una revisión."
            )
        current_revision = str(revisions[0])
        if current_revision not in set(known_revisions):
            raise DBIMigrationControlError(
                "La revisión DBI actual no pertenece al linaje aprobado."
            )

    return DBIMigrationPreflight(
        target=target,
        search_path=search_path,
        postgis_available=postgis_available,
        dbi_schema_available=dbi_schema_available,
        version_table_available=version_table_available,
        current_revision=current_revision,
        head_revision=head_revision,
    )
