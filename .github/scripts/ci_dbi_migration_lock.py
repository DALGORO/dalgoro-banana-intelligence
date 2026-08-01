"""Valida el advisory lock DBI sin abrir conexiones externas."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.migration_control import (  # noqa: E402
    DBIMigrationControlError,
    advisory_lock_key,
)
from app.dbi.migration_lock import (  # noqa: E402
    acquire_migration_lock,
    migration_lock,
    release_migration_lock,
)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _FakeConnection:
    def __init__(self, *, acquire=True, release=True):
        self.acquire = acquire
        self.release = release
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = " ".join(str(statement).lower().split())
        parameters = dict(parameters or {})
        self.calls.append((sql, parameters))
        assert parameters == {"lock_key": advisory_lock_key()}
        if "pg_try_advisory_lock" in sql:
            return _ScalarResult(self.acquire)
        if "pg_advisory_unlock" in sql:
            return _ScalarResult(self.release)
        raise AssertionError(f"Sentencia de lock inesperada: {sql}")


def _assert_rejected(factory) -> None:
    try:
        factory()
    except DBIMigrationControlError:
        return
    raise AssertionError("La operación debía ser rechazada por el lock DBI.")


def validate_acquire_and_release() -> None:
    connection = _FakeConnection()
    key = acquire_migration_lock(connection)
    assert key == advisory_lock_key()
    release_migration_lock(connection, key)
    assert len(connection.calls) == 2
    assert "pg_try_advisory_lock" in connection.calls[0][0]
    assert "pg_advisory_unlock" in connection.calls[1][0]


def validate_context_manager() -> None:
    connection = _FakeConnection()
    with migration_lock(connection) as key:
        assert key == advisory_lock_key()
        assert len(connection.calls) == 1
    assert len(connection.calls) == 2

    failing = _FakeConnection()
    try:
        with migration_lock(failing):
            raise ValueError("fallo simulado")
    except ValueError as exc:
        assert str(exc) == "fallo simulado"
    else:
        raise AssertionError("La excepción original debía propagarse.")
    assert len(failing.calls) == 2


def validate_closed_failures() -> None:
    _assert_rejected(lambda: acquire_migration_lock(_FakeConnection(acquire=False)))
    _assert_rejected(
        lambda: release_migration_lock(
            _FakeConnection(release=False), advisory_lock_key()
        )
    )
    _assert_rejected(lambda: acquire_migration_lock(_InvalidConnection()))


class _InvalidConnection:
    def execute(self, statement, parameters=None):
        return _ScalarResult("true")


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "migration_lock.py"
    ).read_text(encoding="utf-8")
    lower = source.lower()
    assert "pg_try_advisory_lock" in lower
    assert "pg_advisory_unlock" in lower
    assert "finally:" in lower
    for forbidden in (
        "create_engine",
        "engine_from_config",
        "sessionmaker",
        "command.upgrade",
        "command.downgrade",
        "command.stamp",
        "drop database",
        "pg_advisory_lock(",
    ):
        assert forbidden not in lower


def main() -> None:
    validate_acquire_and_release()
    validate_context_manager()
    validate_closed_failures()
    validate_static_boundaries()
    print("Advisory lock de migraciones DBI aprobado offline.")


if __name__ == "__main__":
    main()
