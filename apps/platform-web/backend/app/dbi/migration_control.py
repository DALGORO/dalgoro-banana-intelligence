"""Controles puros para operaciones de migración DBI.

Este módulo no abre conexiones ni ejecuta Alembic. Centraliza las barreras que
se deben superar antes de cualquier operación ``plan``, ``verify`` o ``apply``.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Final

from app.db.dbi_config import DBI_DATABASE_NAMES, DBIDatabaseConfig

DBI_MIGRATION_LOCK_NAMESPACE: Final[str] = "dalgoro-dbi-migrations-v1"
DBI_CI_ENVIRONMENT: Final[str] = "test"
DBI_PRODUCTION_ENVIRONMENT: Final[str] = "production"


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
