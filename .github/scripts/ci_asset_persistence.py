"""Valida activos y artefactos DBI sin conectar almacenamiento o PostgreSQL."""

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
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.dbi_base import DBIBase  # noqa: E402
from app.dbi.models import (  # noqa: E402
    AnalysisArtifact,
    AnalysisInputAsset,
    AnalysisJob,
    AnalysisJobAttempt,
    Campaign,
    Farm,
    Plot,
)
from app.schemas.dbi_analysis_jobs import (  # noqa: E402
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ArtifactRole,
    PipelineStage,
)

EXPECTED_TABLES = {
    "dbi_farms",
    "dbi_plots",
    "dbi_campaigns",
    "dbi_analysis_jobs",
    "dbi_analysis_job_attempts",
    "dbi_analysis_input_assets",
    "dbi_analysis_artifacts",
}
EXPECTED_COLUMNS = {
    "dbi_analysis_input_assets": {
        "id",
        "tenant_ref",
        "farm_id",
        "plot_id",
        "asset_kind",
        "status",
        "object_key",
        "content_type",
        "size_bytes",
        "sha256",
        "crs",
        "created_by_ref",
        "verified_at",
        "created_at",
        "updated_at",
    },
    "dbi_analysis_artifacts": {
        "id",
        "job_id",
        "attempt_id",
        "manifest_schema_version",
        "role",
        "object_key",
        "content_type",
        "size_bytes",
        "sha256",
        "produced_by_stage",
        "crs",
        "created_at",
    },
}


def validate_metadata() -> None:
    """Comprueba tablas, columnas, relaciones y aislamiento DBI."""

    assert {
        Farm,
        Plot,
        Campaign,
        AnalysisJob,
        AnalysisJobAttempt,
        AnalysisInputAsset,
        AnalysisArtifact,
    }
    assert EXPECTED_TABLES.issubset(DBIBase.metadata.tables)

    for table_name, columns in EXPECTED_COLUMNS.items():
        assert set(DBIBase.metadata.tables[table_name].columns.keys()) == columns

    input_targets = {
        foreign_key.target_fullname
        for foreign_key in DBIBase.metadata.tables[
            "dbi_analysis_input_assets"
        ].foreign_keys
    }
    artifact_targets = {
        foreign_key.target_fullname
        for foreign_key in DBIBase.metadata.tables[
            "dbi_analysis_artifacts"
        ].foreign_keys
    }
    assert input_targets == {"dbi_farms.id", "dbi_plots.id"}
    assert artifact_targets == {
        "dbi_analysis_job_attempts.id",
        "dbi_analysis_job_attempts.job_id",
    }
    assert AnalysisArtifact.attempt.property.mapper.class_ is AnalysisJobAttempt


def _named_constraints() -> dict[str, object]:
    """Agrupa restricciones por nombre para aserciones focalizadas."""

    return {
        constraint.name: constraint
        for table in DBIBase.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name is not None
    }


