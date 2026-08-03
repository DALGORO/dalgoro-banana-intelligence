"""Política pura de tamaños, checksums e idempotencia multipartes DBI."""

from __future__ import annotations

import base64
import binascii
import re
from hashlib import sha256
from uuid import UUID

from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm,
    DBIMultipartChecksumType,
    DBIMultipartIdempotencyIdentity,
    DBIMultipartLimits,
    DBIMultipartPartEvidence,
    DBIMultipartPolicyReason,
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
    DBIMultipartTransitionPlan,
    DBIMultipartUploadPlan,
)


MIB = 1024 * 1024
GIB = 1024 * MIB
DBI_MULTIPART_DEFAULT_LIMITS = DBIMultipartLimits(
    synchronous_max_bytes=64 * MIB,
    multipart_max_bytes=20 * GIB,
    part_size_bytes=64 * MIB,
    max_parts=10_000,
    max_grants_per_window=8,
    max_client_concurrency=4,
)

_PROVIDER_MIN_PART_SIZE_BYTES = 5 * MIB
_PROVIDER_MAX_PART_SIZE_BYTES = 5 * GIB
_PROVIDER_MAX_PARTS = 10_000
_MAX_GRANT_WINDOW = 64
_MAX_CLIENT_CONCURRENCY = 16
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_TYPE_RE = re.compile(
    r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$"
)
_ETAG_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,256}$")
_CHECKSUM_LENGTHS = {
    DBIMultipartChecksumAlgorithm.SHA256: 32,
    DBIMultipartChecksumAlgorithm.CRC32: 4,
    DBIMultipartChecksumAlgorithm.CRC32C: 4,
    DBIMultipartChecksumAlgorithm.CRC64NVME: 8,
}
_ALLOWED_CHECKSUM_TYPES = {
    DBIMultipartChecksumAlgorithm.SHA256: frozenset(
        {DBIMultipartChecksumType.COMPOSITE}
    ),
    DBIMultipartChecksumAlgorithm.CRC32: frozenset(
        {
            DBIMultipartChecksumType.COMPOSITE,
            DBIMultipartChecksumType.FULL_OBJECT,
        }
    ),
    DBIMultipartChecksumAlgorithm.CRC32C: frozenset(
        {
            DBIMultipartChecksumType.COMPOSITE,
            DBIMultipartChecksumType.FULL_OBJECT,
        }
    ),
    DBIMultipartChecksumAlgorithm.CRC64NVME: frozenset(
        {DBIMultipartChecksumType.FULL_OBJECT}
    ),
}
_ALLOWED_TRANSITIONS = {
    DBIMultipartSessionState.INITIATED: frozenset(
        {
            DBIMultipartSessionState.UPLOADING,
            DBIMultipartSessionState.ABORTED,
            DBIMultipartSessionState.EXPIRED,
        }
    ),
    DBIMultipartSessionState.UPLOADING: frozenset(
        {
            DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION,
            DBIMultipartSessionState.ABORTED,
            DBIMultipartSessionState.EXPIRED,
        }
    ),
    DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION: frozenset(),
    DBIMultipartSessionState.ABORTED: frozenset(),
    DBIMultipartSessionState.EXPIRED: frozenset(),
    DBIMultipartSessionState.BLOCKED_BY_POLICY: frozenset(),
}


class DBIMultipartPolicyError(ValueError):
    """La declaración multipartes está fuera del contrato canónico."""


class DBIMultipartConflict(DBIMultipartPolicyError):
    """Un reintento o transición contradice evidencia durable."""


