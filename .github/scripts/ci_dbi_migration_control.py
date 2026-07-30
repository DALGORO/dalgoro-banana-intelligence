"""Valida controles y planificación de migraciones DBI sin conexiones externas."""

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


def validate_targets() -> None:
    development = validate_migration_target(
        _config("development", "dbi_development", "dbi_development_migrator"),
        running_in_ci=False,
    )
    assert development.database_name == "dbi_development"
    assert development.apply_confirmation == "APPLY dbi_development"

    test = validate_migration_target(
        _config("test", "dbi_test", "dbi_test_migrator"),
        running_in_ci=True,
    )
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
    target = validate_migration_target(
        _config("test", "dbi_test", "dbi_test_migrator"),
        running_in_ci=True,
    )
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


def main() -> None:
    validate_targets()
    validate_confirmation()
    validate_evidence_contract()
    validate_offline_plan()
    validate_static_boundaries()
    print("Controles y plan offline de migración DBI aprobados.")


if __name__ == "__main__":
    main()