def validate_constraints() -> None:
    """Comprueba pertenencia, referencias, roles, etapas y metadatos."""

    constraints = _named_constraints()
    expected = {
        "uq_dbi_analysis_job_attempts_id_job",
        "uq_dbi_analysis_input_assets_tenant_object",
        "ck_dbi_analysis_input_assets_kind",
        "ck_dbi_analysis_input_assets_status",
        "ck_dbi_analysis_input_assets_positive_size",
        "ck_dbi_analysis_input_assets_sha256",
        "ck_dbi_analysis_input_assets_content_type",
        "ck_dbi_analysis_input_assets_object_key",
        "ck_dbi_analysis_input_assets_verification",
        "uq_dbi_analysis_artifacts_object_key",
        "fk_dbi_analysis_artifacts_attempt_job_dbi_analysis_job_attempts",
        "ck_dbi_analysis_artifacts_schema_version",
        "ck_dbi_analysis_artifacts_role",
        "ck_dbi_analysis_artifacts_stage",
        "ck_dbi_analysis_artifacts_positive_size",
        "ck_dbi_analysis_artifacts_sha256",
        "ck_dbi_analysis_artifacts_content_type",
        "ck_dbi_analysis_artifacts_object_key",
    }
    assert expected.issubset(constraints)

    attempt_identity = constraints[
        "uq_dbi_analysis_job_attempts_id_job"
    ]
    assert isinstance(attempt_identity, UniqueConstraint)
    assert [column.name for column in attempt_identity.columns] == [
        "id",
        "job_id",
    ]

    artifact_link = constraints[
        "fk_dbi_analysis_artifacts_attempt_job_dbi_analysis_job_attempts"
    ]
    assert isinstance(artifact_link, ForeignKeyConstraint)
    assert [column.name for column in artifact_link.columns] == [
        "attempt_id",
        "job_id",
    ]
    assert [
        element.target_fullname for element in artifact_link.elements
    ] == [
        "dbi_analysis_job_attempts.id",
        "dbi_analysis_job_attempts.job_id",
    ]

    role_sql = str(
        constraints["ck_dbi_analysis_artifacts_role"].sqltext
    )
    stage_sql = str(
        constraints["ck_dbi_analysis_artifacts_stage"].sqltext
    )
    for role in ArtifactRole:
        assert f"'{role.value}'" in role_sql
    for stage in PipelineStage:
        assert f"'{stage.value}'" in stage_sql

    schema_sql = str(
        constraints["ck_dbi_analysis_artifacts_schema_version"].sqltext
    )
    assert ARTIFACT_MANIFEST_SCHEMA_VERSION in schema_sql

    for prefix in (
        "ck_dbi_analysis_input_assets",
        "ck_dbi_analysis_artifacts",
    ):
        object_key_sql = str(
            constraints[f"{prefix}_object_key"].sqltext
        )
        assert "object_key ~" in object_key_sql
        assert "object_key !~" in object_key_sql
        assert "object_key not like '%//%'" in object_key_sql.lower()
        assert "{0,511}" not in object_key_sql
        assert "[A-Za-z0-9._/-]*" in object_key_sql


def validate_migration_graph() -> None:
    """Comprueba una sola línea DBI hasta activos y artefactos."""

    config = Config(str(BACKEND_ROOT / "dbi_alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_bases() == ["dbi_0001_baseline"]
    heads = scripts.get_heads()
    assert heads == ["dbi_0014_analysis_results"]
    lineage = {
        revision.revision
        for revision in scripts.iterate_revisions(heads[0], "base")
    }
    assert "dbi_0004_assets_artifacts" in lineage
    revision = scripts.get_revision("dbi_0004_assets_artifacts")
    assert revision is not None
    assert revision.down_revision == "dbi_0003_analysis_jobs"
    repair = scripts.get_revision("dbi_0009_object_key_check")
    assert repair is not None
    assert repair.down_revision == "dbi_0008_scope_hierarchy"


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
    assert "uq_dbi_analysis_job_attempts_id_job" in sql
    assert "artifact-manifest.v1" in sql
    assert "dbi_0009_object_key_check" in sql
    assert "drop constraint ck_dbi_analysis_input_assets_object_key" in sql
    assert "drop constraint ck_dbi_analysis_artifacts_object_key" in sql
    for forbidden in (
        "create extension",
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
    """Bloquea sesiones, SDK de objetos, URLs y ejecución del worker."""

    model_source = (
        BACKEND_ROOT / "app" / "dbi" / "models" / "assets.py"
    ).read_text(encoding="utf-8").lower()
    migration_source = (
        BACKEND_ROOT
        / "dbi_alembic"
        / "versions"
        / "20260729_04_assets_artifacts.py"
    ).read_text(encoding="utf-8").lower()
    repair_source = (
        BACKEND_ROOT
        / "dbi_alembic"
        / "versions"
        / "20260803_09_object_key_check.py"
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
        "azure.storage",
        "pipeline_orchestrator",
        "run_full_pipeline",
        "presigned",
        "signed_url",
        "postgis",
        "geometry",
        "geography",
    ):
        assert forbidden not in model_source

    assert "create extension" not in migration_source
    assert "op.bulk_insert" not in migration_source
    assert "op.execute" not in migration_source
    assert "geometry" not in migration_source
    assert "geography" not in migration_source
    assert "postgis" not in migration_source
    assert 'revision: str = "dbi_0009_object_key_check"' in repair_source
    assert '"dbi_0008_scope_hierarchy"' in repair_source
    assert "[a-za-z0-9._/-]*$" in repair_source
    assert "op.create_check_constraint" in repair_source
    assert "op.execute" not in repair_source


def main() -> None:
    """Ejecuta todas las barreras de activos y artefactos."""

    validate_metadata()
    validate_constraints()
    validate_migration_graph()
    validate_offline_sql()
    validate_sources()
    print("Activos y artefactos DBI: validación offline aprobada.")


if __name__ == "__main__":
    main()
