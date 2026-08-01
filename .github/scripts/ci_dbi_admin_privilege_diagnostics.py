"""Contrato cerrado de privilegios del rol API DBI en CI efímera.

Normaliza únicamente la ACL de actualización de membresías y exige que el rol
pueda modificar ``status`` y ``updated_at``, sin privilegio de tabla, herencia ni
otras columnas. La evidencia solo contiene nombres de roles, columnas y tipos de
privilegio; nunca URLs, credenciales o datos de negocio.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from ci_dbi_admin_integration import (  # noqa: E402
    API_ROLE,
    _admin_connect,
    _provision_api_role,
    _require_ci_scope,
)

EXPECTED_UPDATE_COLUMNS = ("status", "updated_at")


def harden_and_validate_api_role() -> dict[str, object]:
    """Revoca ACL residual, concede dos columnas y exige evidencia exacta."""

    _require_ci_scope()
    _provision_api_role()

    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "REVOKE UPDATE ON TABLE dbi.dbi_memberships FROM {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "REVOKE UPDATE "
                    "(id, principal_id, tenant_ref, status, created_at, updated_at) "
                    "ON TABLE dbi.dbi_memberships FROM {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, updated_at) "
                    "ON TABLE dbi.dbi_memberships TO {}"
                ).format(sql.Identifier(API_ROLE))
            )

            cursor.execute(
                """
                SELECT has_table_privilege(
                    %s,
                    'dbi.dbi_memberships',
                    'UPDATE'
                )
                """,
                (API_ROLE,),
            )
            table_update = bool(cursor.fetchone()[0])

            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'dbi'
                  AND table_name = 'dbi_memberships'
                  AND has_column_privilege(
                      %s,
                      'dbi.dbi_memberships',
                      column_name,
                      'UPDATE'
                  )
                ORDER BY ordinal_position
                """,
                (API_ROLE,),
            )
            effective_update_columns = tuple(
                row[0] for row in cursor.fetchall()
            )

            cursor.execute(
                """
                SELECT column_name, privilege_type, grantor
                FROM information_schema.column_privileges
                WHERE grantee = %s
                  AND table_schema = 'dbi'
                  AND table_name = 'dbi_memberships'
                  AND privilege_type = 'UPDATE'
                ORDER BY column_name, grantor
                """,
                (API_ROLE,),
            )
            direct_column_grants = tuple(cursor.fetchall())

            cursor.execute(
                """
                SELECT privilege_type, grantor
                FROM information_schema.table_privileges
                WHERE grantee = %s
                  AND table_schema = 'dbi'
                  AND table_name = 'dbi_memberships'
                ORDER BY privilege_type, grantor
                """,
                (API_ROLE,),
            )
            direct_table_grants = tuple(cursor.fetchall())

            cursor.execute(
                """
                SELECT parent.rolname
                FROM pg_auth_members AS membership
                JOIN pg_roles AS parent ON parent.oid = membership.roleid
                JOIN pg_roles AS member ON member.oid = membership.member
                WHERE member.rolname = %s
                ORDER BY parent.rolname
                """,
                (API_ROLE,),
            )
            inherited_roles = tuple(row[0] for row in cursor.fetchall())

            cursor.execute(
                """
                SELECT owner.rolname
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_roles AS owner ON owner.oid = relation.relowner
                WHERE namespace.nspname = 'dbi'
                  AND relation.relname = 'dbi_memberships'
                """
            )
            table_owner = cursor.fetchone()[0]

    direct_update_columns = tuple(
        sorted(row[0] for row in direct_column_grants)
    )
    direct_update_privileges = {
        row[1] for row in direct_column_grants
    }
    direct_table_privileges = tuple(
        sorted(row[0] for row in direct_table_grants)
    )

    if table_update:
        raise AssertionError(
            "El rol API conserva UPDATE a nivel de tabla en membresías."
        )
    if effective_update_columns != EXPECTED_UPDATE_COLUMNS:
        raise AssertionError(
            "Las columnas actualizables del rol API no son exactas. "
            f"Efectivas={effective_update_columns!r}"
        )
    if direct_update_columns != EXPECTED_UPDATE_COLUMNS:
        raise AssertionError(
            "Las concesiones UPDATE por columna no son exactas. "
            f"Directas={direct_update_columns!r}"
        )
    if direct_update_privileges != {"UPDATE"}:
        raise AssertionError(
            "La ACL por columna contiene privilegios no autorizados."
        )
    if direct_table_privileges != ("SELECT",):
        raise AssertionError(
            "La ACL de tabla de membresías no está limitada a SELECT. "
            f"Directa={direct_table_privileges!r}"
        )
    if inherited_roles:
        raise AssertionError(
            "El rol API hereda autoridad de otros roles. "
            f"Roles={inherited_roles!r}"
        )
    if table_owner == API_ROLE:
        raise AssertionError(
            "El rol API no puede ser propietario de dbi_memberships."
        )

    return {
        "api_role": API_ROLE,
        "table_owner": table_owner,
        "table_update": False,
        "effective_update_columns": list(effective_update_columns),
        "direct_table_privileges": list(direct_table_privileges),
        "inherited_roles": [],
    }


def main() -> None:
    evidence = harden_and_validate_api_role()
    print(json.dumps(evidence, sort_keys=True))
    print("ACL exacta del rol API DBI aprobada.")


if __name__ == "__main__":
    main()
