"""Adaptador en memoria para probar la semántica del puerto privado DBI."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from secrets import token_urlsafe
from threading import RLock
from typing import BinaryIO, Callable, Iterator

from app.dbi.storage_contracts import (
    DBIStorageAccessMode,
    DBIStorageAddress,
    DBIStorageConflict,
    DBIStorageIntegrityError,
    DBIStorageNotFound,
    DBIStorageObjectRecord,
    DBIStorageObjectState,
    DBIStorageTemporaryGrant,
    DBIStorageWriteRequest,
    DBIStorageWriteResult,
)
from app.dbi.storage_policy import DBIStoragePolicy

_DEFAULT_MAX_OBJECT_SIZE_BYTES = 16 * 1024 * 1024
_READ_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True, slots=True)
class _StoredObject:
    record: DBIStorageObjectRecord
    content: bytes


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _opaque_grant_ref() -> str:
    return token_urlsafe(32)


def _normalized_timestamp(value: object, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIStorageConflict(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


class DBIInMemoryObjectStore:
    """Doble determinista sin red, disco, SDK o autoridad externa.

    Conserva objetos retirados internamente para reproducir borrado lógico, pero
    ``stat``, ``open_read`` y acceso temporal los tratan como no disponibles.
    No existe operación de reactivación o purga física.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utc_now,
        grant_ref_factory: Callable[[], str] = _opaque_grant_ref,
        max_object_size_bytes: int = _DEFAULT_MAX_OBJECT_SIZE_BYTES,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock debe ser invocable.")
        if not callable(grant_ref_factory):
            raise TypeError("grant_ref_factory debe ser invocable.")
        if (
            not isinstance(max_object_size_bytes, int)
            or isinstance(max_object_size_bytes, bool)
            or max_object_size_bytes <= 0
        ):
            raise ValueError("max_object_size_bytes debe ser un entero positivo.")
        self._clock = clock
        self._grant_ref_factory = grant_ref_factory
        self._max_object_size_bytes = max_object_size_bytes
        self._objects: dict[str, _StoredObject] = {}
        self._lock = RLock()

    def _created_at(self) -> datetime:
        return _normalized_timestamp(self._clock(), field_name="clock")

    def _active_object(self, address: DBIStorageAddress) -> _StoredObject:
        canonical = DBIStoragePolicy.validate_address(address)
        with self._lock:
            stored = self._objects.get(canonical.object_key)
            if (
                stored is None
                or stored.record.metadata.address != canonical
                or stored.record.state is not DBIStorageObjectState.ACTIVE
            ):
                raise DBIStorageNotFound()
            return stored

    def _read_verified_content(
        self,
        content: BinaryIO,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> bytes:
        read = getattr(content, "read", None)
        if not callable(read):
            raise DBIStorageIntegrityError("content debe ser un flujo binario.")
        if expected_size > self._max_object_size_bytes:
            raise DBIStorageIntegrityError(
                "El objeto excede el límite del adaptador en memoria."
            )

        digest = sha256()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = read(min(_READ_CHUNK_SIZE, expected_size - total + 1))
            if chunk in (b"", None):
                break
            if not isinstance(chunk, bytes):
                raise DBIStorageIntegrityError(
                    "El flujo debe devolver exclusivamente bytes."
                )
            total += len(chunk)
            if total > expected_size:
                raise DBIStorageIntegrityError(
                    "El contenido excede el tamaño declarado."
                )
            digest.update(chunk)
            chunks.append(chunk)

        if total != expected_size:
            raise DBIStorageIntegrityError(
                "El contenido no coincide con el tamaño declarado."
            )
        if digest.hexdigest() != expected_sha256:
            raise DBIStorageIntegrityError(
                "El contenido no coincide con la huella declarada."
            )
        return b"".join(chunks)

    def put(
        self,
        request: DBIStorageWriteRequest,
        content: BinaryIO,
    ) -> DBIStorageWriteResult:
        """Escribe contenido verificado o acepta un reintento exactamente igual."""

        if not isinstance(request, DBIStorageWriteRequest):
            raise DBIStorageConflict("request debe ser DBIStorageWriteRequest.")
        metadata = DBIStoragePolicy.validate_metadata(request.metadata)
        payload = self._read_verified_content(
            content,
            expected_size=metadata.size_bytes,
            expected_sha256=metadata.sha256,
        )

        with self._lock:
            existing = self._objects.get(metadata.address.object_key)
            if existing is not None:
                if existing.record.state is DBIStorageObjectState.RETIRED:
                    raise DBIStorageConflict(
                        "Un objeto retirado no puede reactivarse implícitamente."
                    )
                if (
                    existing.record.metadata != metadata
                    or existing.content != payload
                ):
                    raise DBIStorageConflict(
                        "La clave existe con identidad o contenido divergente."
                    )
                return DBIStorageWriteResult(
                    record=existing.record,
                    created=False,
                )

            record = DBIStorageObjectRecord(
                metadata=metadata,
                state=DBIStorageObjectState.ACTIVE,
                created_at=self._created_at(),
            )
            DBIStoragePolicy.validate_record(record)
            self._objects[metadata.address.object_key] = _StoredObject(
                record=record,
                content=payload,
            )
            return DBIStorageWriteResult(record=record, created=True)

    def stat(self, address: DBIStorageAddress) -> DBIStorageObjectRecord:
        """Devuelve metadatos de un objeto activo sin contenido o ubicación."""

        return self._active_object(address).record

    @contextmanager
    def open_read(self, address: DBIStorageAddress) -> Iterator[BinaryIO]:
        """Entrega una copia binaria aislada del objeto activo."""

        payload = self._active_object(address).content
        stream = BytesIO(payload)
        try:
            yield stream
        finally:
            stream.close()

    def retire(
        self,
        address: DBIStorageAddress,
        *,
        retired_at: datetime,
    ) -> bool:
        """Retira lógicamente un objeto; repetir el retiro es un no-op."""

        canonical = DBIStoragePolicy.validate_address(address)
        timestamp = _normalized_timestamp(retired_at, field_name="retired_at")
        with self._lock:
            existing = self._objects.get(canonical.object_key)
            if existing is None or existing.record.metadata.address != canonical:
                raise DBIStorageNotFound()
            if existing.record.state is DBIStorageObjectState.RETIRED:
                return False
            retired_record = replace(
                existing.record,
                state=DBIStorageObjectState.RETIRED,
                retired_at=timestamp,
            )
            DBIStoragePolicy.validate_record(retired_record)
            self._objects[canonical.object_key] = _StoredObject(
                record=retired_record,
                content=existing.content,
            )
            return True

    def issue_temporary_access(
        self,
        address: DBIStorageAddress,
        *,
        mode: DBIStorageAccessMode,
        issued_at: datetime,
        expires_at: datetime,
    ) -> DBIStorageTemporaryGrant:
        """Emite una referencia efímera solo para objetos activos ya verificados."""

        if not isinstance(mode, DBIStorageAccessMode):
            raise DBIStorageConflict("mode debe ser DBIStorageAccessMode.")
        active = self._active_object(address)
        issued, expires = DBIStoragePolicy.validate_access_window(
            issued_at=issued_at,
            expires_at=expires_at,
        )
        grant = DBIStorageTemporaryGrant(
            grant_ref=self._grant_ref_factory(),
            address=active.record.metadata.address,
            mode=mode,
            issued_at=issued,
            expires_at=expires,
        )
        return DBIStoragePolicy.validate_grant(grant)
