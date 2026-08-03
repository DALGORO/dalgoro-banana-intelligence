"""Contratos puros para ingesta multipartes de activos grandes DBI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class DBIMultipartSessionState(StrEnum):
    """Estados durables de una sesión, separados del estado del activo."""

    INITIATED = "initiated"
    UPLOADING = "uploading"
    COMPLETED_PENDING_CONTENT_VERIFICATION = (
        "completed_pending_content_verification"
    )
    ABORTED = "aborted"
    EXPIRED = "expired"
    BLOCKED_BY_POLICY = "blocked_by_policy"


class DBIMultipartRoutingDecision(StrEnum):
    """Ruta operativa determinada únicamente por metadata declarada."""

    SYNCHRONOUS = "synchronous"
    MULTIPART = "multipart"
    BLOCKED_BY_POLICY = "blocked_by_policy"


class DBIMultipartPolicyReason(StrEnum):
    """Motivos estables y visibles cuando una carga no puede iniciarse."""

    SIZE_EXCEEDS_POLICY = "asset_multipart_size_exceeds_policy"
    PART_COUNT_EXCEEDS_POLICY = "asset_multipart_part_count_exceeds_policy"


class DBIMultipartChecksumAlgorithm(StrEnum):
    """Algoritmos de integridad de transporte admitidos por el contrato."""

    SHA256 = "SHA256"
    CRC32 = "CRC32"
    CRC32C = "CRC32C"
    CRC64NVME = "CRC64NVME"


class DBIMultipartChecksumType(StrEnum):
    """Semántica del checksum devuelto por el proveedor."""

    COMPOSITE = "COMPOSITE"
    FULL_OBJECT = "FULL_OBJECT"


@dataclass(frozen=True, slots=True)
class DBIMultipartLimits:
    """Configuración explícita de enrutamiento y paralelismo."""

    synchronous_max_bytes: int
    multipart_max_bytes: int
    part_size_bytes: int
    max_parts: int
    max_grants_per_window: int
    max_client_concurrency: int


@dataclass(frozen=True, slots=True)
class DBIMultipartUploadPlan:
    """Plan acotado que no contiene URL, credencial o referencia de proveedor."""

    decision: DBIMultipartRoutingDecision
    size_bytes: int
    part_size_bytes: int | None
    part_count: int
    max_grants_per_window: int
    max_client_concurrency: int
    checksum_algorithm: DBIMultipartChecksumAlgorithm
    checksum_type: DBIMultipartChecksumType
    reason_code: DBIMultipartPolicyReason | None = None


@dataclass(frozen=True, slots=True)
class DBIMultipartPartEvidence:
    """Evidencia canónica de una parte ya transferida al proveedor."""

    session_id: UUID
    part_number: int
    size_bytes: int
    checksum: str = field(repr=False)
    etag: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DBIMultipartIdempotencyIdentity:
    """Huellas persistibles sin conservar la clave idempotente original."""

    key_hash: str = field(repr=False)
    request_fingerprint: str


@dataclass(frozen=True, slots=True)
class DBIMultipartTransitionPlan:
    """Resultado puro de solicitar una transición durable."""

    previous_state: DBIMultipartSessionState
    next_state: DBIMultipartSessionState
    changed: bool
