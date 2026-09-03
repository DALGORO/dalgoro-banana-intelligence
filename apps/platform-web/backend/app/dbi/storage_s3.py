"""Adaptador S3-compatible no productivo para objetos privados DBI."""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from secrets import token_urlsafe
from threading import RLock
from typing import Any, BinaryIO, Callable, Iterator
from urllib.parse import urlencode, urlparse

from botocore.exceptions import BotoCoreError, ClientError

from app.dbi.storage_contracts import (
    DBIStorageAccessMode,
    DBIStorageAddress,
    DBIStorageConflict,
    DBIStorageDenied,
    DBIStorageError,
    DBIStorageIntegrityError,
    DBIStorageNotFound,
    DBIStorageObjectMetadata,
    DBIStorageObjectRecord,
    DBIStorageObjectState,
    DBIStorageTemporaryGrant,
    DBIStorageWriteRequest,
    DBIStorageWriteResult,
)
from app.dbi.storage_policy import DBIStoragePolicy

_DEFAULT_MAX_OBJECT_SIZE_BYTES = 64 * 1024 * 1024
_READ_CHUNK_SIZE = 64 * 1024
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_GRANT_REF_RE = re.compile(r"^[A-Za-z0-9._~-]{16,256}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

_META_SHA256 = "dbi-sha256"
_META_SIZE = "dbi-size"
_META_PURPOSE = "dbi-purpose"
_META_OBJECT_ID = "dbi-object-id"
_TAG_STATE = "dbi-state"
_TAG_RETIRED_AT = "dbi-retired-at"


@dataclass(frozen=True, slots=True)
class DBIS3ObjectStoreConfig:
    """Configuración explícita; nunca consulta cadenas de credenciales implícitas."""

    endpoint_url: str
    bucket: str
    region: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    session_token: str | None = field(default=None, repr=False)
    verify_tls: bool = True
    connect_timeout_seconds: int = 3
    read_timeout_seconds: int = 15
    max_attempts: int = 2
    max_object_size_bytes: int = _DEFAULT_MAX_OBJECT_SIZE_BYTES

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("endpoint_url debe ser un origen HTTP(S) canónico.")
        if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS:
            raise ValueError("HTTP solo está permitido para endpoints loopback.")
        if parsed.scheme == "https" and self.verify_tls is not True:
            raise ValueError("Los endpoints HTTPS deben verificar TLS.")
        if not _BUCKET_RE.fullmatch(self.bucket) or ".." in self.bucket:
            raise ValueError("bucket no cumple la política S3 DBI.")
        if not self.region or self.region.strip() != self.region:
            raise ValueError("region debe ser una referencia canónica.")
        _validate_secret(self.access_key_id, field_name="access_key_id")
        _validate_secret(self.secret_access_key, field_name="secret_access_key")
        if self.session_token is not None:
            _validate_secret(self.session_token, field_name="session_token")
        for value, field_name in (
            (self.connect_timeout_seconds, "connect_timeout_seconds"),
            (self.read_timeout_seconds, "read_timeout_seconds"),
            (self.max_attempts, "max_attempts"),
            (self.max_object_size_bytes, "max_object_size_bytes"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} debe ser un entero positivo.")


@dataclass(frozen=True, slots=True)
class DBIS3ResolvedTemporaryAccess:
    """Material efímero resuelto; URL y cabeceras quedan fuera de repr."""

    grant: DBIStorageTemporaryGrant
    method: str
    url: str = field(repr=False)
    headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class _StoredGrant:
    access: DBIS3ResolvedTemporaryAccess


def _validate_secret(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} no es válido.")
    return value


def _utc_timestamp(value: object, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIStorageConflict(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _opaque_grant_ref() -> str:
    return token_urlsafe(32)


def _object_metadata(metadata: DBIStorageObjectMetadata) -> dict[str, str]:
    return {
        _META_SHA256: metadata.sha256,
        _META_SIZE: str(metadata.size_bytes),
        _META_PURPOSE: metadata.address.purpose.value,
        _META_OBJECT_ID: str(metadata.address.object_id),
    }


def _active_tagging() -> str:
    return urlencode({_TAG_STATE: DBIStorageObjectState.ACTIVE.value})


def _retired_tag_set(retired_at: datetime) -> list[dict[str, str]]:
    return [
        {"Key": _TAG_STATE, "Value": DBIStorageObjectState.RETIRED.value},
        {"Key": _TAG_RETIRED_AT, "Value": retired_at.isoformat()},
    ]


def _error_code(error: ClientError) -> str:
    response = error.response if isinstance(error.response, dict) else {}
    details = response.get("Error", {})
    return str(details.get("Code", ""))


def _translate_client_error(error: ClientError) -> DBIStorageError:
    code = _error_code(error).casefold()
    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if status == 404 or code in {"404", "nosuchkey", "notfound", "nosuchbucket"}:
        return DBIStorageNotFound()
    if status == 403 or code in {"403", "accessdenied", "invalidaccesskeyid"}:
        return DBIStorageDenied()
    if status in {409, 412} or code in {
        "409",
        "412",
        "conflict",
        "preconditionfailed",
        "conditionalrequestconflict",
    }:
        return DBIStorageConflict("La escritura condicional encontró otro objeto.")
    return DBIStorageError("El proveedor S3 rechazó la operación privada.")


def build_s3_client(config: DBIS3ObjectStoreConfig) -> Any:
    """Construye un cliente con credenciales explícitas y SigV4 path-style."""

    if not isinstance(config, DBIS3ObjectStoreConfig):
        raise TypeError("config debe ser DBIS3ObjectStoreConfig.")

    import boto3
    from botocore.config import Config

    session = boto3.Session(
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        aws_session_token=config.session_token,
        region_name=config.region,
    )
    return session.client(
        "s3",
        endpoint_url=config.endpoint_url.rstrip("/"),
        use_ssl=config.endpoint_url.startswith("https://"),
        verify=config.verify_tls,
        config=Config(
            signature_version="s3v4",
            connect_timeout=config.connect_timeout_seconds,
            read_timeout=config.read_timeout_seconds,
            retries={
                "total_max_attempts": config.max_attempts,
                "mode": "standard",
            },
            s3={"addressing_style": "path"},
        ),
    )


class DBIS3ObjectStore:
    """Puerto DBI sobre S3-compatible, cerrado a sobrescrituras y ACL públicas."""

    def __init__(
        self,
        config: DBIS3ObjectStoreConfig,
        *,
        client: Any | None = None,
        clock: Callable[[], datetime] = _utc_now,
        grant_ref_factory: Callable[[], str] = _opaque_grant_ref,
    ) -> None:
        if not isinstance(config, DBIS3ObjectStoreConfig):
            raise TypeError("config debe ser DBIS3ObjectStoreConfig.")
        if not callable(clock) or not callable(grant_ref_factory):
            raise TypeError("clock y grant_ref_factory deben ser invocables.")
        self._config = config
        self._client = client if client is not None else build_s3_client(config)
        self._clock = clock
        self._grant_ref_factory = grant_ref_factory
        self._grants: dict[str, _StoredGrant] = {}
        self._grant_lock = RLock()

    def _call(self, operation: str, /, **kwargs: Any) -> Any:
        method = getattr(self._client, operation, None)
        if not callable(method):
            raise DBIStorageError("El cliente S3 no implementa la operación requerida.")
        try:
            return method(**kwargs)
        except ClientError as error:
            raise _translate_client_error(error) from None
        except BotoCoreError:
            raise DBIStorageError(
                "No se pudo completar la operación con el proveedor S3."
            ) from None

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
        if expected_size > self._config.max_object_size_bytes:
            raise DBIStorageIntegrityError(
                "El objeto excede el límite del adaptador S3 no productivo."
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

    def _record_from_provider(
        self,
        address: DBIStorageAddress,
        *,
        include_retired: bool,
    ) -> DBIStorageObjectRecord:
        canonical = DBIStoragePolicy.validate_address(address)
        head = self._call(
            "head_object",
            Bucket=self._config.bucket,
            Key=canonical.object_key,
        )
        tags_response = self._call(
            "get_object_tagging",
            Bucket=self._config.bucket,
            Key=canonical.object_key,
        )
        raw_metadata = head.get("Metadata", {})
        try:
            metadata = DBIStoragePolicy.build_metadata(
                address=canonical,
                content_type=head["ContentType"],
                size_bytes=int(head["ContentLength"]),
                sha256_hex=raw_metadata[_META_SHA256],
            )
            if raw_metadata[_META_SIZE] != str(metadata.size_bytes):
                raise KeyError(_META_SIZE)
            if raw_metadata[_META_PURPOSE] != canonical.purpose.value:
                raise KeyError(_META_PURPOSE)
            if raw_metadata[_META_OBJECT_ID] != str(canonical.object_id):
                raise KeyError(_META_OBJECT_ID)
            created_at = _utc_timestamp(head["LastModified"], field_name="LastModified")
        except (KeyError, TypeError, ValueError, DBIStorageConflict):
            raise DBIStorageIntegrityError(
                "Los metadatos del objeto S3 no cumplen el contrato DBI."
            ) from None

        tags = {
            item.get("Key"): item.get("Value")
            for item in tags_response.get("TagSet", ())
            if isinstance(item, dict)
        }
        state_value = tags.get(_TAG_STATE)
        if state_value == DBIStorageObjectState.ACTIVE.value:
            state = DBIStorageObjectState.ACTIVE
            retired_at = None
        elif state_value == DBIStorageObjectState.RETIRED.value:
            state = DBIStorageObjectState.RETIRED
            try:
                retired_at = _utc_timestamp(
                    datetime.fromisoformat(tags[_TAG_RETIRED_AT]),
                    field_name="retired_at",
                )
            except (KeyError, TypeError, ValueError, DBIStorageConflict):
                raise DBIStorageIntegrityError(
                    "El retiro lógico S3 no contiene una fecha válida."
                ) from None
        else:
            raise DBIStorageIntegrityError(
                "El objeto S3 no contiene un estado DBI válido."
            )

        record = DBIStorageObjectRecord(
            metadata=metadata,
            state=state,
            created_at=created_at,
            retired_at=retired_at,
        )
        try:
            DBIStoragePolicy.validate_record(record)
        except DBIStorageConflict:
            raise DBIStorageIntegrityError(
                "El estado temporal del objeto S3 no es coherente."
            ) from None
        if state is DBIStorageObjectState.RETIRED and not include_retired:
            raise DBIStorageNotFound()
        return record

    def _download_verified(self, metadata: DBIStorageObjectMetadata) -> bytes:
        response = self._call(
            "get_object",
            Bucket=self._config.bucket,
            Key=metadata.address.object_key,
        )
        body = response.get("Body")
        try:
            return self._read_verified_content(
                body,
                expected_size=metadata.size_bytes,
                expected_sha256=metadata.sha256,
            )
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def put(
        self,
        request: DBIStorageWriteRequest,
        content: BinaryIO,
    ) -> DBIStorageWriteResult:
        if not isinstance(request, DBIStorageWriteRequest):
            raise DBIStorageConflict("request debe ser DBIStorageWriteRequest.")
        metadata = DBIStoragePolicy.validate_metadata(request.metadata)
        payload = self._read_verified_content(
            content,
            expected_size=metadata.size_bytes,
            expected_sha256=metadata.sha256,
        )

        try:
            self._call(
                "put_object",
                Bucket=self._config.bucket,
                Key=metadata.address.object_key,
                Body=payload,
                ContentLength=metadata.size_bytes,
                ContentType=metadata.content_type,
                Metadata=_object_metadata(metadata),
                Tagging=_active_tagging(),
                IfNoneMatch="*",
            )
        except DBIStorageConflict:
            existing = self._record_from_provider(
                metadata.address,
                include_retired=True,
            )
            if existing.state is DBIStorageObjectState.RETIRED:
                raise DBIStorageConflict(
                    "Un objeto retirado no puede reactivarse implícitamente."
                ) from None
            if existing.metadata != metadata:
                raise DBIStorageConflict(
                    "La clave existe con metadatos divergentes."
                ) from None
            if self._download_verified(metadata) != payload:
                raise DBIStorageConflict(
                    "La clave existe con contenido divergente."
                ) from None
            return DBIStorageWriteResult(record=existing, created=False)

        record = self._record_from_provider(
            metadata.address,
            include_retired=True,
        )
        if record.state is not DBIStorageObjectState.ACTIVE or record.metadata != metadata:
            raise DBIStorageIntegrityError(
                "El proveedor no confirmó la escritura exacta solicitada."
            )
        return DBIStorageWriteResult(record=record, created=True)

    def stat(self, address: DBIStorageAddress) -> DBIStorageObjectRecord:
        return self._record_from_provider(address, include_retired=False)

    @contextmanager
    def open_read(self, address: DBIStorageAddress) -> Iterator[BinaryIO]:
        record = self.stat(address)
        payload = self._download_verified(record.metadata)
        stream = BytesIO(payload)
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
        """Materializa un objeto activo sin acumularlo completo en memoria."""

        record = self.stat(address)
        write = getattr(destination, "write", None)
        if not callable(write):
            raise DBIStorageIntegrityError("destination debe ser un flujo binario escribible.")
        if progress is not None and not callable(progress):
            raise DBIStorageIntegrityError("progress debe ser invocable o null.")

        response = self._call(
            "get_object",
            Bucket=self._config.bucket,
            Key=record.metadata.address.object_key,
        )
        body = response.get("Body")
        read = getattr(body, "read", None)
        if not callable(read):
            raise DBIStorageIntegrityError("El proveedor no devolvió un flujo binario.")

        digest = sha256()
        total = 0
        try:
            while True:
                chunk = read(_READ_CHUNK_SIZE)
                if chunk in (b"", None):
                    break
                if not isinstance(chunk, bytes):
                    raise DBIStorageIntegrityError(
                        "El flujo S3 debe devolver exclusivamente bytes."
                    )
                total += len(chunk)
                if total > record.metadata.size_bytes:
                    raise DBIStorageIntegrityError(
                        "El objeto S3 excede el tamaño declarado."
                    )
                written = write(chunk)
                if written is not None and written != len(chunk):
                    raise DBIStorageIntegrityError(
                        "destination realizó una escritura parcial."
                    )
                digest.update(chunk)
                if progress is not None:
                    progress(total)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

        if total != record.metadata.size_bytes:
            raise DBIStorageIntegrityError(
                "El objeto S3 no coincide con el tamaño declarado."
            )
        if digest.hexdigest() != record.metadata.sha256:
            raise DBIStorageIntegrityError(
                "El objeto S3 no coincide con la huella declarada."
            )
        return record

    def retire(
        self,
        address: DBIStorageAddress,
        *,
        retired_at: datetime,
    ) -> bool:
        record = self._record_from_provider(address, include_retired=True)
        if record.state is DBIStorageObjectState.RETIRED:
            return False
        timestamp = _utc_timestamp(retired_at, field_name="retired_at")
        candidate = DBIStorageObjectRecord(
            metadata=record.metadata,
            state=DBIStorageObjectState.RETIRED,
            created_at=record.created_at,
            retired_at=timestamp,
        )
        DBIStoragePolicy.validate_record(candidate)
        self._call(
            "put_object_tagging",
            Bucket=self._config.bucket,
            Key=record.metadata.address.object_key,
            Tagging={"TagSet": _retired_tag_set(timestamp)},
        )
        persisted = self._record_from_provider(address, include_retired=True)
        if persisted != candidate:
            raise DBIStorageIntegrityError(
                "El proveedor no confirmó el retiro lógico exacto."
            )
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
        issued, expires = DBIStoragePolicy.validate_access_window(
            issued_at=issued_at,
            expires_at=expires_at,
        )

        headers: tuple[tuple[str, str], ...]
        if mode is DBIStorageAccessMode.READ:
            existing = self._record_from_provider(
                canonical.address,
                include_retired=False,
            )
            if existing.metadata != canonical:
                raise DBIStorageConflict(
                    "El objeto activo no coincide con los metadatos del grant."
                )
            operation = "get_object"
            params: dict[str, Any] = {
                "Bucket": self._config.bucket,
                "Key": canonical.address.object_key,
            }
            method = "GET"
            headers = ()
        else:
            try:
                self._record_from_provider(
                    canonical.address,
                    include_retired=True,
                )
            except DBIStorageNotFound:
                pass
            else:
                raise DBIStorageConflict(
                    "Un grant de carga solo puede emitirse para una clave ausente."
                )
            operation = "put_object"
            object_metadata = _object_metadata(canonical)
            tagging = _active_tagging()
            params = {
                "Bucket": self._config.bucket,
                "Key": canonical.object_key,
                "ContentLength": canonical.size_bytes,
                "ContentType": canonical.content_type,
                "Metadata": object_metadata,
                "Tagging": tagging,
                "IfNoneMatch": "*",
            }
            method = "PUT"
            headers = tuple(
                sorted(
                    {
                        "content-length": str(canonical.size_bytes),
                        "content-type": canonical.content_type,
                        "if-none-match": "*",
                        "x-amz-tagging": tagging,
                        **{
                            f"x-amz-meta-{key}": value
                            for key, value in object_metadata.items()
                        },
                    }.items()
                )
            )

        ttl_seconds = int((expires - issued).total_seconds())
        try:
            url = self._client.generate_presigned_url(
                operation,
                Params=params,
                ExpiresIn=ttl_seconds,
                HttpMethod=method,
            )
        except (ClientError, BotoCoreError):
            raise DBIStorageError(
                "No se pudo emitir acceso temporal con el proveedor S3."
            ) from None
        if not isinstance(url, str) or not url:
            raise DBIStorageIntegrityError(
                "El proveedor S3 no devolvió una autorización temporal válida."
            )

        grant_ref = self._grant_ref_factory()
        grant = DBIStorageTemporaryGrant(
            grant_ref=grant_ref,
            metadata=canonical,
            mode=mode,
            issued_at=issued,
            expires_at=expires,
        )
        DBIStoragePolicy.validate_grant(grant)
        access = DBIS3ResolvedTemporaryAccess(
            grant=grant,
            method=method,
            url=url,
            headers=headers,
        )
        with self._grant_lock:
            self._grants[grant_ref] = _StoredGrant(access=access)
        return grant

    def resolve_temporary_access(
        self,
        grant_ref: str,
        *,
        now: datetime | None = None,
    ) -> DBIS3ResolvedTemporaryAccess:
        """Resuelve un grant solo en memoria y elimina referencias expiradas."""

        if not isinstance(grant_ref, str) or not _GRANT_REF_RE.fullmatch(grant_ref):
            raise DBIStorageNotFound()
        timestamp = _utc_timestamp(
            self._clock() if now is None else now,
            field_name="now",
        )
        with self._grant_lock:
            stored = self._grants.get(grant_ref)
            if stored is None:
                raise DBIStorageNotFound()
            if timestamp >= stored.access.grant.expires_at:
                self._grants.pop(grant_ref, None)
                raise DBIStorageNotFound()
            return stored.access
