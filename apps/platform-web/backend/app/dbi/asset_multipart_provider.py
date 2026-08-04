"""Puerto proveedor-neutral para transporte multipartes de activos DBI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm,
    DBIMultipartChecksumType,
    DBIMultipartPartEvidence,
    DBIMultipartRoutingDecision,
    DBIMultipartUploadPlan,
)
from app.dbi.asset_multipart_policy import DBIMultipartPolicy
from app.dbi.storage_contracts import (
    DBIStorageConflict,
    DBIStorageObjectMetadata,
    DBIStoragePurpose,
)
from app.dbi.storage_policy import DBIStoragePolicy


class DBIMultipartProviderError(RuntimeError):
    """Error normalizado de una operación multipartes del proveedor."""


class DBIMultipartProviderDenied(DBIMultipartProviderError):
    """El proveedor rechazó la autoridad configurada."""


class DBIMultipartProviderConflict(DBIMultipartProviderError):
    """La operación contradice una carga u objeto ya existente."""


class DBIMultipartProviderNotFound(DBIMultipartProviderError):
    """La carga u objeto no existe en el proveedor."""


class DBIMultipartProviderIntegrityError(DBIMultipartProviderError):
    """La evidencia del proveedor no coincide con el contrato DBI."""


@dataclass(frozen=True, slots=True)
class DBIMultipartProviderInitiateRequest:
    """Inicio sin credenciales, bucket, endpoint o URL."""

    session_id: UUID
    metadata: DBIStorageObjectMetadata
    plan: DBIMultipartUploadPlan
    initiated_at: datetime


@dataclass(frozen=True, slots=True)
class DBIMultipartProviderUpload:
    """Carga iniciada; la referencia del proveedor permanece interna."""

    provider_upload_ref: str = field(repr=False)
    session_id: UUID
    metadata: DBIStorageObjectMetadata
    plan: DBIMultipartUploadPlan
    initiated_at: datetime


@dataclass(frozen=True, slots=True)
class DBIMultipartProviderPartGrantRequest:
    """Solicitud acotada de autoridad temporal para una parte exacta."""

    upload: DBIMultipartProviderUpload = field(repr=False)
    part_number: int
    size_bytes: int
    checksum: str = field(repr=False)
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DBIMultipartProviderPartGrant:
    """Grant seguro; URL y cabeceras se resuelven solo de forma efímera."""

    grant_ref: str = field(repr=False)
    session_id: UUID
    part_number: int
    size_bytes: int
    checksum_algorithm: DBIMultipartChecksumAlgorithm
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DBIMultipartProviderCompleteRequest:
    """Manifiesto exacto para ensamblar el objeto una sola vez."""

    upload: DBIMultipartProviderUpload = field(repr=False)
    parts: tuple[DBIMultipartPartEvidence, ...] = field(repr=False)
    full_object_checksum: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class DBIMultipartProviderCompletion:
    """Evidencia de transporte, distinta del SHA-256 canónico declarado."""

    session_id: UUID
    metadata: DBIStorageObjectMetadata
    checksum_algorithm: DBIMultipartChecksumAlgorithm
    checksum_type: DBIMultipartChecksumType
    transport_checksum: str = field(repr=False)
    etag: str = field(repr=False)
    completed_at: datetime
    created: bool


class DBIMultipartObjectStore(Protocol):
    """Operaciones multipartes requeridas antes de aborto y limpieza."""

    def initiate(
        self,
        request: DBIMultipartProviderInitiateRequest,
    ) -> DBIMultipartProviderUpload: ...

    def issue_part_access(
        self,
        request: DBIMultipartProviderPartGrantRequest,
    ) -> DBIMultipartProviderPartGrant: ...

    def complete(
        self,
        request: DBIMultipartProviderCompleteRequest,
    ) -> DBIMultipartProviderCompletion: ...

    def inspect_completed(
        self,
        upload: DBIMultipartProviderUpload,
    ) -> DBIMultipartProviderCompletion: ...


def _utc(value: object, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIMultipartProviderConflict(
            f"{field_name} debe incluir zona horaria."
        )
    return value.astimezone(timezone.utc)


def _provider_ref(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 1024
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise DBIMultipartProviderIntegrityError(
            "La referencia del proveedor no es canónica."
        )
    return value


def validate_initiate_request(
    value: object,
) -> DBIMultipartProviderInitiateRequest:
    if not isinstance(value, DBIMultipartProviderInitiateRequest):
        raise DBIMultipartProviderConflict(
            "request debe ser DBIMultipartProviderInitiateRequest."
        )
    if not isinstance(value.session_id, UUID):
        raise DBIMultipartProviderConflict("session_id debe ser UUID.")
    try:
        metadata = DBIStoragePolicy.validate_metadata(value.metadata)
    except (DBIStorageConflict, TypeError, ValueError) as error:
        raise DBIMultipartProviderConflict(str(error)) from error
    if metadata.address.purpose is not DBIStoragePurpose.ANALYSIS_INPUT:
        raise DBIMultipartProviderConflict(
            "multipartes solo admite activos privados de entrada."
        )
    if (
        not isinstance(value.plan, DBIMultipartUploadPlan)
        or value.plan.decision is not DBIMultipartRoutingDecision.MULTIPART
        or value.plan.size_bytes != metadata.size_bytes
        or value.plan.part_size_bytes is None
        or value.plan.part_count < 1
    ):
        raise DBIMultipartProviderConflict("el plan multipartes no es canónico.")
    try:
        DBIMultipartPolicy.validate_checksum_mode(
            value.plan.checksum_algorithm,
            value.plan.checksum_type,
        )
    except ValueError as error:
        raise DBIMultipartProviderConflict(str(error)) from error
    _utc(value.initiated_at, field_name="initiated_at")
    return value


def validate_upload(value: object) -> DBIMultipartProviderUpload:
    if not isinstance(value, DBIMultipartProviderUpload):
        raise DBIMultipartProviderConflict(
            "upload debe ser DBIMultipartProviderUpload."
        )
    _provider_ref(value.provider_upload_ref)
    validate_initiate_request(
        DBIMultipartProviderInitiateRequest(
            session_id=value.session_id,
            metadata=value.metadata,
            plan=value.plan,
            initiated_at=value.initiated_at,
        )
    )
    return value


def validate_part_grant_request(
    value: object,
) -> DBIMultipartProviderPartGrantRequest:
    if not isinstance(value, DBIMultipartProviderPartGrantRequest):
        raise DBIMultipartProviderConflict(
            "request debe ser DBIMultipartProviderPartGrantRequest."
        )
    upload = validate_upload(value.upload)
    try:
        expected_size = DBIMultipartPolicy.expected_part_size(
            upload.plan,
            part_number=value.part_number,
        )
        DBIMultipartPolicy.validate_transport_checksum(
            value.checksum,
            algorithm=upload.plan.checksum_algorithm,
        )
    except ValueError as error:
        raise DBIMultipartProviderConflict(str(error)) from error
    if value.size_bytes != expected_size:
        raise DBIMultipartProviderConflict(
            "el tamaño de parte contradice el plan durable."
        )
    try:
        issued, expires = DBIStoragePolicy.validate_access_window(
            issued_at=value.issued_at,
            expires_at=value.expires_at,
        )
    except (DBIStorageConflict, TypeError, ValueError) as error:
        raise DBIMultipartProviderConflict(str(error)) from error
    if issued < upload.initiated_at or expires <= issued:
        raise DBIMultipartProviderConflict(
            "la ventana del grant no es coherente con la carga."
        )
    return value


def validate_complete_request(
    value: object,
) -> DBIMultipartProviderCompleteRequest:
    if not isinstance(value, DBIMultipartProviderCompleteRequest):
        raise DBIMultipartProviderConflict(
            "request debe ser DBIMultipartProviderCompleteRequest."
        )
    upload = validate_upload(value.upload)
    try:
        parts = DBIMultipartPolicy.validate_complete_part_set(
            upload.plan,
            value.parts,
        )
    except ValueError as error:
        raise DBIMultipartProviderConflict(str(error)) from error
    if any(part.session_id != upload.session_id for part in parts):
        raise DBIMultipartProviderConflict(
            "las partes no pertenecen a la sesión solicitada."
        )
    if upload.plan.checksum_type is DBIMultipartChecksumType.FULL_OBJECT:
        if value.full_object_checksum is None:
            raise DBIMultipartProviderConflict(
                "la finalización FULL_OBJECT requiere checksum completo."
            )
        try:
            DBIMultipartPolicy.validate_transport_checksum(
                value.full_object_checksum,
                algorithm=upload.plan.checksum_algorithm,
            )
        except ValueError as error:
            raise DBIMultipartProviderConflict(str(error)) from error
    elif value.full_object_checksum is not None:
        raise DBIMultipartProviderConflict(
            "COMPOSITE no admite un checksum de objeto completo declarado."
        )
    return value


class DBIMultipartProviderPolicy:
    """Superficie explícita de validación para adaptadores."""

    utc = staticmethod(_utc)
    provider_ref = staticmethod(_provider_ref)
    validate_initiate_request = staticmethod(validate_initiate_request)
    validate_upload = staticmethod(validate_upload)
    validate_part_grant_request = staticmethod(validate_part_grant_request)
    validate_complete_request = staticmethod(validate_complete_request)
