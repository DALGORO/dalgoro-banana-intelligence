"""Métricas no sensibles para cualquier adaptador del puerto privado DBI."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import BinaryIO, Iterator

from app.dbi.storage_contracts import (
    DBIPrivateObjectStore,
    DBIStorageAccessMode,
    DBIStorageAddress,
    DBIStorageConflict,
    DBIStorageDenied,
    DBIStorageIntegrityError,
    DBIStorageNotFound,
    DBIStorageObjectMetadata,
    DBIStorageObjectRecord,
    DBIStorageTemporaryGrant,
    DBIStorageWriteRequest,
    DBIStorageWriteResult,
)


@dataclass(frozen=True, slots=True)
class DBIStorageMetricsSnapshot:
    """Contadores agregados sin claves, contenido, URLs o credenciales."""

    put_attempts: int
    created_objects: int
    idempotent_writes: int
    stat_attempts: int
    read_attempts: int
    retire_attempts: int
    retired_objects: int
    idempotent_retires: int
    temporary_access_attempts: int
    temporary_grants: int
    bytes_verified: int
    bytes_created: int
    bytes_opened: int
    denied_errors: int
    conflict_errors: int
    not_found_errors: int
    integrity_errors: int


@dataclass(slots=True)
class _MutableMetrics:
    put_attempts: int = 0
    created_objects: int = 0
    idempotent_writes: int = 0
    stat_attempts: int = 0
    read_attempts: int = 0
    retire_attempts: int = 0
    retired_objects: int = 0
    idempotent_retires: int = 0
    temporary_access_attempts: int = 0
    temporary_grants: int = 0
    bytes_verified: int = 0
    bytes_created: int = 0
    bytes_opened: int = 0
    denied_errors: int = 0
    conflict_errors: int = 0
    not_found_errors: int = 0
    integrity_errors: int = 0


class DBIMeteredObjectStore:
    """Decorador proveedor-neutral que agrega únicamente contadores seguros."""

    def __init__(self, delegate: DBIPrivateObjectStore) -> None:
        if delegate is None:
            raise TypeError("delegate es obligatorio.")
        self._delegate = delegate
        self._metrics = _MutableMetrics()
        self._lock = RLock()

    def _increment(self, field_name: str, value: int = 1) -> None:
        with self._lock:
            current = getattr(self._metrics, field_name)
            setattr(self._metrics, field_name, current + value)

    def _record_error(self, error: Exception) -> None:
        if isinstance(error, DBIStorageDenied):
            self._increment("denied_errors")
        elif isinstance(error, DBIStorageIntegrityError):
            self._increment("integrity_errors")
        elif isinstance(error, DBIStorageNotFound):
            self._increment("not_found_errors")
        elif isinstance(error, DBIStorageConflict):
            self._increment("conflict_errors")

    def put(
        self,
        request: DBIStorageWriteRequest,
        content: BinaryIO,
    ) -> DBIStorageWriteResult:
        self._increment("put_attempts")
        try:
            result = self._delegate.put(request, content)
        except (
            DBIStorageDenied,
            DBIStorageIntegrityError,
            DBIStorageNotFound,
            DBIStorageConflict,
        ) as error:
            self._record_error(error)
            raise

        self._increment("bytes_verified", result.record.metadata.size_bytes)
        if result.created:
            self._increment("created_objects")
            self._increment("bytes_created", result.record.metadata.size_bytes)
        else:
            self._increment("idempotent_writes")
        return result

    def stat(self, address: DBIStorageAddress) -> DBIStorageObjectRecord:
        self._increment("stat_attempts")
        try:
            return self._delegate.stat(address)
        except (
            DBIStorageDenied,
            DBIStorageIntegrityError,
            DBIStorageNotFound,
            DBIStorageConflict,
        ) as error:
            self._record_error(error)
            raise

    @contextmanager
    def open_read(self, address: DBIStorageAddress) -> Iterator[BinaryIO]:
        """Mide adquisición/cierre del adaptador, no errores del consumidor."""

        self._increment("read_attempts")
        consumer_error = False
        try:
            record = self._delegate.stat(address)
            with self._delegate.open_read(address) as stream:
                self._increment("bytes_opened", record.metadata.size_bytes)
                try:
                    yield stream
                except BaseException:
                    consumer_error = True
                    raise
        except (
            DBIStorageDenied,
            DBIStorageIntegrityError,
            DBIStorageNotFound,
            DBIStorageConflict,
        ) as error:
            if not consumer_error:
                self._record_error(error)
            raise

    def retire(
        self,
        address: DBIStorageAddress,
        *,
        retired_at: datetime,
    ) -> bool:
        self._increment("retire_attempts")
        try:
            retired = self._delegate.retire(
                address,
                retired_at=retired_at,
            )
        except (
            DBIStorageDenied,
            DBIStorageIntegrityError,
            DBIStorageNotFound,
            DBIStorageConflict,
        ) as error:
            self._record_error(error)
            raise

        if retired:
            self._increment("retired_objects")
        else:
            self._increment("idempotent_retires")
        return retired

    def issue_temporary_access(
        self,
        metadata: DBIStorageObjectMetadata,
        *,
        mode: DBIStorageAccessMode,
        issued_at: datetime,
        expires_at: datetime,
    ) -> DBIStorageTemporaryGrant:
        self._increment("temporary_access_attempts")
        try:
            grant = self._delegate.issue_temporary_access(
                metadata,
                mode=mode,
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except (
            DBIStorageDenied,
            DBIStorageIntegrityError,
            DBIStorageNotFound,
            DBIStorageConflict,
        ) as error:
            self._record_error(error)
            raise

        self._increment("temporary_grants")
        return grant

    def metrics_snapshot(self) -> DBIStorageMetricsSnapshot:
        """Copia atómica de contadores agregados sin datos de objetos."""

        with self._lock:
            return DBIStorageMetricsSnapshot(
                put_attempts=self._metrics.put_attempts,
                created_objects=self._metrics.created_objects,
                idempotent_writes=self._metrics.idempotent_writes,
                stat_attempts=self._metrics.stat_attempts,
                read_attempts=self._metrics.read_attempts,
                retire_attempts=self._metrics.retire_attempts,
                retired_objects=self._metrics.retired_objects,
                idempotent_retires=self._metrics.idempotent_retires,
                temporary_access_attempts=(
                    self._metrics.temporary_access_attempts
                ),
                temporary_grants=self._metrics.temporary_grants,
                bytes_verified=self._metrics.bytes_verified,
                bytes_created=self._metrics.bytes_created,
                bytes_opened=self._metrics.bytes_opened,
                denied_errors=self._metrics.denied_errors,
                conflict_errors=self._metrics.conflict_errors,
                not_found_errors=self._metrics.not_found_errors,
                integrity_errors=self._metrics.integrity_errors,
            )
