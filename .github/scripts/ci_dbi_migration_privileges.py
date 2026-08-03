"""Valida privilegios efectivos del rol migrador DBI sin conexión externa."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import DBIDatabaseConfig  # noqa: E402
from app.dbi.migration_control import (  # noqa: E402
    DBIMigrationControlError,
    validate_migration_target,
)
from app.dbi.migration_preflight import (  # noqa: E402
    FORBIDDEN_ROLE_CAPABILITIES,
    IDENTITY_SQL,
    READ_ONLY_STATEMENTS,
    ROLE_SQL,
    run_migration_preflight,
)

HEAD = "dbi_0010_asset_multipart"
KNOWN_REVISIONS = {
    "dbi_0001_baseline",
    "dbi_0006_plot_boundaries",
    "dbi_0007_admin_audit",
    "dbi_0008_scope_hierarchy",
    "dbi_0009_object_key_check",
    HEAD,
}


class _Mappings:
    def __init__(self, row):
        self.row = row

    def one(self):
        assert self.row is not None
        return self.row

    def one_or_none(self):
        return self.row


class _Scalars:
    def all(self):
        return []


class _Result:
    def __init__(self, *, row=None):
        self.row = row

    def mappings(self):
        return _Mappings(self.row)

    def scalars(self):
        return _Scalars()


class _FakeConnection:
    def __init__(self, role, *, session_username="dbi_test_migrator"):
        self.role = role
        self.session_username = session_username
        self.executed = []

    def execute(self, statement):
        sql = str(statement)
        self.executed.append(sql)
        compact = " ".join(sql.lower().split())

        # ROLE_SQL también contiene current_database() para comprobar propiedad.
        # Debe reconocerse antes que la consulta de identidad.
        if "from pg_roles" in compact:
            return _Result(row=self.role)
        if "current_database() as database_name" in compact:
            return _Result(
                row={
                    "database_name": "dbi_test",
                    "username": "dbi_test_migrator",
                    "session_username": self.session_username,
                    "search_path": "dbi, public",
                }
            )
        if "from pg_extension" in compact:
            return _Result(
                row={
                    "postgis_available": True,
                    "dbi_schema_available": True,
                    "version_table_available": False,
                }
            )
        raise AssertionError(f"Consulta inesperada: {sql}")


def _target():
    config = DBIDatabaseConfig(
        environment="test",
        url=make_url(
            "postgresql+psycopg://dbi_test_migrator:placeholder@"
            "127.0.0.1:5432/dbi_test"
        ),
    )
    return validate_migration_target(config, running_in_ci=True)


def _clean_role():
    return {
        field: False
        for field in FORBIDDEN_ROLE_CAPABILITIES
    }


def _assert_rejected(role) -> None:
    try:
        run_migration_preflight(
            _FakeConnection(role),
            target=_target(),
            known_revisions=KNOWN_REVISIONS,
            head_revision=HEAD,
        )
    except DBIMigrationControlError:
        return
    raise AssertionError("El privilegio migrador no autorizado debía rechazarse.")


def validate_clean_role() -> None:
    connection = _FakeConnection(_clean_role())
    evidence = run_migration_preflight(
        connection,
        target=_target(),
        known_revisions=KNOWN_REVISIONS,
        head_revision=HEAD,
    )
    assert evidence.database_is_empty is True
    assert evidence.current_revision is None
    assert len(connection.executed) == 3


def validate_session_identity() -> None:
    connection = _FakeConnection(
        _clean_role(),
        session_username="postgres",
    )
    try:
        run_migration_preflight(
            connection,
            target=_target(),
            known_revisions=KNOWN_REVISIONS,
            head_revision=HEAD,
        )
    except DBIMigrationControlError:
        return
    raise AssertionError("Un session_user distinto del migrador debía rechazarse.")


def validate_forbidden_capabilities() -> None:
    for field in FORBIDDEN_ROLE_CAPABILITIES:
        role = _clean_role()
        role[field] = True
        _assert_rejected(role)


def validate_query_contract() -> None:
    identity = " ".join(IDENTITY_SQL.lower().split())
    normalized = " ".join(ROLE_SQL.lower().split())
    assert "session_user as session_username" in identity
    for field in FORBIDDEN_ROLE_CAPABILITIES:
        assert field in normalized
    assert "from pg_auth_members" in normalized
    assert "from pg_database" in normalized
    assert "from pg_namespace" in normalized
    assert all(
        statement.lstrip().upper().startswith("SELECT")
        for statement in READ_ONLY_STATEMENTS
    )


def main() -> None:
    validate_clean_role()
    validate_session_identity()
    validate_forbidden_capabilities()
    validate_query_contract()
    print("Privilegios efectivos del rol migrador DBI aprobados offline.")


if __name__ == "__main__":
    main()
