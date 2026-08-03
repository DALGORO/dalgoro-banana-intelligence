"""Valida el orquestador cerrado de apply DBI sin migraciones reales."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import DBIDatabaseConfig  # noqa: E402
from app.dbi.migration_apply import apply_migrations_controlled  # noqa: E402
from app.dbi.migration_control import DBIMigrationControlError  # noqa: E402
from app.dbi.migration_preflight import (  # noqa: E402
    FORBIDDEN_ROLE_CAPABILITIES,
)

HEAD = "dbi_0010_asset_multipart_sessions"
KNOWN = {
    "dbi_0001_baseline",
    "dbi_0006_plot_boundaries",
    "dbi_0007_admin_audit",
    "dbi_0008_scope_hierarchy",
    "dbi_0009_object_key_check",
    HEAD,
}
AUTHORIZED_RUNTIME = {
    "GITHUB_ACTIONS": "true",
    "CI": "true",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "dalgorosas/dalgoro-banana-intelligence",
    "GITHUB_WORKFLOW": "DBI migrations integration",
    "GITHUB_WORKFLOW_REF": (
        "dalgorosas/dalgoro-banana-intelligence/"
        ".github/workflows/dbi-migration-integration.yml@refs/pull/48/merge"
    ),
    "GITHUB_JOB": "dbi-postgis-integration",
    "GITHUB_EVENT_NAME": "pull_request",
    "RUNNER_ENVIRONMENT": "github-hosted",
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
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)


class _Result:
    def __init__(self, *, row=None, values=(), scalar=None):
        self.row = row
        self.values = values
        self.scalar = scalar

    def mappings(self):
        return _Mappings(self.row)

    def scalars(self):
        return _Scalars(self.values)

    def scalar_one(self):
        return self.scalar


class _FakeConnection:
    def __init__(
        self,
        *,
        revision=None,
        lock_available=True,
        session_username="dbi_test_migrator",
        role=None,
    ):
        self.database_name = "dbi_test"
        self.username = "dbi_test_migrator"
        self.session_username = session_username
        self.search_path = "dbi, public"
        self.revision = revision
        self.lock_available = lock_available
        self.lock_held = False
        self.role = role or {
            field: False
            for field in FORBIDDEN_ROLE_CAPABILITIES
        }
        self.executed = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.executed.append((sql, parameters))
        compact = " ".join(sql.lower().split())

        if "pg_try_advisory_lock" in compact:
            acquired = self.lock_available and not self.lock_held
            if acquired:
                self.lock_held = True
            return _Result(scalar=acquired)
        if "pg_advisory_unlock" in compact:
            released = self.lock_held
            self.lock_held = False
            return _Result(scalar=released)
        if "from pg_roles" in compact:
            return _Result(row=self.role)
        if "current_database() as database_name" in compact:
            return _Result(
                row={
                    "database_name": self.database_name,
                    "username": self.username,
                    "session_username": self.session_username,
                    "search_path": self.search_path,
                }
            )
        if "from pg_extension" in compact:
            return _Result(
                row={
                    "postgis_available": True,
                    "dbi_schema_available": True,
                    "version_table_available": self.revision is not None,
                }
            )
        if "select version_num" in compact:
            values = () if self.revision is None else (self.revision,)
            return _Result(values=values)
        raise AssertionError(f"SQL inesperado: {sql}")


def _config(*, host="127.0.0.1", environment="test", database="dbi_test"):
    return DBIDatabaseConfig(
        environment=environment,
        url=make_url(
            "postgresql+psycopg://dbi_test_migrator:placeholder@"
            f"{host}:5432/{database}"
        ),
    )


def _assert_rejected(factory) -> None:
    try:
        factory()
    except DBIMigrationControlError:
        return
    raise AssertionError("El apply controlado debía ser rechazado.")


def _apply(connection, callback, *, config=None, **overrides):
    values = {
        "confirmation": "APPLY dbi_test",
        "running_in_ci": True,
        "known_revisions": KNOWN,
        "head_revision": HEAD,
        "upgrade_head": callback,
    }
    values.update(overrides)
    with patch.dict(os.environ, AUTHORIZED_RUNTIME, clear=False):
        return apply_migrations_controlled(
            config or _config(),
            connection,
            **values,
        )


def validate_success_and_idempotence() -> None:
    connection = _FakeConnection()
    calls = []

    def upgrade_head(received):
        assert received is connection
        assert connection.lock_held is True
        calls.append("upgrade")
        connection.revision = HEAD

    result = _apply(connection, upgrade_head)
    assert result.applied is True
    assert result.after.is_at_head is True
    assert calls == ["upgrade"]
    assert connection.lock_held is False
    assert len(result.plan.fingerprint) == 64

    already_migrated = _FakeConnection(revision=HEAD)
    second_calls = []
    result = _apply(already_migrated, lambda _: second_calls.append("unexpected"))
    assert result.applied is False
    assert second_calls == []
    assert already_migrated.lock_held is False


def validate_closed_rejections() -> None:
    no_op = lambda _: None
    _assert_rejected(
        lambda: _apply(
            _FakeConnection(),
            no_op,
            running_in_ci=False,
        )
    )
    _assert_rejected(
        lambda: _apply(
            _FakeConnection(),
            no_op,
            config=_config(host="db.example.invalid"),
        )
    )
    _assert_rejected(
        lambda: _apply(
            _FakeConnection(),
            no_op,
            confirmation="apply dbi_test",
        )
    )
    _assert_rejected(
        lambda: _apply(
            _FakeConnection(lock_available=False),
            no_op,
        )
    )
    _assert_rejected(
        lambda: _apply(
            _FakeConnection(session_username="postgres"),
            no_op,
        )
    )

    with patch.dict(
        os.environ,
        {"GITHUB_ACTIONS": "true"},
        clear=True,
    ):
        _assert_rejected(
            lambda: apply_migrations_controlled(
                _config(),
                _FakeConnection(),
                confirmation="APPLY dbi_test",
                running_in_ci=True,
                known_revisions=KNOWN,
                head_revision=HEAD,
                upgrade_head=no_op,
            )
        )


def validate_failure_paths_release_lock() -> None:
    connection = _FakeConnection()

    def failing_upgrade(_):
        assert connection.lock_held is True
        raise RuntimeError("fallo controlado")

    try:
        _apply(connection, failing_upgrade)
    except RuntimeError as exc:
        assert str(exc) == "fallo controlado"
    else:
        raise AssertionError("La excepción de upgrade debía propagarse.")
    assert connection.lock_held is False

    no_head = _FakeConnection()
    _assert_rejected(lambda: _apply(no_head, lambda _: None))
    assert no_head.lock_held is False


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "migration_apply.py"
    ).read_text(encoding="utf-8").lower()
    assert "require_authorized_github_actions_runtime()" in source
    assert "migration_lock(connection)" in source
    assert "upgrade_head(connection)" in source
    assert source.count("upgrade_head(connection)") == 1
    for forbidden in (
        "create_engine",
        "engine_from_config",
        "sessionmaker",
        "command.upgrade",
        "command.downgrade",
        "command.stamp",
        "drop database",
        "truncate ",
    ):
        assert forbidden not in source


def main() -> None:
    validate_success_and_idempotence()
    validate_closed_rejections()
    validate_failure_paths_release_lock()
    validate_static_boundaries()
    print("Orquestador cerrado de apply DBI aprobado offline.")


if __name__ == "__main__":
    main()
