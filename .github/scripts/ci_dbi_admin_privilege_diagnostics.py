"""Diagnóstico seguro de privilegios del rol API DBI en CI efímera.

Solo informa nombres de roles, columnas y tipos de privilegio. No imprime URLs,
credenciales, valores de datos ni contenido de tablas.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from ci_dbi_admin_integration import (  # noqa: E402
    API_ROLE,
    _admin_connect,
    _provision_api_role,
    _require_ci_scope,
)


def main() -> None:
    _require_ci_scope()
    _provision_api_role()

    with _admin_connect() as connection:
        with connection.cursor() as cursor:
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
            effective_update_columns = [row[0] for row in cursor.fetchall()]

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
            direct_column_grants = [
                {
                    "column": row[0],
                    "privilege": row[1],
                    "grantor": row[2],
                }
                for row in cursor.fetchall()
            ]

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
            direct_table_grants = [
                {"privilege": row[0], "grantor": row[1]}
                for row in cursor.fetchall()
            ]

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
            inherited_roles = [row[0] for row in cursor.fetchall()]

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

    evidence = {
        "api_role": API_ROLE,
        "table_owner": table_owner,
        "table_update": table_update,
        "effective_update_columns": effective_update_columns,
        "direct_column_grants": direct_column_grants,
        "direct_table_grants": direct_table_grants,
        "inherited_roles": inherited_roles,
    }
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main()
