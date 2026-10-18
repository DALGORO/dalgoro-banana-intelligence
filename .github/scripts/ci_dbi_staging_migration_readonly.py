"""Test sin infraestructura: staging read-only, rechazo seguro y redacción total."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))
sys.path.insert(0, str(ROOT / ".github" / "scripts"))

from app.dbi import staging_migration_verify as staging  # noqa: E402
from ci_dbi_migration_control_base import _FakeConnection  # noqa: E402

URL = (
    "postgresql+psycopg://dbi_staging_migration_auditor:SENSITIVE_PASSWORD@"
    "staging-db.example.org:5432/dbi_staging?sslmode=verify-full"
)
VALUES = {
    "DBI_ENVIRONMENT": "staging",
    "DBI_DATABASE_URL": URL,
    "DBI_STAGING_VERIFY_HOST": "staging-db.example.org",
    "DBI_STAGING_VERIFY_CONFIRM": "VERIFY dbi_staging READ ONLY",
}
HEAD = "dbi_0031_raster_asset"


class Connection(_FakeConnection):
    def __init__(self, *, revision=HEAD, **kwargs):
        super().__init__(
            database_name="dbi_staging",
            username="dbi_staging_migration_auditor",
            revisions=(revision,) if revision is not None else (),
            **kwargs,
        )
        self.rollbacks = 0
        self.readonly = False

    def exec_driver_sql(self, statement):
        assert statement == "SET TRANSACTION READ ONLY"
        assert not self.executed
        self.readonly = True
        self.executed.append(statement)

    def execute(self, statement):
        assert self.readonly
        assert str(statement).lstrip().upper().startswith("SELECT")
        return super().execute(statement)

    def rollback(self):
        self.rollbacks += 1


class Engine:
    def __init__(self, conn):
        self.conn = conn
        self.connects = 0
        self.disposes = 0

    def connect(self):
        self.connects += 1

        class Context:
            def __enter__(inner):
                return self.conn

            def __exit__(inner, *args):
                return False

        return Context()

    def dispose(self):
        self.disposes += 1


def call(values):
    sink = StringIO()
    with redirect_stdout(sink):
        code = staging.main(["--verify-readonly"], values=values)
    output = sink.getvalue()
    assert output.endswith("\n") and output.count("\n") == 1
    for forbidden in (
        "SENSITIVE_PASSWORD", "staging-db.example.org",
        "postgresql+psycopg", "DBI_DATABASE_URL",
        "sslmode=verify-full",
    ):
        assert forbidden not in output, forbidden
    return code, json.loads(output)


def blocked(values):
    with patch.object(staging, "create_engine", side_effect=AssertionError("blocked must not connect")):
        code, output = call(values)
    assert code == 2 and output["result"] == "BLOCKED"
    assert output["deployment_readiness"] == "NOT_VERIFIED"


def run():
    # Test de guardas sin motor ni red.
    blocked({**VALUES, "DBI_ENVIRONMENT": "production"})
    blocked({**VALUES, "DBI_ENVIRONMENT": "test"})
    blocked({**VALUES, "GITHUB_ACTIONS": "true"})
    blocked({**VALUES, "CI": "true"})
    blocked({**VALUES, "DBI_STAGING_VERIFY_CONFIRM": "APPLY dbi_staging"})
    blocked({**VALUES, "DBI_STAGING_VERIFY_CONFIRM": ""})
    blocked({**VALUES, "DBI_STAGING_VERIFY_HOST": "production-db.example.org"})
    blocked({**VALUES, "DBI_STAGING_VERIFY_HOST": "localhost"})
    blocked({**VALUES, "DBI_DATABASE_URL": URL.replace(
        "staging-db.example.org", "127.0.0.1"),
        "DBI_STAGING_VERIFY_HOST": "127.0.0.1"})
    blocked({**VALUES, "DBI_DATABASE_URL": URL.replace(
        "staging-db.example.org", "staging-db.example.invalid"),
        "DBI_STAGING_VERIFY_HOST": "staging-db.example.invalid"})
    blocked({**VALUES, "DBI_DATABASE_URL": URL.replace(
        "sslmode=verify-full", "sslmode=require")})
    blocked({**VALUES, "DBI_DATABASE_URL": URL.replace(
        "sslmode=verify-full", "sslmode=disable")})
    blocked({**VALUES, "DBI_DATABASE_URL": URL.replace(
        "dbi_staging_migration_auditor", "dbi_staging_migrator")})
    blocked({**VALUES, "DBI_DATABASE_URL": URL.replace(
        "/dbi_staging?", "/dbi_production?")})
    blocked({**VALUES, "DBI_DATABASE_URL": URL.replace(
        ":5432/", ":5433/")})
    blocked({**VALUES, "DBI_DATABASE_URL": ""})

    conn = Connection()
    engine = Engine(conn)

    def connect(url, **kwargs):
        assert url.database == "dbi_staging" and url.username == staging.AUDITOR_ROLE
        assert url.query["sslmode"] == "verify-full"
        assert kwargs["poolclass"].__name__ == "NullPool"
        assert kwargs["connect_args"]["connect_timeout"] == 5
        assert "default_transaction_read_only=on" in kwargs["connect_args"]["options"]
        assert "statement_timeout=8000" in kwargs["connect_args"]["options"]
        return engine

    with patch.object(socket, "socket", side_effect=AssertionError("NO NETWORK")):
        with patch.object(staging, "create_engine", side_effect=connect):
            code, report = call(VALUES)
    assert code == 0 and conn.readonly and conn.rollbacks == 1
    assert engine.connects == 1 and engine.disposes == 1
    assert report["operation"] == "verify-staging-readonly"
    assert report["migration_apply"] == "BLOCKED"
    assert report["deployment_readiness"] == "NOT_VERIFIED"
    assert report["is_at_head"] is True
    assert report["database_revision"] == HEAD
    assert report["code_head_revision"] == HEAD
    assert len(conn.executed) == 5  # SET TRANSACTION READ ONLY + 4 SELECT

    # Entorno con migración pendiente: informa diferencia pero no aplica nada.
    lagged = Engine(Connection(revision="dbi_0025_gpkg_layer_options"))
    with patch.object(staging, "create_engine", return_value=lagged):
        code, info = call(VALUES)
    assert code == 0 and info["is_at_head"] is False
    assert info["database_revision"] == "dbi_0025_gpkg_layer_options"
    assert lagged.conn.rollbacks == 1 and lagged.disposes == 1

    # Errores de privilegio/certificados/consulta quedan redactados.
    badrole = {field: False for field in (
        "rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication",
        "rolbypassrls", "has_role_memberships", "owns_database", "owns_dbi_schema",
    )}
    badrole["rolsuper"] = True
    restricted = Engine(Connection(role=badrole))
    with patch.object(staging, "create_engine", return_value=restricted):
        code, data = call(VALUES)
    assert code == 2 and data["result"] == "BLOCKED"
    assert restricted.disposes == 1

    with patch.object(
        staging, "create_engine",
        side_effect=SQLAlchemyError("SENSITIVE_PASSWORD staging-db.example.org"),
    ):
        code, data = call(VALUES)
    assert code == 3 and data["result"] == "UNAVAILABLE"

    # El controlador original no adquiere capacidad staging ni nuevo apply.
    from app.dbi import migration_cli
    with patch.object(migration_cli, "create_engine", side_effect=AssertionError("no connection")):
        out = StringIO()
        err = StringIO()
        from contextlib import redirect_stderr
        with patch.dict(os.environ, VALUES, clear=True), redirect_stdout(out), redirect_stderr(err):
            code = migration_cli.main(["verify"])
        assert code == 2 and out.getvalue() == ""
        assert "SENSITIVE_PASSWORD" not in err.getvalue()
        assert "staging-db.example.org" not in err.getvalue()
    print("Staging migration auditor: READ ONLY, SSL, tenant DBI, CI blocked, secrets safe.")


if __name__ == "__main__":
    run()
