"""Valida la interfaz operativa DBI sin abrir conexiones reales."""

from __future__ import annotations

import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi import migration_cli  # noqa: E402
from app.dbi.migration_control import validate_migration_target  # noqa: E402

HEAD = "dbi_0008_scope_hierarchy"
TEST_URL = (
    "postgresql+psycopg://dbi_test_migrator:placeholder@"
    "127.0.0.1:5432/dbi_test"
)
DEVELOPMENT_URL = (
    "postgresql+psycopg://dbi_development_migrator:placeholder@"
    "127.0.0.1:5432/dbi_development"
)


class _FakeConnection:
    pass


class _FakeEngine:
    def __init__(self):
        self.connection = _FakeConnection()
        self.dispose_calls = 0

    class _ConnectionContext:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self.connection

        def __exit__(self, exc_type, exc, traceback):
            return False

    def connect(self):
        return self._ConnectionContext(self.connection)

    def dispose(self):
        self.dispose_calls += 1


def _run(argv, environment):
    stdout = StringIO()
    stderr = StringIO()
    with patch.dict(os.environ, environment, clear=True):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = migration_cli.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def _ci_environment(url: str = TEST_URL):
    return {
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
        "DBI_ENVIRONMENT": "test",
        "DBI_DATABASE_URL": url,
    }


def _development_environment(url: str = DEVELOPMENT_URL):
    return {
        "DBI_ENVIRONMENT": "development",
        "DBI_DATABASE_URL": url,
    }


def _assert_no_connection_markers(output: str) -> None:
    for marker in (
        "placeholder",
        "127.0.0.1",
        "postgresql+psycopg://",
    ):
        assert marker not in output


def validate_default_plan() -> None:
    with patch(
        "app.dbi.migration_cli.create_engine",
        side_effect=AssertionError("plan no debe abrir conexiones"),
    ):
        code, stdout, stderr = _run([], _ci_environment())

    assert code == 0
    assert stderr == ""
    evidence = json.loads(stdout)
    assert evidence["operation"] == "plan"
    assert evidence["environment"] == "test"
    assert evidence["database"] == "dbi_test"
    assert evidence["head_revision"] == HEAD
    assert len(evidence["plan_sha256"]) == 64
    assert evidence["sql_output"] is None
    _assert_no_connection_markers(stdout)

    code, _, stderr = _run(
        ["plan", "--confirm", "APPLY dbi_test"],
        _ci_environment(),
    )
    assert code == 2
    assert "--confirm" in stderr

    production = {
        "DBI_ENVIRONMENT": "production",
        "DBI_DATABASE_URL": (
            "postgresql+psycopg://dbi_production_migrator:placeholder@"
            "127.0.0.1:5432/dbi_production"
        ),
    }
    code, stdout, stderr = _run(["plan"], production)
    assert code == 2
    assert stdout == ""
    assert "produ" in stderr.lower()
    _assert_no_connection_markers(stderr)


def validate_plan_sql_output() -> None:
    with TemporaryDirectory() as directory:
        output_path = Path(directory) / "dbi-plan.sql"
        code, stdout, stderr = _run(
            ["plan", "--sql-output", str(output_path)],
            _ci_environment(),
        )
        assert code == 0
        assert stderr == ""
        assert output_path.is_file()
        sql_text = output_path.read_text(encoding="utf-8").lower()
        assert "alembic_version_dbi" in sql_text
        assert "geometry(multipolygon,4326)" in "".join(sql_text.split())
        assert "dbi_admin_audit_events" in sql_text
        for constraint_name in (
            "uq_dbi_farms_id_organization",
            "uq_dbi_plots_id_farm",
            "fk_dbi_membership_scopes_farm_organization",
            "fk_dbi_membership_scopes_plot_farm",
        ):
            assert constraint_name in sql_text
        evidence = json.loads(stdout)
        assert evidence["sql_output"] == str(output_path)

        original = output_path.read_text(encoding="utf-8")
        code, _, stderr = _run(
            ["plan", "--sql-output", str(output_path)],
            _ci_environment(),
        )
        assert code == 3
        assert output_path.read_text(encoding="utf-8") == original
        assert "detalles de conexión" in stderr


def validate_verify_scope_and_evidence() -> None:
    engine = _FakeEngine()

    def fake_preflight(connection, *, target, known_revisions, head_revision):
        assert connection is engine.connection
        assert target.environment == "development"
        assert target.database_name == "dbi_development"
        assert head_revision in known_revisions
        return SimpleNamespace(
            current_revision=None,
            database_is_empty=True,
            is_at_head=False,
            search_path=("dbi", "public"),
            postgis_available=True,
            dbi_schema_available=True,
        )

    with patch(
        "app.dbi.migration_cli.create_engine",
        return_value=engine,
    ), patch(
        "app.dbi.migration_cli.run_migration_preflight",
        side_effect=fake_preflight,
    ):
        code, stdout, stderr = _run(
            ["verify"],
            _development_environment(),
        )

    assert code == 0
    assert stderr == ""
    assert engine.dispose_calls == 1
    evidence = json.loads(stdout)
    assert evidence["operation"] == "verify"
    assert evidence["database_is_empty"] is True
    assert evidence["search_path"] == ["dbi", "public"]
    _assert_no_connection_markers(stdout)

    staging = {
        "DBI_ENVIRONMENT": "staging",
        "DBI_DATABASE_URL": (
            "postgresql+psycopg://dbi_staging_migrator:placeholder@"
            "127.0.0.1:5432/dbi_staging"
        ),
    }
    with patch(
        "app.dbi.migration_cli.create_engine",
        side_effect=AssertionError("staging no debe abrir conexión"),
    ):
        code, _, stderr = _run(["verify"], staging)
    assert code == 2
    assert "development" in stderr

    remote = _development_environment(
        DEVELOPMENT_URL.replace("127.0.0.1", "db.example.invalid")
    )
    with patch(
        "app.dbi.migration_cli.create_engine",
        side_effect=AssertionError("host remoto no debe abrir conexión"),
    ):
        code, _, stderr = _run(["verify"], remote)
    assert code == 2
    assert "local" in stderr.lower()


