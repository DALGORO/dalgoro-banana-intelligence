"""Contratos puros e inmutables para la entrega durable DBI."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.dbi.jobs.service_contracts import canonical_contract_bytes
from app.dbi.jobs.state_machine import AnalysisJobStatus
from app.schemas.dbi_analysis_jobs import (
    ANALYSIS_JOB_COMMAND_SCHEMA_VERSION,
    ANALYSIS_JOB_RESULT_SCHEMA_VERSION,
    AnalysisJobCommand,
    AnalysisJobResult,
    OpaqueReference,
    Sha256Digest,
)

MAX_DELIVERY_PAYLOAD_BYTES = 1024 * 1024
DELIVERY_ENVELOPE_SCHEMA_VERSION = "dbi-delivery-envelope.v1"
DELIVERY_LEASE_SCHEMA_VERSION = "dbi-delivery-lease.v1"
DELIVERY_LEASE_RENEWAL_SCHEMA_VERSION = "dbi-delivery-lease-renewal.v1"


class DeliveryStream(StrEnum):
    """Canales durables permitidos por la arquitectura DBI."""

    ANALYSIS_COMMAND = "analysis_command"
    ANALYSIS_RESULT = "analysis_result"


class DeliveryMessageStatus(StrEnum):
    """Estados persistidos de un mensaje durable."""

    PENDING = "pending"
    LEASED = "leased"
    DELIVERED = "delivered"
    DEAD_LETTER = "dead_letter"


class DeliveryContractError(ValueError):
    """El contrato de entrega no satisface sus invariantes."""


class DeliveryPersistenceConflict(RuntimeError):
    """El estado persistido no permite la operación solicitada."""


class DeliveryMessageUnavailable(LookupError):
    """El mensaje solicitado no existe o no está disponible."""


class _StrictDeliveryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
        frozen=True,
    )


class PreparedDeliveryPayload(_StrictDeliveryModel):
    """Payload canónico listo para persistirse sin reinterpretación."""

    stream: DeliveryStream
    schema_version: Literal[
        "analysis-job-command.v1",
        "analysis-job-result.v1",
    ]
    payload_json: str = Field(min_length=2)
    payload_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_payload(self) -> "PreparedDeliveryPayload":
        raw = self.payload_json.encode("utf-8")
        if len(raw) > MAX_DELIVERY_PAYLOAD_BYTES:
            raise ValueError("payload de entrega excede 1 MiB.")

        try:
            decoded = json.loads(self.payload_json)
        except json.JSONDecodeError as error:
            raise ValueError("payload_json no es JSON válido.") from error
        if not isinstance(decoded, dict):
            raise ValueError("payload_json debe contener un objeto JSON.")

        canonical = json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if canonical != self.payload_json:
            raise ValueError("payload_json debe usar serialización canónica.")

        expected_schema = _schema_for_stream(self.stream)
        if self.schema_version != expected_schema:
            raise ValueError("schema_version no corresponde al stream.")
        if decoded.get("schema_version") != expected_schema:
            raise ValueError("schema_version del payload no corresponde al stream.")

        digest = hashlib.sha256(raw).hexdigest()
        if digest != self.payload_sha256:
            raise ValueError("payload_sha256 no coincide con payload_json.")
        return self


class DeliveryEnvelope(_StrictDeliveryModel):
    """Evidencia durable de un mensaje sin credenciales ni binarios."""

    schema_version: Literal["dbi-delivery-envelope.v1"] = (
        DELIVERY_ENVELOPE_SCHEMA_VERSION
    )
    message_id: UUID
    stream: DeliveryStream
    job_id: UUID
    attempt_id: UUID
    correlation_id: OpaqueReference
    payload: PreparedDeliveryPayload
    status: DeliveryMessageStatus
    available_at: AwareDatetime
    delivery_count: int = Field(ge=0, le=100)
    max_deliveries: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def validate_envelope(self) -> "DeliveryEnvelope":
        if self.payload.stream is not self.stream:
            raise ValueError("payload y envelope deben usar el mismo stream.")
        if self.delivery_count > self.max_deliveries:
            raise ValueError("delivery_count no puede superar max_deliveries.")
        return self


class DeliveryLease(_StrictDeliveryModel):
    """Lease temporal que autoriza una única entrega."""

    schema_version: Literal["dbi-delivery-lease.v1"] = DELIVERY_LEASE_SCHEMA_VERSION
    lease_ref: UUID
    claimed_at: AwareDatetime
    lease_expires_at: AwareDatetime
    envelope: DeliveryEnvelope

    @model_validator(mode="after")
    def validate_lease(self) -> "DeliveryLease":
        if self.envelope.status is not DeliveryMessageStatus.LEASED:
            raise ValueError("un lease exige envelope en estado leased.")
        if self.lease_expires_at <= self.claimed_at:
            raise ValueError("lease_expires_at debe ser posterior a claimed_at.")
        return self


class DeliveryLeaseRenewalEvidence(_StrictDeliveryModel):
    """Evidencia exacta e idempotente de una renovación del lease activo."""

    schema_version: Literal["dbi-delivery-lease-renewal.v1"] = (
        DELIVERY_LEASE_RENEWAL_SCHEMA_VERSION
    )
    message_id: UUID
    lease_ref: UUID
    renewed_at: AwareDatetime
    previous_expires_at: AwareDatetime
    lease_expires_at: AwareDatetime
    changed: bool

    @model_validator(mode="after")
    def validate_renewal(self) -> "DeliveryLeaseRenewalEvidence":
        if self.previous_expires_at <= self.renewed_at:
            raise ValueError("sólo un lease todavía vigente puede renovarse.")
        if self.changed:
            if self.lease_expires_at <= self.previous_expires_at:
                raise ValueError("una renovación cambiada debe extender el vencimiento.")
        elif self.lease_expires_at != self.previous_expires_at:
            raise ValueError("un replay sin cambios debe conservar el vencimiento.")
        return self


class DeliveryTransitionEvidence(_StrictDeliveryModel):
    """Resultado acotado de ack, nack o dead-letter."""

    message_id: UUID
    status: DeliveryMessageStatus
    changed: bool
    delivery_count: int = Field(ge=0, le=100)


class AnalysisCommandEnqueueEvidence(_StrictDeliveryModel):
    """Prueba atómica de intento, mensaje y transición global a queued."""

    job_id: UUID
    attempt_id: UUID
    attempt_number: int = Field(gt=0)
    job_status: AnalysisJobStatus
    message: DeliveryEnvelope
    created: bool

    @model_validator(mode="after")
    def validate_enqueue(self) -> "AnalysisCommandEnqueueEvidence":
        if self.job_status is not AnalysisJobStatus.QUEUED:
            raise ValueError("el trabajo encolado debe quedar queued.")
        if self.message.stream is not DeliveryStream.ANALYSIS_COMMAND:
            raise ValueError("el encolado de análisis exige stream de comando.")
        if self.message.job_id != self.job_id:
            raise ValueError("message.job_id no coincide con job_id.")
        if self.message.attempt_id != self.attempt_id:
            raise ValueError("message.attempt_id no coincide con attempt_id.")
        return self


def _schema_for_stream(stream: DeliveryStream) -> str:
    if stream is DeliveryStream.ANALYSIS_COMMAND:
        return ANALYSIS_JOB_COMMAND_SCHEMA_VERSION
    if stream is DeliveryStream.ANALYSIS_RESULT:
        return ANALYSIS_JOB_RESULT_SCHEMA_VERSION
    raise DeliveryContractError("stream de entrega no soportado.")


def prepare_delivery_payload(
    contract: AnalysisJobCommand | AnalysisJobResult,
) -> PreparedDeliveryPayload:
    """Serializa un contrato aprobado una sola vez y fija su huella."""

    if isinstance(contract, AnalysisJobCommand):
        stream = DeliveryStream.ANALYSIS_COMMAND
        schema_version = ANALYSIS_JOB_COMMAND_SCHEMA_VERSION
    elif isinstance(contract, AnalysisJobResult):
        stream = DeliveryStream.ANALYSIS_RESULT
        schema_version = ANALYSIS_JOB_RESULT_SCHEMA_VERSION
    else:
        raise DeliveryContractError("contrato de entrega no soportado.")

    raw = canonical_contract_bytes(contract)
    if len(raw) > MAX_DELIVERY_PAYLOAD_BYTES:
        raise DeliveryContractError("payload de entrega excede 1 MiB.")
    return PreparedDeliveryPayload(
        stream=stream,
        schema_version=schema_version,
        payload_json=raw.decode("utf-8"),
        payload_sha256=hashlib.sha256(raw).hexdigest(),
    )
