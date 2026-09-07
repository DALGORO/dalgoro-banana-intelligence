"""Almacenamiento privado persistente en disco para operación DBI local."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from threading import RLock
from typing import BinaryIO, Callable, Iterator

from app.dbi.storage_contracts import (
    MAX_STORAGE_RANGE_BYTES,
    DBIStorageAccessMode,
    DBIStorageAddress,
    DBIStorageConflict,
    DBIStorageIntegrityError,
    DBIStorageNotFound,
    DBIStorageObjectMetadata,
    DBIStorageObjectRecord,
    DBIStorageObjectState,
    DBIStorageRangeRead,
    DBIStorageTemporaryGrant,
    DBIStorageWriteRequest,
    DBIStorageWriteResult,
)
from app.dbi.storage_policy import DBIStoragePolicy


_READ_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class DBILocalResolvedTemporaryAccess:
    """Grant resuelto para el transporte HTTP local."""

    grant: DBIStorageTemporaryGrant
    method: str
    url: str
    headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _StoredGrant:
    access: DBILocalResolvedTemporaryAccess


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _opaque_grant_ref() -> str:
    return token_urlsafe(32)


def _utc(value: object, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIStorageConflict(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _validated_range(
    *,
    size_bytes: int,
    start: int,
    end_exclusive: int,
) -> tuple[int, int]:
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end_exclusive, int)
        or isinstance(end_exclusive, bool)
        or start < 0
        or end_exclusive <= start
        or end_exclusive > size_bytes
        or end_exclusive - start > MAX_STORAGE_RANGE_BYTES
    ):
        raise DBIStorageIntegrityError("rango privado fuera de política.")
    return start, end_exclusive


class DBILocalObjectStore:
    """Object store privado y persistente para la estación Windows DBI.

    Los objetos se guardan debajo de una raíz controlada por la aplicación.
    Las claves siguen siendo derivadas exclusivamente por ``DBIStoragePolicy``.
    No se exponen rutas físicas a clientes.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        upload_base_path: str = "/api/v1/dbi/local-storage/grants",
        clock: Callable[[], datetime] = _utc_now,
        grant_ref_factory: Callable[[], str] = _opaque_grant_ref,
    ) -> None:
        root_path = Path(root).expanduser()
        if not str(root_path).strip():
            raise ValueError("root no puede estar vacío.")
        if not upload_base_path.startswith("/") or ".." in upload_base_path:
            raise ValueError("upload_base_path debe ser una ruta HTTP relativa canónica.")
        if not callable(clock) or not callable(grant_ref_factory):
            raise TypeError("clock y grant_ref_factory deben ser invocables.")

        self._root = root_path.resolve()
        self._objects_root = self._root / "objects"
        self._metadata_root = self._root / "metadata"
        self._staging_root = self._root / "staging"
        for directory in (
            self._root,
            self._objects_root,
            self._metadata_root,
            self._staging_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self._upload_base_path = upload_base_path.rstrip("/")
        self._clock = clock
        self._grant_ref_factory = grant_ref_factory
        self._grants: dict[str, _StoredGrant] = {}
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def staging_directory(self) -> Path:
        return self._staging_root

    def _created_at(self) -> datetime:
        return _utc(self._clock(), field_name="clock")

    def _paths(self, address: DBIStorageAddress) -> tuple[Path, Path]:
        canonical = DBIStoragePolicy.validate_address(address)
        key = Path(*canonical.object_key.split("/"))
        object_path = (self._objects_root / key).resolve()
        metadata_path = (self._metadata_root / key).with_suffix(".json").resolve()
        if self._objects_root not in object_path.parents:
            raise DBIStorageConflict("clave de objeto fuera de la raíz local.")
        if self._metadata_root not in metadata_path.parents:
            raise DBIStorageConflict("metadata fuera de la raíz local.")
        return object_path, metadata_path

    def _write_sidecar(self, path: Path, record: DBIStorageObjectRecord) -> None:
        payload = {
            "tenant_ref": record.metadata.address.tenant_ref,
            "purpose": record.metadata.address.purpose.value,
            "object_id": str(record.metadata.address.object_id),
            "object_key": record.metadata.address.object_key,
            "content_type": record.metadata.content_type,
            "size_bytes": record.metadata.size_bytes,
            "sha256": record.metadata.sha256,
            "state": record.state.value,
            "created_at": record.created_at.isoformat(),
            "retired_at": (
                record.retired_at.isoformat() if record.retired_at is not None else None
            ),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{token_urlsafe(8)}.tmp")
        try:
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def _load_record(
        self,
        address: DBIStorageAddress,
        *,
        include_retired: bool,
    ) -> DBIStorageObjectRecord:
        canonical = DBIStoragePolicy.validate_address(address)
        object_path, metadata_path = self._paths(canonical)
        if not object_path.is_file() or not metadata_path.is_file():
            raise DBIStorageNotFound()

        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
            if (
                raw.get("tenant_ref") != canonical.tenant_ref
                or raw.get("purpose") != canonical.purpose.value
                or raw.get("object_id") != str(canonical.object_id)
                or raw.get("object_key") != canonical.object_key
            ):
                raise DBIStorageIntegrityError(
                    "La metadata local no coincide con la dirección solicitada."
                )
            metadata = DBIStoragePolicy.build_metadata(
                address=canonical,
                content_type=str(raw["content_type"]),
                size_bytes=int(raw["size_bytes"]),
                sha256_hex=str(raw["sha256"]),
            )
            state = DBIStorageObjectState(str(raw["state"]))
            created_at = _utc(
                datetime.fromisoformat(str(raw["created_at"])),
                field_name="created_at",
            )
            retired_raw = raw.get("retired_at")
            retired_at = (
                _utc(
                    datetime.fromisoformat(str(retired_raw)),
                    field_name="retired_at",
                )
                if retired_raw
                else None
            )
        except DBIStorageIntegrityError:
            raise
        except Exception as error:
            raise DBIStorageIntegrityError(
                "La metadata local del objeto está dañada."
            ) from error

        if object_path.stat().st_size != metadata.size_bytes:
            raise DBIStorageIntegrityError(
                "El archivo local no coincide con el tamaño declarado."
            )

        record = DBIStorageObjectRecord(
            metadata=metadata,
            state=state,
            created_at=created_at,
            retired_at=retired_at,
        )
        DBIStoragePolicy.validate_record(record)
        if record.state is DBIStorageObjectState.RETIRED and not include_retired:
            raise DBIStorageNotFound()
        return record

    def put(
        self,
        request: DBIStorageWriteRequest,
        content: BinaryIO,
    ) -> DBIStorageWriteResult:
        if not isinstance(request, DBIStorageWriteRequest):
            raise DBIStorageConflict("request debe ser DBIStorageWriteRequest.")
        metadata = DBIStoragePolicy.validate_metadata(request.metadata)
        read = getattr(content, "read", None)
        if not callable(read):
            raise DBIStorageIntegrityError("content debe ser un flujo binario.")

        object_path, metadata_path = self._paths(metadata.address)
        with self._lock:
            try:
                existing = self._load_record(
                    metadata.address,
                    include_retired=True,
                )
            except DBIStorageNotFound:
                existing = None

            if existing is not None:
                if existing.state is DBIStorageObjectState.RETIRED:
                    raise DBIStorageConflict(
                        "Un objeto retirado no puede reactivarse implícitamente."
                    )
                if existing.metadata != metadata:
                    raise DBIStorageConflict(
                        "La clave existe con metadatos divergentes."
                    )

                digest = sha256()
                total = 0
                with object_path.open("rb") as stored:
                    while True:
                        chunk = stored.read(_READ_CHUNK_SIZE)
                        if not chunk:
                            break
                        total += len(chunk)
                        digest.update(chunk)
                if total != metadata.size_bytes or digest.hexdigest() != metadata.sha256:
                    raise DBIStorageIntegrityError(
                        "El objeto local existente no coincide con su metadata."
                    )
                return DBIStorageWriteResult(record=existing, created=False)

            object_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._staging_root / f"{metadata.address.object_id}.{token_urlsafe(8)}.part"
            digest = sha256()
            total = 0
            try:
                with temp_path.open("wb") as destination:
                    while True:
                        chunk = read(_READ_CHUNK_SIZE)
                        if chunk in (b"", None):
                            break
                        if not isinstance(chunk, bytes):
                            raise DBIStorageIntegrityError(
                                "El flujo debe devolver exclusivamente bytes."
                            )
                        total += len(chunk)
                        if total > metadata.size_bytes:
                            raise DBIStorageIntegrityError(
                                "El contenido excede el tamaño declarado."
                            )
                        destination.write(chunk)
                        digest.update(chunk)

                if total != metadata.size_bytes:
                    raise DBIStorageIntegrityError(
                        "El contenido no coincide con el tamaño declarado."
                    )
                if digest.hexdigest() != metadata.sha256:
                    raise DBIStorageIntegrityError(
                        "El contenido no coincide con la huella declarada."
                    )

                os.replace(temp_path, object_path)
                record = DBIStorageObjectRecord(
                    metadata=metadata,
                    state=DBIStorageObjectState.ACTIVE,
                    created_at=self._created_at(),
                )
                DBIStoragePolicy.validate_record(record)
                self._write_sidecar(metadata_path, record)
                return DBIStorageWriteResult(record=record, created=True)
            except Exception:
                temp_path.unlink(missing_ok=True)
                if object_path.exists() and not metadata_path.exists():
                    object_path.unlink(missing_ok=True)
                raise

    def stat(self, address: DBIStorageAddress) -> DBIStorageObjectRecord:
        return self._load_record(address, include_retired=False)

    @contextmanager
    def open_read(self, address: DBIStorageAddress) -> Iterator[BinaryIO]:
        record = self.stat(address)
        object_path, _ = self._paths(record.metadata.address)
        stream = object_path.open("rb")
        try:
            yield stream
        finally:
            stream.close()

    def copy_to(
        self,
        address: DBIStorageAddress,
        destination: BinaryIO,
        *,
        progress: Callable[[int], None] | None = None,
    ) -> DBIStorageObjectRecord:
        record = self.stat(address)
        write = getattr(destination, "write", None)
        if not callable(write):
            raise DBIStorageIntegrityError(
                "destination debe ser un flujo binario escribible."
            )
        if progress is not None and not callable(progress):
            raise DBIStorageIntegrityError("progress debe ser invocable o null.")

        digest = sha256()
        total = 0
        with self.open_read(address) as source:
            while True:
                chunk = source.read(_READ_CHUNK_SIZE)
                if not chunk:
                    break
                written = write(chunk)
                if written is not None and written != len(chunk):
                    raise DBIStorageIntegrityError(
                        "destination realizó una escritura parcial."
                    )
                total += len(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(total)

        if total != record.metadata.size_bytes or digest.hexdigest() != record.metadata.sha256:
            raise DBIStorageIntegrityError(
                "El objeto local no coincide con tamaño o SHA-256 declarados."
            )
        return record

    def read_range(
        self,
        address: DBIStorageAddress,
        *,
        start: int,
        end_exclusive: int,
    ) -> DBIStorageRangeRead:
        record = self.stat(address)
        begin, end = _validated_range(
            size_bytes=record.metadata.size_bytes,
            start=start,
            end_exclusive=end_exclusive,
        )
        object_path, _ = self._paths(record.metadata.address)
        with object_path.open("rb") as stream:
            stream.seek(begin)
            data = stream.read(end - begin)
        if len(data) != end - begin:
            raise DBIStorageIntegrityError("el rango local quedó truncado.")
        return DBIStorageRangeRead(
            record=record,
            start=begin,
            end_exclusive=end,
            data=data,
        )

    def retire(
        self,
        address: DBIStorageAddress,
        *,
        retired_at: datetime,
    ) -> bool:
        canonical = DBIStoragePolicy.validate_address(address)
        timestamp = _utc(retired_at, field_name="retired_at")
        _, metadata_path = self._paths(canonical)
        with self._lock:
            record = self._load_record(canonical, include_retired=True)
            if record.state is DBIStorageObjectState.RETIRED:
                return False
            retired = replace(
                record,
                state=DBIStorageObjectState.RETIRED,
                retired_at=timestamp,
            )
            DBIStoragePolicy.validate_record(retired)
            self._write_sidecar(metadata_path, retired)
            return True

    def issue_temporary_access(
        self,
        metadata: DBIStorageObjectMetadata,
        *,
        mode: DBIStorageAccessMode,
        issued_at: datetime,
        expires_at: datetime,
    ) -> DBIStorageTemporaryGrant:
        canonical = DBIStoragePolicy.validate_metadata(metadata)
        if not isinstance(mode, DBIStorageAccessMode):
            raise DBIStorageConflict("mode debe ser DBIStorageAccessMode.")

        if mode is DBIStorageAccessMode.READ:
            existing = self.stat(canonical.address)
            if existing.metadata != canonical:
                raise DBIStorageConflict(
                    "La lectura temporal no coincide con el objeto activo."
                )
        else:
            try:
                existing = self._load_record(
                    canonical.address,
                    include_retired=True,
                )
            except DBIStorageNotFound:
                existing = None
            if existing is not None:
                if existing.state is DBIStorageObjectState.RETIRED:
                    raise DBIStorageConflict(
                        "Un objeto retirado no admite nueva carga temporal."
                    )
                if existing.metadata != canonical:
                    raise DBIStorageConflict(
                        "La carga temporal diverge del objeto existente."
                    )

        issued, expires = DBIStoragePolicy.validate_access_window(
            issued_at=issued_at,
            expires_at=expires_at,
        )
        grant = DBIStorageTemporaryGrant(
            grant_ref=self._grant_ref_factory(),
            metadata=canonical,
            mode=mode,
            issued_at=issued,
            expires_at=expires,
        )
        DBIStoragePolicy.validate_grant(grant)

        access = DBILocalResolvedTemporaryAccess(
            grant=grant,
            method="GET" if mode is DBIStorageAccessMode.READ else "PUT",
            url=f"{self._upload_base_path}/{grant.grant_ref}",
            headers=(
                ()
                if mode is DBIStorageAccessMode.READ
                else (
                    ("content-type", canonical.content_type),
                    ("x-dbi-content-sha256", canonical.sha256),
                )
            ),
        )
        with self._lock:
            self._grants[grant.grant_ref] = _StoredGrant(access=access)
        return grant

    def resolve_temporary_access(
        self,
        grant_ref: str,
        *,
        now: datetime | None = None,
    ) -> DBILocalResolvedTemporaryAccess:
        if not isinstance(grant_ref, str) or len(grant_ref) < 16:
            raise DBIStorageNotFound()
        timestamp = _utc(
            self._clock() if now is None else now,
            field_name="now",
        )
        with self._lock:
            stored = self._grants.get(grant_ref)
            if stored is None:
                raise DBIStorageNotFound()
            if timestamp >= stored.access.grant.expires_at:
                self._grants.pop(grant_ref, None)
                raise DBIStorageNotFound()
            return stored.access