def _positive_int(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DBIMultipartPolicyError(f"{field_name} debe ser un entero positivo.")
    return value


def validate_limits(value: object) -> DBIMultipartLimits:
    """Valida límites configurables contra la frontera inicial del proveedor."""

    if not isinstance(value, DBIMultipartLimits):
        raise DBIMultipartPolicyError("limits debe ser DBIMultipartLimits.")
    synchronous = _positive_int(
        value.synchronous_max_bytes,
        field_name="synchronous_max_bytes",
    )
    maximum = _positive_int(
        value.multipart_max_bytes,
        field_name="multipart_max_bytes",
    )
    part_size = _positive_int(value.part_size_bytes, field_name="part_size_bytes")
    max_parts = _positive_int(value.max_parts, field_name="max_parts")
    grant_window = _positive_int(
        value.max_grants_per_window,
        field_name="max_grants_per_window",
    )
    concurrency = _positive_int(
        value.max_client_concurrency,
        field_name="max_client_concurrency",
    )
    if maximum <= synchronous:
        raise DBIMultipartPolicyError(
            "multipart_max_bytes debe superar synchronous_max_bytes."
        )
    if not _PROVIDER_MIN_PART_SIZE_BYTES <= part_size <= _PROVIDER_MAX_PART_SIZE_BYTES:
        raise DBIMultipartPolicyError("part_size_bytes está fuera de la política.")
    if max_parts > _PROVIDER_MAX_PARTS:
        raise DBIMultipartPolicyError("max_parts supera la frontera del proveedor.")
    if grant_window > min(max_parts, _MAX_GRANT_WINDOW):
        raise DBIMultipartPolicyError("La ventana de grants es demasiado grande.")
    if concurrency > min(grant_window, _MAX_CLIENT_CONCURRENCY):
        raise DBIMultipartPolicyError(
            "La concurrencia debe caber dentro de la ventana de grants."
        )
    return value


def validate_checksum_mode(
    algorithm: object,
    checksum_type: object,
) -> tuple[DBIMultipartChecksumAlgorithm, DBIMultipartChecksumType]:
    """Impide confundir un SHA-256 compuesto con un hash de objeto completo."""

    if not isinstance(algorithm, DBIMultipartChecksumAlgorithm):
        raise DBIMultipartPolicyError("algorithm no es canónico.")
    if not isinstance(checksum_type, DBIMultipartChecksumType):
        raise DBIMultipartPolicyError("checksum_type no es canónico.")
    if checksum_type not in _ALLOWED_CHECKSUM_TYPES[algorithm]:
        raise DBIMultipartPolicyError(
            "El algoritmo no admite ese tipo de checksum multipartes."
        )
    return algorithm, checksum_type


def build_upload_plan(
    *,
    size_bytes: int,
    limits: DBIMultipartLimits = DBI_MULTIPART_DEFAULT_LIMITS,
    checksum_algorithm: DBIMultipartChecksumAlgorithm = (
        DBIMultipartChecksumAlgorithm.SHA256
    ),
    checksum_type: DBIMultipartChecksumType = DBIMultipartChecksumType.COMPOSITE,
) -> DBIMultipartUploadPlan:
    """Enruta sin tocar red, disco, base de datos o contenido binario."""

    size = _positive_int(size_bytes, field_name="size_bytes")
    canonical_limits = validate_limits(limits)
    algorithm, canonical_type = validate_checksum_mode(
        checksum_algorithm,
        checksum_type,
    )
    if size <= canonical_limits.synchronous_max_bytes:
        return DBIMultipartUploadPlan(
            decision=DBIMultipartRoutingDecision.SYNCHRONOUS,
            size_bytes=size,
            part_size_bytes=None,
            part_count=0,
            max_grants_per_window=0,
            max_client_concurrency=0,
            checksum_algorithm=algorithm,
            checksum_type=canonical_type,
        )
    if size > canonical_limits.multipart_max_bytes:
        return DBIMultipartUploadPlan(
            decision=DBIMultipartRoutingDecision.BLOCKED_BY_POLICY,
            size_bytes=size,
            part_size_bytes=None,
            part_count=0,
            max_grants_per_window=0,
            max_client_concurrency=0,
            checksum_algorithm=algorithm,
            checksum_type=canonical_type,
            reason_code=DBIMultipartPolicyReason.SIZE_EXCEEDS_POLICY,
        )

    part_count = (size + canonical_limits.part_size_bytes - 1) // (
        canonical_limits.part_size_bytes
    )
    if part_count > canonical_limits.max_parts:
        return DBIMultipartUploadPlan(
            decision=DBIMultipartRoutingDecision.BLOCKED_BY_POLICY,
            size_bytes=size,
            part_size_bytes=None,
            part_count=0,
            max_grants_per_window=0,
            max_client_concurrency=0,
            checksum_algorithm=algorithm,
            checksum_type=canonical_type,
            reason_code=DBIMultipartPolicyReason.PART_COUNT_EXCEEDS_POLICY,
        )
    return DBIMultipartUploadPlan(
        decision=DBIMultipartRoutingDecision.MULTIPART,
        size_bytes=size,
        part_size_bytes=canonical_limits.part_size_bytes,
        part_count=part_count,
        max_grants_per_window=canonical_limits.max_grants_per_window,
        max_client_concurrency=canonical_limits.max_client_concurrency,
        checksum_algorithm=algorithm,
        checksum_type=canonical_type,
    )