def validate_apply_scope_and_evidence() -> None:
    engine = _FakeEngine()
    callback_seen = []

    def fake_apply(
        config,
        connection,
        *,
        confirmation,
        running_in_ci,
        known_revisions,
        head_revision,
        upgrade_head,
    ):
        assert connection is engine.connection
        assert confirmation == "APPLY dbi_test"
        assert running_in_ci is True
        assert head_revision in known_revisions
        callback_seen.append(upgrade_head)
        target = validate_migration_target(config, running_in_ci=True)
        return SimpleNamespace(
            target=target,
            before=SimpleNamespace(current_revision=None),
            after=SimpleNamespace(
                current_revision=head_revision,
                head_revision=head_revision,
            ),
            applied=True,
            plan=SimpleNamespace(fingerprint="0" * 64),
        )

    with patch(
        "app.dbi.migration_cli.create_engine",
        return_value=engine,
    ), patch(
        "app.dbi.migration_cli.apply_migrations_controlled",
        side_effect=fake_apply,
    ):
        code, stdout, stderr = _run(
            ["apply", "--confirm", "APPLY dbi_test"],
            _ci_environment(),
        )

    assert code == 0
    assert stderr == ""
    assert engine.dispose_calls == 1
    assert callback_seen == [migration_cli.upgrade_head_on_connection]
    evidence = json.loads(stdout)
    assert evidence["operation"] == "apply"
    assert evidence["applied"] is True
    assert evidence["after_revision"] == HEAD
    _assert_no_connection_markers(stdout)

    with patch(
        "app.dbi.migration_cli.create_engine",
        side_effect=AssertionError("confirmación inválida no debe conectar"),
    ):
        code, _, stderr = _run(["apply"], _ci_environment())
    assert code == 2
    assert "confirmación" in stderr.lower()

    with patch(
        "app.dbi.migration_cli.create_engine",
        side_effect=AssertionError("fuera de CI no debe conectar"),
    ):
        code, _, stderr = _run(
            ["apply", "--confirm", "APPLY dbi_development"],
            _development_environment(),
        )
    assert code == 2
    assert "ci" in stderr.lower()

    spoofed_ci = {
        "GITHUB_ACTIONS": "true",
        "DBI_ENVIRONMENT": "test",
        "DBI_DATABASE_URL": TEST_URL,
    }
    with patch(
        "app.dbi.migration_cli.create_engine",
        side_effect=AssertionError("runtime incompleto no debe conectar"),
    ):
        code, _, stderr = _run(
            ["apply", "--confirm", "APPLY dbi_test"],
            spoofed_ci,
        )
    assert code == 2
    assert "workflow" in stderr.lower()

    remote = _ci_environment(
        TEST_URL.replace("127.0.0.1", "db.example.invalid")
    )
    with patch(
        "app.dbi.migration_cli.create_engine",
        side_effect=AssertionError("host remoto no debe conectar"),
    ):
        code, _, stderr = _run(
            ["apply", "--confirm", "APPLY dbi_test"],
            remote,
        )
    assert code == 2
    assert "local" in stderr.lower()


def validate_safe_connection_error() -> None:
    secret = "do-not-print-this-secret"
    with patch(
        "app.dbi.migration_cli.create_engine",
        side_effect=SQLAlchemyError(secret),
    ):
        code, stdout, stderr = _run(
            ["verify"],
            _development_environment(),
        )

    assert code == 3
    assert stdout == ""
    assert secret not in stderr
    _assert_no_connection_markers(stderr)


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "migration_cli.py"
    ).read_text(encoding="utf-8").lower()

    assert 'default="plan"' in source
    assert 'choices=("plan", "verify", "apply")' in source
    assert "require_authorized_github_actions_runtime()" in source
    assert 'command.upgrade' not in source
    assert "--yes" not in source
    assert "database_url" not in source
    for forbidden in (
        "command.downgrade",
        "command.stamp",
        "drop database",
        "truncate ",
    ):
        assert forbidden not in source


def main() -> None:
    validate_default_plan()
    validate_plan_sql_output()
    validate_verify_scope_and_evidence()
    validate_apply_scope_and_evidence()
    validate_safe_connection_error()
    validate_static_boundaries()
    print("Interfaz operativa DBI plan/verify/apply aprobada offline.")


if __name__ == "__main__":
    main()
