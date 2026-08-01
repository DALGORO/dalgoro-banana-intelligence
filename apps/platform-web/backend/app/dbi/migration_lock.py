"""Bloqueo de sesión PostgreSQL para serializar migraciones DBI.

El módulo recibe una conexión ya abierta y no crea motores, sesiones ni
credenciales. El bloqueo debe mantenerse en la misma conexión durante toda la
operación protegida.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Protocol

from sqlalchemy import text

from app.dbi.migration_control import (
    DBIMigrationControlError,
    advisory_lock_key,
)


class DBIMigrationLockConnection(Protocol):
    """Contrato mínimo de una conexión capaz de ejecutar SQL escalar."""

    def execute(self, statement, parameters=None): ...


_LOCK_SQL = text("SELECT pg_try_advisory_lock(:lock_key)")
_UNLOCK_SQL = text("SELECT pg_advisory_unlock(:lock_key)")


def _scalar_boolean(result) -> bool:
    """Convierte de forma estricta el resultado escalar de PostgreSQL."""

    value = result.scalar_one()
    if not isinstance(value, bool):
        raise DBIMigrationControlError(
            "PostgreSQL devolvió una respuesta inválida para el advisory lock."
        )
    return value


def acquire_migration_lock(connection: DBIMigrationLockConnection) -> int:
    """Adquiere sin espera el bloqueo exclusivo de migraciones DBI."""

    lock_key = advisory_lock_key()
    acquired = _scalar_boolean(
        connection.execute(_LOCK_SQL, {"lock_key": lock_key})
    )
    if not acquired:
        raise DBIMigrationControlError(
            "Ya existe otra operación de migración DBI en ejecución."
        )
    return lock_key


def release_migration_lock(
    connection: DBIMigrationLockConnection,
    lock_key: int,
) -> None:
    """Libera el bloqueo y falla cerrado si la sesión no lo poseía."""

    released = _scalar_boolean(
        connection.execute(_UNLOCK_SQL, {"lock_key": lock_key})
    )
    if not released:
        raise DBIMigrationControlError(
            "No fue posible confirmar la liberación del bloqueo DBI."
        )


@contextmanager
def migration_lock(
    connection: DBIMigrationLockConnection,
) -> Iterator[int]:
    """Mantiene el advisory lock y garantiza un intento de liberación."""

    lock_key = acquire_migration_lock(connection)
    operation_error: BaseException | None = None
    try:
        yield lock_key
    except BaseException as exc:
        operation_error = exc
        raise
    finally:
        try:
            release_migration_lock(connection, lock_key)
        except DBIMigrationControlError:
            if operation_error is None:
                raise