def expected_part_size(plan: object, *, part_number: int) -> int:
    """Calcula el tamaño exacto de una parte, incluida la última."""

    if not isinstance(plan, DBIMultipartUploadPlan):
        raise DBIMultipartPolicyError("plan debe ser DBIMultipartUploadPlan.")
    if plan.decision is not DBIMultipartRoutingDecision.MULTIPART:
        raise DBIMultipartPolicyError("El plan no corresponde a multipartes.")
    number = _positive_int(part_number, field_name="part_number")
    if number > plan.part_count or plan.part_size_bytes is None:
        raise DBIMultipartPolicyError("part_number está fuera del plan.")
    if number < plan.part_count:
        return plan.part_size_bytes
    consumed = plan.part_size_bytes * (plan.part_count - 1)
    return plan.size_bytes - consumed


def validate_transport_checksum(
    value: object,
    *,
    algorithm: DBIMultipartChecksumAlgorithm,
) -> str:
    """Exige Base64 canónico con la longitud propia del algoritmo."""

    if not isinstance(algorithm, DBIMultipartChecksumAlgorithm):
        raise DBIMultipartPolicyError("algorithm no es canónico.")
    if not isinstance(value, str) or not value or value.strip() != value:
        raise DBIMultipartPolicyError("checksum debe ser Base64 canónico.")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise DBIMultipartPolicyError("checksum no es Base64 válido.") from None
    if len(decoded) != _CHECKSUM_LENGTHS[algorithm]:
        raise DBIMultipartPolicyError("checksum no coincide con el algoritmo.")
    if base64.b64encode(decoded).decode("ascii") != value:
        raise DBIMultipartPolicyError("checksum no usa Base64 canónico.")
    return value


def validate_part_evidence(
    value: object,
    *,
    plan: DBIMultipartUploadPlan,
) -> DBIMultipartPartEvidence:
    """Valida identidad, número, tamaño y evidencia opaca de una parte."""

    if not isinstance(value, DBIMultipartPartEvidence):
        raise DBIMultipartPolicyError(
            "part evidence debe ser DBIMultipartPartEvidence."
        )
    if not isinstance(value.session_id, UUID):
        raise DBIMultipartPolicyError("session_id debe ser UUID.")
    expected_size = expected_part_size(plan, part_number=value.part_number)
    if _positive_int(value.size_bytes, field_name="size_bytes") != expected_size:
        raise DBIMultipartConflict("El tamaño de la parte contradice el plan.")
    validate_transport_checksum(
        value.checksum,
        algorithm=plan.checksum_algorithm,
    )
    if not isinstance(value.etag, str) or not _ETAG_RE.fullmatch(value.etag):
        raise DBIMultipartPolicyError("etag no es una referencia opaca canónica.")
    return value


def validate_complete_part_set(
    plan: DBIMultipartUploadPlan,
    parts: object,
) -> tuple[DBIMultipartPartEvidence, ...]:
    """Normaliza partes desordenadas y rechaza faltantes o duplicadas."""

    if not isinstance(parts, (tuple, list)):
        raise DBIMultipartPolicyError("parts debe ser una secuencia acotada.")
    canonical: dict[int, DBIMultipartPartEvidence] = {}
    session_id: UUID | None = None
    for part in parts:
        evidence = validate_part_evidence(part, plan=plan)
        if session_id is None:
            session_id = evidence.session_id
        elif evidence.session_id != session_id:
            raise DBIMultipartConflict("Las partes pertenecen a sesiones distintas.")
        if evidence.part_number in canonical:
            raise DBIMultipartConflict("La lista contiene una parte duplicada.")
        canonical[evidence.part_number] = evidence
    expected_numbers = set(range(1, plan.part_count + 1))
    if set(canonical) != expected_numbers:
        raise DBIMultipartConflict("La lista de partes está incompleta.")
    ordered = tuple(canonical[number] for number in sorted(canonical))
    if sum(part.size_bytes for part in ordered) != plan.size_bytes:
        raise DBIMultipartConflict("La suma de partes contradice el objeto declarado.")
    return ordered


