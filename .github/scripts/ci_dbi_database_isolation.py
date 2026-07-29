"""Valida el aislamiento DBI sin conectarse a una base de datos."""

from __future__ import annotations

import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.dbi_config import (  # noqa: E402
    DBIDatabaseConfigurationError,
    load_dbi_database_config,
)

AUTHORIZED_DATABASES = {
    "development": "dbi_development",
    "test": "dbi_test",
    "staging": "dbi_staging",
    "production": "dbi_production",
}

LEGACY_HEADS = {
    "20260411_01",
    "2cec060d9aa4",
    "7ce73aae44ce",
}


def assert_rejected(values: dict[str, str]) -> None:
    """Comprueba rechazo sin permitir que el error revele la URL."""

    secret_markers = ("dbi_user", "dbi-password", "example.internal")
    try:
        load_dbi_database_config(values)
    except DBIDatabaseConfigurationError as exc:
        message = str(exc)
        assert all(marker not in message for marker in secret_markers), message
    else:
        raise AssertionError(f"Configuración no autorizada aceptada: {values.keys()}")


def validate_configuration_barriers() -> None:
    """Valida ambientes autorizados y rechazo de rutas heredadas."""

    for environment, database_name in AUTHORIZED_DATABASES.items():
        config = load_dbi_database_config(
            {
                "DBI_ENVIRONMENT": environment,
                "DBI_DATABASE_URL": (
                    "postgresql+psycopg://dbi_user:dbi-password"
                    f"@example.internal:5432/{database_name}"
                ),
            }
        )
        assert config.environment == environment
        assert config.database_name == database_name

    provider_style_config = load_dbi_database_config(
        {
            "DBI_ENVIRONMENT": "test",
            "DBI_DATABASE_URL": (
                "postgresql://dbi_user:dbi-password"
                "@example.internal:5432/dbi_test"
            ),
        }
    )
    assert provider_style_config.database_name == "dbi_test"

    assert_rejected(
        {
            "DBI_ENVIRONMENT": "test",
            "DATABASE_URL": (
                "postgresql+psycopg://dbi_user:dbi-password"
                "@example.internal:5432/sst_compliance"
            ),
        }
    )
    assert_rejected(
        {
            "DBI_ENVIRONMENT": "test",
            "DBI_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        }
    )
    assert_rejected(
        {
            "DBI_ENVIRONMENT": "test",
            "DBI_DATABASE_URL": (
                "postgresql+psycopg://dbi_user:dbi-password"
                "@example.internal:5432/sst_compliance"
            ),
        }
    )
    assert_rejected(
        {
            "DBI_ENVIRONMENT": "test",
            "DBI_DATABASE_URL": (
                "postgresql+psycopg://dbi_user:dbi-password@/dbi_test"
            ),
        }
    )
    assert_rejected(
        {
            "DBI_ENVIRONMENT": "unknown",
            "DBI_DATABASE_URL": (
                "postgresql+psycopg://dbi_user:dbi-password"
                "@example.internal:5432/dbi_test"
            ),
        }
    )


def validate_migration_graphs() -> None:
    """Comprueba que los historiales DBI y heredado no se mezclaron."""

    legacy_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    legacy_scripts = ScriptDirectory.from_config(legacy_config)
    assert set(legacy_scripts.get_heads()) == LEGACY_HEADS

    dbi_config = Config(str(BACKEND_ROOT / "dbi_alembic.ini"))
    dbi_scripts = ScriptDirectory.from_config(dbi_config)
    assert dbi_scripts.get_bases() == ["dbi_0001_baseline"]
    assert dbi_scripts.get_heads() == ["dbi_0001_baseline"]


def validate_offline_sql() -> None:
    """Genera SQL DBI offline y confirma que no contiene dominio heredado."""

    dbi_config = Config(str(BACKEND_ROOT / "dbi_alembic.ini"))
    output = StringIO()
    environment = {
        "DBI_ENVIRONMENT": "test",
        "DBI_DATABASE_URL": (
            "postgresql+psycopg://dbi_user:dbi-password"
            "@example.internal:5432/dbi_test"
        ),
    }

    with patch.dict(os.environ, environment, clear=True):
        with redirect_stdout(output):
            command.upgrade(dbi_config, "head", sql=True)

    sql = output.getvalue().lower()
    assert "alembic_version_dbi" in sql
    assert "documents" not in sql
    assert "users" not in sql
    assert "companies" not in sql
    assert "drop database" not in sql


def validate_no_destructive_database_command() -> None:
    """Bloquea comandos de eliminación de base dentro del historial DBI."""

    migration_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (BACKEND_ROOT / "dbi_alembic" / "versions").glob("*.py")
    )
    assert "drop database" not in migration_text
    assert "drop_database" not in migration_text


def validate_source_isolation() -> None:
    """Comprueba que el código DBI no importe configuración heredada."""

    config_source = (
        BACKEND_ROOT / "app" / "db" / "dbi_config.py"
    ).read_text(encoding="utf-8")
    env_source = (BACKEND_ROOT / "dbi_alembic" / "env.py").read_text(
        encoding="utf-8"
    )
    ini_source = (BACKEND_ROOT / "dbi_alembic.ini").read_text(encoding="utf-8")

    assert 'source.get("DATABASE_URL"' not in config_source
    assert "create_engine" not in config_source
    assert "sessionmaker" not in config_source
    assert "app.core.config" not in env_source
    assert "app.db.base import Base" not in env_source
    assert "sst_compliance" not in ini_source
    assert "dalgoro_banana" not in ini_source


def main() -> None:
    """Ejecuta todas las comprobaciones sin servicios externos."""

    validate_configuration_barriers()
    validate_migration_graphs()
    validate_offline_sql()
    validate_no_destructive_database_command()
    validate_source_isolation()
    print("Aislamiento DBI: configuración y Alembic offline aprobados.")


if __name__ == "__main__":
    main()
