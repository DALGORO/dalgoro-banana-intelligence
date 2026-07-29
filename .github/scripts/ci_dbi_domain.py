"""Valida el dominio agrícola DBI sin conectar con PostgreSQL."""

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
from sqlalchemy import CheckConstraint, UniqueConstraint

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.dbi_base import DBIBase  # noqa: E402
from app.dbi.models import Campaign, Farm, Plot  # noqa: E402

EXPECTED_TABLES = {"dbi_farms", "dbi_plots", "dbi_campaigns"}
EXPECTED_COLUMNS = {
    "dbi_farms": {
        "id",
        "organization_ref",
        "code",
        "name",
        "status",
        "created_at",
        "updated_at",
    },
    "dbi_plots": {
        "id",
        "farm_id",
        "code",
        "name",
        "area_hectares",
        "status",
        "created_at",
        "updated_at",
    },
    "dbi_campaigns": {
        "id",
        "farm_id",
        "code",
        "name",
        "starts_at",
        "ends_at",
        "status",
        "created_at",
        "updated_at",
    },
}


def validate_metadata() -> None:
    """Comprueba tablas, columnas y aislamiento de metadatos."""

    assert {Farm, Plot, Campaign}
    assert EXPECTED_TABLES.issubset(DBIBase.metadata.tables)

    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        table = DBIBase.metadata.tables[table_name]
        assert set(table.columns.keys()) == expected_columns

    plot_targets = {
        foreign_key.target_fullname
        for foreign_key in DBIBase.metadata.tables["dbi_plots"].foreign_keys
    }
    campaign_targets = {
        foreign_key.target_fullname
        for foreign_key in DBIBase.metadata.tables[
            "dbi_campaigns"
        ].foreign_keys
    }
    assert plot_targets == {"dbi_farms.id"}
    assert campaign_targets == {"dbi_farms.id"}


def validate_constraints() -> None:
    """Comprueba unicidad, estados y consistencia temporal."""

    constraint_names = {
        constraint.name
        for table in DBIBase.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
    }
    assert {
        "uq_dbi_farms_organization_code",
        "uq_dbi_plots_farm_code",
        "uq_dbi_campaigns_farm_code",
        "ck_dbi_farms_status",
        "ck_dbi_plots_status",
        "ck_dbi_plots_positive_area",
        "ck_dbi_campaigns_status",
        "ck_dbi_campaigns_date_order",
    }.issubset(constraint_names)

    all_constraint_names = {
        constraint.name
        for table in DBIBase.metadata.tables.values()
        for constraint in table.constraints
    }
    assert {
        "pk_dbi_farms",
        "pk_dbi_plots",
        "pk_dbi_campaigns",
        "fk_dbi_plots_farm_id_dbi_farms",
        "fk_dbi_campaigns_farm_id_dbi_farms",
    }.issubset(all_constraint_names)


def validate_migration_graph() -> None:
    """Comprueba que el dominio continúa la línea base DBI."""

    config = Config(str(BACKEND_ROOT / "dbi_alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_bases() == ["dbi_0001_baseline"]
    assert len(scripts.get_heads()) == 1
    revision = scripts.get_revision("dbi_0002_agricultural_domain")
    assert revision is not None
    assert revision.down_revision == "dbi_0001_baseline"


def validate_offline_sql() -> None:
    """Genera el historial completo sin abrir conexiones."""

    config = Config(str(BACKEND_ROOT / "dbi_alembic.ini"))
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
            command.upgrade(config, "head", sql=True)

    sql = output.getvalue().lower()
    for table_name in EXPECTED_TABLES:
        assert f"create table {table_name}" in sql

    assert "alembic_version_dbi" in sql
    for forbidden in (
        "create extension",
        "postgis",
        "geometry(",
        "geography(",
        "gen_random_uuid",
        "uuid_generate",
        "insert into dbi_farms",
        "insert into dbi_plots",
        "insert into dbi_campaigns",
        "create table users",
        "create table companies",
        "create table documents",
    ):
        assert forbidden not in sql


def validate_sources() -> None:
    """Bloquea motores, sesiones y extensiones dentro del dominio."""

    models_source = (
        BACKEND_ROOT / "app" / "dbi" / "models" / "agriculture.py"
    ).read_text(encoding="utf-8").lower()
    migration_source = (
        BACKEND_ROOT
        / "dbi_alembic"
        / "versions"
        / "20260729_02_agricultural_domain.py"
    ).read_text(encoding="utf-8").lower()
    env_source = (
        BACKEND_ROOT / "dbi_alembic" / "env.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "create_engine",
        "sessionmaker",
        "app.models.user",
        "app.models.company",
        "geometry",
        "geography",
        "postgis",
    ):
        assert forbidden not in models_source

    assert "create extension" not in migration_source
    assert "op.bulk_insert" not in migration_source
    assert "app.dbi import models as dbi_models" in env_source


def main() -> None:
    """Ejecuta las barreras del dominio agrícola."""

    validate_metadata()
    validate_constraints()
    validate_migration_graph()
    validate_offline_sql()
    validate_sources()
    print("Dominio agrícola DBI: validación offline aprobada.")


if __name__ == "__main__":
    main()