def build_idempotency_identity(
    *,
    idempotency_key: str,
    asset_id: UUID,
    content_type: str,
    size_bytes: int,
    sha256_hex: str,
) -> DBIMultipartIdempotencyIdentity:
    """Separa la huella de la clave de la huella del contenido solicitado."""

    if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY_RE.fullmatch(
        idempotency_key
    ):
        raise DBIMultipartPolicyError("idempotency_key no es canónica.")
    if not isinstance(asset_id, UUID):
        raise DBIMultipartPolicyError("asset_id debe ser UUID.")
    if not isinstance(content_type, str) or not _CONTENT_TYPE_RE.fullmatch(
        content_type
    ):
        raise DBIMultipartPolicyError("content_type no es canónico.")
    size = _positive_int(size_bytes, field_name="size_bytes")
    if not isinstance(sha256_hex, str) or not _SHA256_RE.fullmatch(sha256_hex):
        raise DBIMultipartPolicyError("sha256_hex no es canónico.")
    key_hash = sha256(
        f"dalgoro:dbi:multipart:key:v1\0{idempotency_key}".encode("utf-8")
    ).hexdigest()
    request_material = "\0".join(
        (
            "dalgoro:dbi:multipart:request:v1",
            str(asset_id),
            content_type,
            str(size),
            sha256_hex,
        )
    ).encode("utf-8")
    return DBIMultipartIdempotencyIdentity(
        key_hash=key_hash,
        request_fingerprint=sha256(request_material).hexdigest(),
    )


def validate_idempotent_reuse(
    existing: object,
    requested: object,
) -> bool:
    """Devuelve True solo para un reintento exacto de la misma clave."""

    if not isinstance(existing, DBIMultipartIdempotencyIdentity) or not isinstance(
        requested,
        DBIMultipartIdempotencyIdentity,
    ):
        raise DBIMultipartPolicyError("La identidad idempotente no es canónica.")
    if existing.key_hash != requested.key_hash:
        return False
    if existing.request_fingerprint != requested.request_fingerprint:
        raise DBIMultipartConflict(
            "La clave idempotente ya está vinculada a otra solicitud."
        )
    return True


def plan_transition(
    current: object,
    requested: object,
) -> DBIMultipartTransitionPlan:
    """Valida una transición o reconoce un reintento terminal exacto."""

    if not isinstance(current, DBIMultipartSessionState) or not isinstance(
        requested,
        DBIMultipartSessionState,
    ):
        raise DBIMultipartPolicyError("Los estados deben ser canónicos.")
    if current is requested:
        return DBIMultipartTransitionPlan(
            previous_state=current,
            next_state=requested,
            changed=False,
        )
    if requested not in _ALLOWED_TRANSITIONS[current]:
        raise DBIMultipartConflict("La transición multipartes no está permitida.")
    return DBIMultipartTransitionPlan(
        previous_state=current,
        next_state=requested,
        changed=True,
    )


class DBIMultipartPolicy:
    """Superficie explícita para futuros repositorios, servicios y adaptadores."""

    default_limits = DBI_MULTIPART_DEFAULT_LIMITS
    validate_limits = staticmethod(validate_limits)
    validate_checksum_mode = staticmethod(validate_checksum_mode)
    build_upload_plan = staticmethod(build_upload_plan)
    expected_part_size = staticmethod(expected_part_size)
    validate_transport_checksum = staticmethod(validate_transport_checksum)
    validate_part_evidence = staticmethod(validate_part_evidence)
    validate_complete_part_set = staticmethod(validate_complete_part_set)
    build_idempotency_identity = staticmethod(build_idempotency_identity)
    validate_idempotent_reuse = staticmethod(validate_idempotent_reuse)
    plan_transition = staticmethod(plan_transition)
