"""Valida trabajos e intentos DBI sin conectar con PostgreSQL."""

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
from app.dbi.jobs import AnalysisJobStatus  # noqa: E402
from app.dbi.models import (  # noqa: E402
    AnalysisJob,
    AnalysisJobAttempt,
    Campaign,
    Farm,
    Plot,
)

EXPECTED_TABLES = {
    "dbi_farms",
    "dbi_plots",
    "dbi_campaigns",
    "dbi_analysis_jobs",
    "dbi_analysis_job_attempts",
}
EXPECTED_NEW_COLUMNS = {
    "dbi_analysis_jobs": {
        "id",
        "tenant_ref",
        "request_id",
        "correlation_id",
        "farm_id",
        "plot_id",
        "campaign_id",
        "orthophoto_asset_ref",
        "boundary_asset_ref",
        "exclusions_asset_ref",
        "model_version_ref",
        "pipeline_config_version",
        "requested_by_ref",
        "command_sha256",
        "status",
        "accepted_at",
        "created_at",
        "updated_at",
    },
    "dbi_analysis_job_attempts": {
        "id",
        "job_id",
        "attempt_number",
        "status",
        "worker_ref",
        "pipeline_build_ref",
        "result_sha256",
        "failure_code",
        "queued_at",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    },
}


def validate_metadata() -> None:
    """Comprueba tablas, columnas, relaciones y aislamiento."""

    assert {Farm, Plot, Campaign, AnalysisJob, AnalysisJobAttempt}
    assert EXPECTED_TABLES.issubset(DBIBase.metadata.tables)

    for table_name, columns in EXPECTED_NEW_COLUMNS.items():
        assert set(
            DBIBase.metadata.tables[table_name].columns.keys()
        ) == columns

    job_targets = {
        foreign_key.target_fullname
        for foreign_key in DBIBase.metadata.tables[
            "dbi_analysis_jobs"
        ].foreign_keys
    }
    attempt_targets = {
        foreign_key.target_fullname
        for foreign_key in DBIBase.metadata.tables[
            "dbi_analysis_job_attempts"
        ].foreign_keys
    }
    assert job_targets == {
        "dbi_farms.id",
        "dbi_plots.id",
        "dbi_campaigns.id",
    }
    assert attempt_targets == {"dbi_analysis_jobs.id"}
    assert AnalysisJob.attempts.property.mapper.class_ is AnalysisJobAttempt
    assert AnalysisJobAttempt.job.property.mapper.class_ is AnalysisJob


def validate_constraints() -> None:
    """Comprueba idempotencia, estados, huellas y orden temporal."""

    constraints = {
        constraint.name: constraint
        for table in DBIBase.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
    }
    expected_names = {
        "uq_dbi_analysis_jobs_tenant_request",
        "ck_dbi_analysis_jobs_status",
        "ck_dbi_analysis_jobs_command_sha256",
        "uq_dbi_analysis_job_attempts_job_number",
        "ck_dbi_analysis_job_attempts_positive_number",
        "ck_dbi_analysis_job_attempts_status",
        "ck_dbi_analysis_job_attempts_start_order",
        "ck_dbi_analysis_job_attempts_finish_order",
        "ck_dbi_analysis_job_attempts_result_sha256",
    }
    assert expected_names.issubset(constraints)

    idempotency = constraints["uq_dbi_analysis_jobs_tenant_request"]
    assert [column.name for column in idempotency.columns] == [
        "tenant_ref",
        "request_id",
    ]
    attempt_number = constraints[
        "uq_dbi_analysis_job_attempts_job_number"
    ]
    assert [column.name for column in attempt_number.columns] == [
        "job_id",
        "attempt_number",
    ]

    job_status_sql = str(
        constraints["ck_dbi_analysis_jobs_status"].sqltext
    )
    for status in AnalysisJobStatus:
        assert f"'{status.value}'" in job_status_sql


def validate_migration_graph() -> None:
    """Comprueba una sola línea DBI hasta la revisión de trabajos."""

    config = Config(str(BACKEND_ROOT / "dbi_alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_bases() == ["dbi_0001_baseline"]
    assert len(scripts.get_heads()) == 1
    revision = scripts.get_revision("dbi_0003_analysis_jobs")
    assert revision is not None
    assert revision.down_revision == "dbi_0002_agricultural_domain"


def validate_offline_sql() -> None:
    """Genera el historial DBI completo sin abrir conexiones."""

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
    assert "uq_dbi_analysis_jobs_tenant_request" in sql
    assert "uq_dbi_analysis_job_attempts_job_number" in sql
    for forbidden in (
        "create extension",
        "postgis",
        "geometry(",
        "geography(",
        "gen_random_uuid",
        "uuid_generate",
        "insert into dbi_",
        "create table users",
        "create table companies",
        "create table documents",
    ):
        assert forbidden not in sql


def validate_sources() -> None:
    """Bloquea conexiones, infraestructura y acoplamiento heredado."""

    model_source = (
        BACKEND_ROOT
        / "app"
        / "dbi"
        / "models"
        / "analysis_jobs.py"
    ).read_text(encoding="utf-8").lower()
    migration_source = (
        BACKEND_ROOT
        / "dbi_alembic"
        / "versions"
        / "20260729_03_analysis_jobs.py"
    ).read_text(encoding="utf-8").lower()

    for forbidden in (
        "create_engine",
        "sessionmaker",
        "app.models.",
        "celery",
        "redis",
        "rabbit",
        "boto",
        "google.cloud.storage",
        "pipeline_orchestrator",
        "run_full_pipeline",
        "postgis",
        "geometry",
        "geography",
    ):
        assert forbidden not in model_source

    assert "create extension" not in migration_source
    assert "op.bulk_insert" not in migration_source
    assert "op.execute" not in migration_source


def main() -> None:
    """Ejecuta todas las barreras de persistencia del trabajo."""

    validate_metadata()
    validate_constraints()
    validate_migration_graph()
    validate_offline_sql()
    validate_sources()
    print("Persistencia de trabajos DBI: validación offline aprobada.")


if __name__ == "__main__":
    main()
