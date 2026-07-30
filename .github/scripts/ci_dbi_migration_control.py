"""Valida controles de migración DBI sin abrir conexiones externas."""

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
    advisory_lock_key,
    plan_fingerprint,
    require_apply_confirmation,
    validate_migration_target,
)


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


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "migration_control.py"
    ).read_text(encoding="utf-8")
    lower = source.lower()
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
        assert forbidden not in lower


def main() -> None:
    validate_targets()
    validate_confirmation()
    validate_evidence_contract()
    validate_static_boundaries()
    print("Controles puros de migración DBI aprobados offline.")


if __name__ == "__main__":
    main()
