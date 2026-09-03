"""Política pura para claves, metadatos y acceso temporal DBI."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from app.dbi.storage_contracts import (
    DBIStorageAccessMode,
    DBIStorageAddress,
    DBIStorageConflict,
    DBIStorageObjectMetadata,
    DBIStorageObjectRecord,
    DBIStorageObjectState,
    DBIStoragePurpose,
    DBIStorageTemporaryGrant,
)

_OBJECT_KEY_MAX_LENGTH = 512
_TENANT_REF_MAX_LENGTH = 128
_CONTENT_TYPE_MAX_LENGTH = 128
_MAX_SIZE_BYTES = 9_223_372_036_854_775_807
_MIN_ACCESS_TTL = timedelta(seconds=30)
_MAX_ACCESS_TTL = timedelta(hours=1)
_WILDCARD_REFS = frozenset({"all", "any"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")
_OBJECT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,511}$")
_GRANT_REF_RE = re.compile(r"^[A-Za-z0-9._~-]{16,256}$")

_ALLOWED_CONTENT_TYPES: dict[DBIStoragePurpose, frozenset[str]] = {
    DBIStoragePurpose.ANALYSIS_INPUT: frozenset(
        {
            "application/geo+json",
            "application/geopackage+sqlite3",
            "application/json",
            "application/octet-stream",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/zip",
            "image/tiff",
            "text/csv",
        }
    ),
    DBIStoragePurpose.ANALYSIS_ARTIFACT: frozenset(
        {
            "application/geo+json",
            "application/geopackage+sqlite3",
            "application/json",
            "application/octet-stream",
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/zip",
            "image/png",
            "image/tiff",
            "text/csv",
        }
    ),
    DBIStoragePurpose.MODEL_ARTIFACT: frozenset(
        {
            "application/json",
            "application/octet-stream",
            "application/zip",
        }
    ),
    DBIStoragePurpose.TECHNICAL_SOURCE: frozenset(
        {
            "application/json",
            "application/pdf",
            "text/markdown",
            "text/plain",
        }
    ),
}


def _validated_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise DBIStorageConflict(f"{field_name} debe ser texto.")
    normalized = value.strip()
    if (
        not normalized
        or normalized != value
        or len(normalized) > _TENANT_REF_MAX_LENGTH
        or "*" in normalized
        or normalized.casefold() in _WILDCARD_REFS
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise DBIStorageConflict(f"{field_name} no es una referencia canónica.")
    return normalized


def _required_uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise DBIStorageConflict(f"{field_name} debe ser UUID.")
    return value


def _required_purpose(value: object) -> DBIStoragePurpose:
    if not isinstance(value, DBIStoragePurpose):
        raise DBIStorageConflict("purpose debe ser DBIStoragePurpose.")
    return value


def _utc_timestamp(value: object, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIStorageConflict(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def tenant_namespace(tenant_ref: str) -> str:
    """Deriva un namespace estable sin exponer la referencia del tenant."""

    tenant = _validated_ref(tenant_ref, field_name="tenant_ref")
    material = f"dalgoro:dbi:storage:tenant:v1\0{tenant}".encode("utf-8")
    return sha256(material).hexdigest()[:32]


def build_object_key(
    *,
    tenant_ref: str,
    purpose: DBIStoragePurpose,
    object_id: UUID,
) -> str:
    """Construye una clave relativa sin nombres originales ni datos personales."""

    namespace = tenant_namespace(tenant_ref)
    storage_purpose = _required_purpose(purpose)
    identifier = _required_uuid(object_id, field_name="object_id")
    key = f"tenants/{namespace}/{storage_purpose.value}/{identifier}"
    if len(key) > _OBJECT_KEY_MAX_LENGTH or not _OBJECT_KEY_RE.fullmatch(key):
        raise DBIStorageConflict("La clave canónica excede la política DBI.")
    return key


def build_address(
    *,
    tenant_ref: str,
    purpose: DBIStoragePurpose,
    object_id: UUID,
) -> DBIStorageAddress:
    """Crea una dirección cuyo key solo puede derivarse de su identidad."""

    tenant = _validated_ref(tenant_ref, field_name="tenant_ref")
    storage_purpose = _required_purpose(purpose)
    identifier = _required_uuid(object_id, field_name="object_id")
    return DBIStorageAddress(
        tenant_ref=tenant,
        purpose=storage_purpose,
        object_id=identifier,
        object_key=build_object_key(
            tenant_ref=tenant,
            purpose=storage_purpose,
            object_id=identifier,
        ),
    )


def validate_address(value: object) -> DBIStorageAddress:
    """Rechaza direcciones fabricadas, URLs, rutas o namespaces divergentes."""

    if not isinstance(value, DBIStorageAddress):
        raise DBIStorageConflict("address debe ser DBIStorageAddress.")
    expected = build_address(
        tenant_ref=value.tenant_ref,
        purpose=value.purpose,
        object_id=value.object_id,
    )
    if value != expected:
        raise DBIStorageConflict("La dirección no coincide con su clave canónica.")
    key = value.object_key
    if (
        len(key) > _OBJECT_KEY_MAX_LENGTH
        or not _OBJECT_KEY_RE.fullmatch(key)
        or key.startswith("/")
        or "\\" in key
        or "//" in key
        or ":" in key
        or "?" in key
        or "#" in key
        or any(segment in {"", ".", ".."} for segment in key.split("/"))
    ):
        raise DBIStorageConflict("La clave contiene una ruta o segmento prohibido.")
    return value


def validate_content_type(
    value: object,
    *,
    purpose: DBIStoragePurpose,
) -> str:
    """Valida un MIME canónico y permitido para el propósito declarado."""

    storage_purpose = _required_purpose(purpose)
    if not isinstance(value, str):
        raise DBIStorageConflict("content_type debe ser texto.")
    normalized = value.strip().lower()
    if (
        not normalized
        or normalized != value
        or len(normalized) > _CONTENT_TYPE_MAX_LENGTH
        or not _CONTENT_TYPE_RE.fullmatch(normalized)
        or normalized not in _ALLOWED_CONTENT_TYPES[storage_purpose]
    ):
        raise DBIStorageConflict("content_type no está permitido para el propósito.")
    return normalized


def validate_size_bytes(value: object) -> int:
    """Valida el rango compatible con metadatos DBI BigInteger."""

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
        or value > _MAX_SIZE_BYTES
    ):
        raise DBIStorageConflict("size_bytes debe ser un entero positivo válido.")
    return value


def validate_sha256(value: object) -> str:
    """Exige SHA-256 hexadecimal canónico en minúsculas."""

    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise DBIStorageConflict("sha256 debe contener 64 caracteres hexadecimales.")
    return value


def build_metadata(
    *,
    address: DBIStorageAddress,
    content_type: str,
    size_bytes: int,
    sha256_hex: str,
) -> DBIStorageObjectMetadata:
    """Crea metadatos verificables sin URL, credencial o ruta local."""

    canonical_address = validate_address(address)
    return DBIStorageObjectMetadata(
        address=canonical_address,
        content_type=validate_content_type(
            content_type,
            purpose=canonical_address.purpose,
        ),
        size_bytes=validate_size_bytes(size_bytes),
        sha256=validate_sha256(sha256_hex),
    )


def validate_metadata(value: object) -> DBIStorageObjectMetadata:
    if not isinstance(value, DBIStorageObjectMetadata):
        raise DBIStorageConflict("metadata debe ser DBIStorageObjectMetadata.")
    expected = build_metadata(
        address=value.address,
        content_type=value.content_type,
        size_bytes=value.size_bytes,
        sha256_hex=value.sha256,
    )
    if value != expected:
        raise DBIStorageConflict("Los metadatos no son canónicos.")
    return value


def validate_access_window(
    *,
    issued_at: datetime,
    expires_at: datetime,
) -> tuple[datetime, datetime]:
    """Exige una ventana UTC acotada y no expirada al emitirse."""

    issued = _utc_timestamp(issued_at, field_name="issued_at")
    expires = _utc_timestamp(expires_at, field_name="expires_at")
    ttl = expires - issued
    if ttl < _MIN_ACCESS_TTL or ttl > _MAX_ACCESS_TTL:
        raise DBIStorageConflict("El TTL temporal está fuera de la política DBI.")
    return issued, expires


def validate_grant(value: object) -> DBIStorageTemporaryGrant:
    """Valida una autorización efímera opaca y sus metadatos vinculados."""

    if not isinstance(value, DBIStorageTemporaryGrant):
        raise DBIStorageConflict("grant debe ser DBIStorageTemporaryGrant.")
    if not isinstance(value.grant_ref, str) or not _GRANT_REF_RE.fullmatch(
        value.grant_ref
    ):
        raise DBIStorageConflict("grant_ref debe ser una referencia opaca acotada.")
    validate_metadata(value.metadata)
    if not isinstance(value.mode, DBIStorageAccessMode):
        raise DBIStorageConflict("mode debe ser DBIStorageAccessMode.")
    issued, expires = validate_access_window(
        issued_at=value.issued_at,
        expires_at=value.expires_at,
    )
    if value.issued_at != issued or value.expires_at != expires:
        raise DBIStorageConflict("Las fechas del grant deben persistir en UTC.")
    return value


def validate_record(value: object) -> DBIStorageObjectRecord:
    """Comprueba coherencia temporal del estado lógico del objeto."""

    if not isinstance(value, DBIStorageObjectRecord):
        raise DBIStorageConflict("record debe ser DBIStorageObjectRecord.")
    validate_metadata(value.metadata)
    created = _utc_timestamp(value.created_at, field_name="created_at")
    if value.created_at != created:
        raise DBIStorageConflict("created_at debe estar normalizado a UTC.")
    if not isinstance(value.state, DBIStorageObjectState):
        raise DBIStorageConflict("state debe ser DBIStorageObjectState.")
    if value.state is DBIStorageObjectState.ACTIVE:
        if value.retired_at is not None:
            raise DBIStorageConflict("Un objeto activo no puede tener retired_at.")
    else:
        retired = _utc_timestamp(value.retired_at, field_name="retired_at")
        if value.retired_at != retired or retired < created:
            raise DBIStorageConflict("retired_at no es coherente con la creación.")
    return value


class DBIStoragePolicy:
    """Superficie explícita para consumidores y futuros adaptadores."""

    min_access_ttl = _MIN_ACCESS_TTL
    max_access_ttl = _MAX_ACCESS_TTL
    allowed_content_types = _ALLOWED_CONTENT_TYPES
    tenant_namespace = staticmethod(tenant_namespace)
    build_address = staticmethod(build_address)
    validate_address = staticmethod(validate_address)
    build_metadata = staticmethod(build_metadata)
    validate_metadata = staticmethod(validate_metadata)
    validate_access_window = staticmethod(validate_access_window)
    validate_grant = staticmethod(validate_grant)
    validate_record = staticmethod(validate_record)
