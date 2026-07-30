"""Valida controles, plan y preflight DBI sin conexiones externas."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import (  # noqa: E402
    DBI_DATABASE_URL_ENV_VAR,
    DBI_ENVIRONMENT_ENV_VAR,
    DBIDatabaseConfig,
)
from app.dbi.migration_control import (  # noqa: E402
    DBIMigrationControlError,
    advisory_lock_key,
    plan_fingerprint,
    require_apply_confirmation,
    validate_migration_target,
)
from app.dbi.migration_plan import generate_offline_plan  # noqa: E402
from app.dbi.migration_preflight import (  # noqa: E402
    READ_ONLY_STATEMENTS,
    run_migration_preflight,
)


class _Mappings:
    def __init__(self, row):
        self.row = row

    def one(self):
        assert self.row is not None
        return self.row

    def one_or_none(self):
        return self.row


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)


class _Result:
    def __init__(self, *, row=None, values=()):
        self.row = row
        self.values = values

    def mappings(self):
        return _Mappings(self.row)

    def scalars(self):
        return _Scalars(self.values)


class _FakeConnection:
    def __init__(
        self,
        *,
        database_name="dbi_test",
        username="dbi_test_migrator",
        search_path="dbi, public",
        role=None,
        capabilities=None,
        revisions=(),
    ):
        self.database_name = database_name
        self.username = username
        self.search_path = search_path
        self.role = role or {
            "rolsuper": False,
            "rolcreatedb": False,
            "rolcreaterole": False,
            "rolreplication": False,
        }
        self.capabilities = capabilities or {
            "postgis_available": True,
            "dbi_schema_available": True,
            "version_table_available": bool(revisions),
        }
        self.revisions = revisions
        self.executed = []

    def execute(self, statement):
        sql = str(statement)
        self.executed.append(sql)
        compact = " ".join(sql.lower().split())
        if "current_database()" in compact:
            return _Result(
                row={
                    "database_name": self.database_name,
                    "username": self.username,
                    "search_path": self.search_path,
                }
            )
        if "from pg_roles" in compact:
            return _Result(row=self.role)
        if "from pg_extension" in compact:
            return _Result(row=self.capabilities)
        if "select version_num" in compact:
            return _Result(values=self.revisions)
        raise AssertionError(f"Consulta preflight inesperada: {sql}")


def _config(environment: str, database_name: str, username: str) -> DBIDatabaseConfig:
    return DBIDatabaseConfig(
        environment=environment,
        url=make_url(
            f"postgresql+psycopg://{username}:placeholder@example.invalid:5432/"
            f"{database_name}"
        ),
    )


def _assert_rejected(factory) -> None:
    try:
        factory()
    except DBIMigrationControlError:
        return
    raise AssertionError("La operación debía ser rechazada por las barreras DBI.")


def _test_target():
    return validate_migration_target(
        _config("test", "dbi_test", "dbi_test_migrator"),
        running_in_ci=True,
    )


def validate_targets() -> None:
    development = validate_migration_target(
        _config("development", "dbi_development", "dbi_development_migrator"),
        running_in_ci=False,
    )
    assert development.database_name == "dbi_development"
    assert development.apply_confirmation == "APPLY dbi_development"

    test = _test_target()
    assert test.environment == "test"

    _assert_rejected(
        lambda: validate_migration_target(
            _config("production", "dbi_production", "dbi_production_migrator"),
            running_in_ci=False,
        )
    )
    _assert_rejected(
        lambda: validate_migration_target(
            _config("staging", "dbi_staging", "dbi_staging_migrator"),
            running_in_ci=True,
        )
    )
    _assert_rejected(
        lambda: validate_migration_target(
            _config("test", "dbi_shadow", "dbi_shadow_migrator"),
            running_in_ci=True,
        )
    )
    _assert_rejected(
        lambda: validate_migration_target(
            _config("test", "dbi_test", "dbi_test_owner"),
            running_in_ci=True,
        )
    )
    _assert_rejected(
        lambda: validate_migration_target(
            _config("test", "dbi_test", "dbi_test_api"),
            running_in_ci=True,
        )
    )


def validate_confirmation() -> None:
    target = _test_target()
    require_apply_confirmation(target, "APPLY dbi_test")
    _assert_rejected(lambda: require_apply_confirmation(target, None))
    _assert_rejected(lambda: require_apply_confirmation(target, "apply dbi_test"))
    _assert_rejected(lambda: require_apply_confirmation(target, "APPLY dbi_production"))


def validate_evidence_contract() -> None:
    sql_lf = "BEGIN;\nSELECT 1;\nCOMMIT;\n"
    sql_crlf = sql_lf.replace("\n", "\r\n")
    assert plan_fingerprint(sql_lf) == plan_fingerprint(sql_crlf)
    assert len(plan_fingerprint(sql_lf)) == 64
    assert plan_fingerprint(sql_lf) != plan_fingerprint("SELECT 2;\n")

    lock_key = advisory_lock_key()
    assert -(2**63) <= lock_key < 2**63
    assert lock_key == advisory_lock_key()
    assert lock_key != 0


def validate_offline_plan() -> None:
    previous_environment = os.environ.get(DBI_ENVIRONMENT_ENV_VAR)
    previous_url = os.environ.get(DBI_DATABASE_URL_ENV_VAR)
    config = _config("test", "dbi_test", "dbi_test_migrator")

    first = generate_offline_plan(config, running_in_ci=True)
    second = generate_offline_plan(config, running_in_ci=True)

    assert first.target.database_name == "dbi_test"
    assert first.head_revision == "dbi_0006_plot_boundaries"
    assert first.fingerprint == second.fingerprint
    assert first.sql == second.sql
    assert len(first.fingerprint) == 64

    compact_sql = "".join(first.sql.lower().split())
    assert "alembic_version_dbi" in first.sql
    assert "geometry(multipolygon,4326)" in compact_sql
    assert "ix_dbi_plots_boundary_gist" in first.sql
    assert "placeholder" not in first.sql
    assert "example.invalid" not in first.sql
    assert "postgresql+psycopg://" not in first.sql

    assert os.environ.get(DBI_ENVIRONMENT_ENV_VAR) == previous_environment
    assert os.environ.get(DBI_DATABASE_URL_ENV_VAR) == previous_url

    _assert_rejected(
        lambda: generate_offline_plan(
            _config("production", "dbi_production", "dbi_production_migrator"),
            running_in_ci=False,
        )
    )


def validate_read_only_preflight() -> None:
    target = _test_target()
    known = {"dbi_0001_baseline", "dbi_0006_plot_boundaries"}

    empty_connection = _FakeConnection()
    empty = run_migration_preflight(
        empty_connection,
        target=target,
        known_revisions=known,
        head_revision="dbi_0006_plot_boundaries",
    )
    assert empty.database_is_empty is True
    assert empty.current_revision is None
    assert empty.search_path == ("dbi", "public")
    assert len(empty_connection.executed) == 3

    migrated_connection = _FakeConnection(revisions=("dbi_0006_plot_boundaries",))
    migrated = run_migration_preflight(
        migrated_connection,
        target=target,
        known_revisions=known,
        head_revision="dbi_0006_plot_boundaries",
    )
    assert migrated.is_at_head is True
    assert len(migrated_connection.executed) == 4

    rejected_connections = (
        _FakeConnection(database_name="dbi_shadow"),
        _FakeConnection(username="dbi_test_owner"),
        _FakeConnection(search_path="public, dbi"),
        _FakeConnection(role={"rolsuper": True, "rolcreatedb": False, "rolcreaterole": False, "rolreplication": False}),
        _FakeConnection(capabilities={"postgis_available": False, "dbi_schema_available": True, "version_table_available": False}),
        _FakeConnection(capabilities={"postgis_available": True, "dbi_schema_available": False, "version_table_available": False}),
        _FakeConnection(revisions=("revision_unknown",)),
        _FakeConnection(revisions=("dbi_0001_baseline", "dbi_0006_plot_boundaries")),
    )
    for connection in rejected_connections:
        _assert_rejected(
            lambda connection=connection: run_migration_preflight(
                connection,
                target=target,
                known_revisions=known,
                head_revision="dbi_0006_plot_boundaries",
            )
        )

    assert all(
        statement.lstrip().upper().startswith("SELECT")
        for statement in READ_ONLY_STATEMENTS
    )


def validate_static_boundaries() -> None:
    control_source = (
        BACKEND / "app" / "dbi" / "migration_control.py"
    ).read_text(encoding="utf-8")
    control_lower = control_source.lower()
    for forbidden in (
        "create_engine",
        "engine_from_config",
        "sessionmaker",
        "alembic.command",
        "database_url",
        "downgrade",
        "stamp(",
        "drop database",
    ):
        assert forbidden not in control_lower

    plan_source = (
        BACKEND / "app" / "dbi" / "migration_plan.py"
    ).read_text(encoding="utf-8")
    plan_lower = plan_source.lower()
    assert 'command.upgrade(alembic_config, "head", sql=true)' in plan_lower
    for forbidden in (
        "create_engine",
        "engine_from_config",
        "sessionmaker",
        ".connect(",
        ".execute(",
        "command.downgrade",
        "command.stamp",
        "drop database",
    ):
        assert forbidden not in plan_lower

    preflight_source = (
        BACKEND / "app" / "dbi" / "migration_preflight.py"
    ).read_text(encoding="utf-8")
    preflight_lower = preflight_source.lower()
    assert "connection.execute" in preflight_lower
    for forbidden in (
        "create_engine",
        "engine_from_config",
        "sessionmaker",
        "insert ",
        "update ",
        "delete ",
        "alter ",
        "drop ",
        "truncate ",
        "command.upgrade",
        "command.downgrade",
        "command.stamp",
    ):
        assert forbidden not in preflight_lower


def main() -> None:
    validate_targets()
    validate_confirmation()
    validate_evidence_contract()
    validate_offline_plan()
    validate_read_only_preflight()
    validate_static_boundaries()
    print("Controles, plan y preflight de migración DBI aprobados.")


if __name__ == "__main__":
    main()
