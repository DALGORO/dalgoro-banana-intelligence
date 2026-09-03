"""Controles puros para operaciones de migración DBI.

Este módulo no abre conexiones ni ejecuta Alembic. Centraliza las barreras que
se deben superar antes de cualquier operación ``plan``, ``verify`` o ``apply``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Final

from app.db.dbi_config import DBI_DATABASE_NAMES, DBIDatabaseConfig

DBI_MIGRATION_LOCK_NAMESPACE: Final[str] = "dalgoro-dbi-migrations-v1"
DBI_CI_ENVIRONMENT: Final[str] = "test"
DBI_PRODUCTION_ENVIRONMENT: Final[str] = "production"
DBI_GITHUB_REPOSITORY: Final[str] = "DALGORO/dalgoro-banana-intelligence"
DBI_GITHUB_WORKFLOW: Final[str] = "DBI migrations integration"
DBI_GITHUB_WORKFLOW_PATH: Final[str] = (
    ".github/workflows/dbi-migration-integration.yml"
)
DBI_GITHUB_JOB: Final[str] = "dbi-postgis-integration"
DBI_ASSET_GITHUB_WORKFLOW: Final[str] = "DBI asset integration"
DBI_ASSET_GITHUB_WORKFLOW_PATH: Final[str] = (
    ".github/workflows/dbi-asset-integration.yml"
)
DBI_ASSET_GITHUB_JOB: Final[str] = "dbi-asset-integration"
DBI_ANALYSIS_JOB_GITHUB_WORKFLOW: Final[str] = "DBI analysis job integration"
DBI_ANALYSIS_JOB_GITHUB_WORKFLOW_PATH: Final[str] = (
    ".github/workflows/dbi-analysis-job-integration.yml"
)
DBI_ANALYSIS_JOB_GITHUB_JOB: Final[str] = "dbi-analysis-job-integration"
DBI_AUTHORIZED_GITHUB_WORKFLOWS: Final[
    frozenset[tuple[str, str, str]]
] = frozenset(
    {
        (
            DBI_GITHUB_WORKFLOW,
            DBI_GITHUB_WORKFLOW_PATH,
            DBI_GITHUB_JOB,
        ),
        (
            DBI_ASSET_GITHUB_WORKFLOW,
            DBI_ASSET_GITHUB_WORKFLOW_PATH,
            DBI_ASSET_GITHUB_JOB,
        ),
        (
            DBI_ANALYSIS_JOB_GITHUB_WORKFLOW,
            DBI_ANALYSIS_JOB_GITHUB_WORKFLOW_PATH,
            DBI_ANALYSIS_JOB_GITHUB_JOB,
        ),
    }
)
DBI_GITHUB_EVENTS: Final[frozenset[str]] = frozenset(
    {"pull_request", "push", "workflow_dispatch"}
)


class DBIMigrationControlError(RuntimeError):
    """Indica que una barrera de migración DBI no fue satisfecha."""


@dataclass(frozen=True)
class DBIMigrationTarget:
    """Destino validado para una operación DBI, sin credenciales renderizadas."""

    environment: str
    database_name: str
    username: str
    expected_migrator_role: str

    @property
    def apply_confirmation(self) -> str:
        """Frase exacta requerida para habilitar una aplicación real."""

        return f"APPLY {self.database_name}"


def expected_migrator_role(database_name: str) -> str:
    """Deriva el rol migrador canónico de una base DBI autorizada."""

    return f"{database_name}_migrator"


def _is_authorized_workflow_identity(values: Mapping[str, str]) -> bool:
    """Exige una combinación exacta e inseparable de nombre, ruta y job."""

    workflow_ref = values.get("GITHUB_WORKFLOW_REF", "")
    workflow = values.get("GITHUB_WORKFLOW")
    job = values.get("GITHUB_JOB")
    return any(
        workflow == authorized_workflow
        and job == authorized_job
        and workflow_ref.startswith(
            f"{DBI_GITHUB_REPOSITORY}/{authorized_path}@"
        )
        for authorized_workflow, authorized_path, authorized_job
        in DBI_AUTHORIZED_GITHUB_WORKFLOWS
    )


def is_authorized_github_actions_runtime(
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Comprueba los marcadores inmutables de un workflow DBI autorizado."""

    values = os.environ if environment is None else environment
    return (
        values.get("GITHUB_ACTIONS") == "true"
        and values.get("CI") == "true"
        and values.get("GITHUB_SERVER_URL") == "https://github.com"
        and values.get("GITHUB_REPOSITORY") == DBI_GITHUB_REPOSITORY
        and _is_authorized_workflow_identity(values)
        and values.get("GITHUB_EVENT_NAME") in DBI_GITHUB_EVENTS
        and values.get("RUNNER_ENVIRONMENT") == "github-hosted"
    )


def require_authorized_github_actions_runtime(
    environment: Mapping[str, str] | None = None,
) -> None:
    """Falla cerrado fuera del workflow y job DBI autorizados."""

    if not is_authorized_github_actions_runtime(environment):
        raise DBIMigrationControlError(
            "Apply DBI exige el workflow y job autorizados de GitHub Actions."
        )


def validate_migration_target(
    config: DBIDatabaseConfig,
    *,
    running_in_ci: bool,
) -> DBIMigrationTarget:
    """Valida ambiente, base y rol antes de cualquier operación de migración."""

    if config.environment == DBI_PRODUCTION_ENVIRONMENT:
        raise DBIMigrationControlError(
            "Las migraciones de producción están bloqueadas por esta herramienta."
        )

    expected_database = DBI_DATABASE_NAMES.get(config.environment)
    if expected_database is None or config.database_name != expected_database:
        raise DBIMigrationControlError(
            "La base DBI no corresponde al ambiente autorizado."
        )

    if running_in_ci and config.environment != DBI_CI_ENVIRONMENT:
        raise DBIMigrationControlError(
            "CI solo puede operar contra el ambiente DBI test."
        )

    username = (config.url.username or "").strip()
    migrator_role = expected_migrator_role(expected_database)
    if username != migrator_role:
        raise DBIMigrationControlError(
            "La conexión DBI debe usar el rol migrador autorizado del ambiente."
        )

    return DBIMigrationTarget(
        environment=config.environment,
        database_name=expected_database,
        username=username,
        expected_migrator_role=migrator_role,
    )


def require_apply_confirmation(
    target: DBIMigrationTarget,
    supplied_confirmation: str | None,
) -> None:
    """Exige una confirmación inequívoca antes de permitir ``apply``."""

    if supplied_confirmation != target.apply_confirmation:
        raise DBIMigrationControlError(
            "Confirmación de apply ausente o incorrecta."
        )


def plan_fingerprint(sql: str) -> str:
    """Calcula una huella SHA-256 estable del SQL offline generado."""

    normalized = sql.replace("\r\n", "\n").replace("\r", "\n")
    return sha256(normalized.encode("utf-8")).hexdigest()


def advisory_lock_key() -> int:
    """Devuelve una clave advisory lock PostgreSQL estable y con signo."""

    raw = sha256(DBI_MIGRATION_LOCK_NAMESPACE.encode("utf-8")).digest()[:8]
    return int.from_bytes(raw, byteorder="big", signed=True)
