"""Valida el adaptador Alembic DBI sin abrir conexiones ni ejecutar migraciones reales."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.migration_control import DBIMigrationControlError  # noqa: E402
from app.dbi.migration_runner import upgrade_head_on_connection  # noqa: E402


class _FakeConnection:
    def __init__(self, *, closed: bool = False, in_transaction: bool = True):
        self.closed = closed
        self._in_transaction = in_transaction
        self.commits = 0

    def in_transaction(self) -> bool:
        return self._in_transaction

    def commit(self) -> None:
        self.commits += 1
        self._in_transaction = False


def _assert_rejected(factory) -> None:
    try:
        factory()
    except DBIMigrationControlError:
        return
    raise AssertionError("El adaptador Alembic DBI debía rechazar la operación.")


def validate_external_connection_adapter() -> None:
    connection = _FakeConnection()
    calls = []
    expected_connection = connection

    def fake_upgrade(config, revision):
        calls.append((config, revision))
        assert config.attributes["connection"] is expected_connection

    with patch("app.dbi.migration_runner.command.upgrade", fake_upgrade):
        upgrade_head_on_connection(connection)

    assert connection.commits == 1
    assert len(calls) == 1
    assert calls[0][1] == "head"

    clean_connection = _FakeConnection(in_transaction=False)
    expected_connection = clean_connection
    with patch("app.dbi.migration_runner.command.upgrade", fake_upgrade):
        upgrade_head_on_connection(clean_connection)
    assert clean_connection.commits == 0
    assert len(calls) == 2
    assert calls[1][1] == "head"

    _assert_rejected(lambda: upgrade_head_on_connection(_FakeConnection(closed=True)))


def validate_static_boundaries() -> None:
    runner_source = (
        BACKEND / "app" / "dbi" / "migration_runner.py"
    ).read_text(encoding="utf-8").lower()
    env_source = (BACKEND / "dbi_alembic" / "env.py").read_text(
        encoding="utf-8"
    ).lower()

    assert 'alembic_config.attributes["connection"] = connection' in runner_source
    assert 'command.upgrade(alembic_config, "head")' in runner_source
    assert runner_source.count("command.upgrade(") == 1
    assert 'config.attributes.get("connection")' in env_source
    assert "conexión externa controlada" in env_source

    for source in (runner_source, env_source):
        for forbidden in (
            "create_engine",
            "engine_from_config",
            "sessionmaker",
            "nullpool",
            "command.downgrade",
            "command.stamp",
            "drop database",
        ):
            assert forbidden not in source


def main() -> None:
    validate_external_connection_adapter()
    validate_static_boundaries()
    print("Adaptador Alembic DBI sobre conexión externa aprobado offline.")


if __name__ == "__main__":
    main()
