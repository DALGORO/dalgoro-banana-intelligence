"""Servicio transaccional de entrega durable para trabajos DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dbi.delivery.contracts import (
    AnalysisCommandEnqueueEvidence,
    DeliveryEnvelope,
    DeliveryMessageStatus,
    DeliveryPersistenceConflict,
    DeliveryStream,
    prepare_delivery_payload,
)
from app.dbi.delivery.repository import DBIDeliveryRepository
from app.dbi.jobs.service_contracts import contract_sha256
from app.dbi.jobs.state_machine import (
    AnalysisJobStatus,
    evaluate_analysis_job_transition,
)
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt
from app.dbi.models.delivery import DBIDeliveryMessage
from app.schemas.dbi_analysis_jobs import (
    AnalysisJobCommand,
    AnalysisJobInputs,
    AnalysisJobResult,
)


def _utc(value: datetime, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DeliveryPersistenceConflict(
            f"{field_name} debe incluir zona horaria."
        )
    return value.astimezone(timezone.utc)


def _uuid(value: UUID, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise DeliveryPersistenceConflict(f"{field_name} debe ser UUID.")
    return value


def _ref(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DeliveryPersistenceConflict(f"{field_name} no es canónico.")
    return value


def _uuid_ref(value: str, *, field_name: str) -> UUID:
    normalized = _ref(value, field_name=field_name)
    try:
        parsed = UUID(normalized)
    except ValueError as error:
        raise DeliveryPersistenceConflict(f"{field_name} no es UUID.") from error
    if normalized != str(parsed):
        raise DeliveryPersistenceConflict(f"{field_name} no es UUID canónico.")
    return parsed


def _job_status(value: object) -> AnalysisJobStatus:
    try:
        return AnalysisJobStatus(value)
    except (TypeError, ValueError) as error:
        raise DeliveryPersistenceConflict("estado global de trabajo inválido.") from error


def _command_from_job(row: AnalysisJob) -> AnalysisJobCommand:
    command = AnalysisJobCommand(
        request_id=row.request_id,
        correlation_id=row.correlation_id,
        job_id=str(row.id),
        tenant_id=row.tenant_ref,
        farm_id=str(row.farm_id),
        lot_id=str(row.plot_id),
        inputs=AnalysisJobInputs(
            orthophoto_asset_id=row.orthophoto_asset_ref,
            boundary_asset_id=row.boundary_asset_ref,
            exclusions_asset_id=row.exclusions_asset_ref,
        ),
        model_version_id=row.model_version_ref,
        pipeline_config_version=row.pipeline_config_version,
        requested_by=row.requested_by_ref,
    )
    if contract_sha256(command) != row.command_sha256:
        raise DeliveryPersistenceConflict(
            "command_sha256 persistido no coincide con el comando reconstruido."
        )
    return command


class DBIAnalysisDeliveryService:
    """Coordina job, attempt y mensaje sin commit ni efectos externos."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DeliveryPersistenceConflict("session debe ser Session.")
        self._session = session
        self._delivery = DBIDeliveryRepository(session)

    def enqueue_analysis_command(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        job_id: UUID,
        queued_at: datetime,
        retry_authorized: bool = False,
        max_deliveries: int = 5,
    ) -> AnalysisCommandEnqueueEvidence:
        """Crea intento+mensaje y mueve accepted/failed a queued atómicamente."""

        tenant = _ref(tenant_ref, field_name="tenant_ref")
        farm = _uuid(farm_id, field_name="farm_id")
        job = _uuid(job_id, field_name="job_id")
        queued = _utc(queued_at, field_name="queued_at")

        row = self._session.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.id == job,
                AnalysisJob.tenant_ref == tenant,
                AnalysisJob.farm_id == farm,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise DeliveryPersistenceConflict("trabajo no disponible para encolar.")

        current = _job_status(row.status)
        if current is AnalysisJobStatus.QUEUED:
            return self._existing_queued(row)
        if current not in {AnalysisJobStatus.ACCEPTED, AnalysisJobStatus.FAILED}:
            raise DeliveryPersistenceConflict(
                "el trabajo no está en un estado encolable."
            )
        if current is AnalysisJobStatus.FAILED and not retry_authorized:
            raise DeliveryPersistenceConflict(
                "failed → queued exige reintento autorizado."
            )

        decision = evaluate_analysis_job_transition(
            current,
            AnalysisJobStatus.QUEUED,
            retry_authorized=retry_authorized,
        )
        previous_number = self._session.execute(
            select(func.max(AnalysisJobAttempt.attempt_number)).where(
                AnalysisJobAttempt.job_id == row.id
            )
        ).scalar_one()
        attempt_number = int(previous_number or 0) + 1
        attempt_id = uuid4()
        attempt = AnalysisJobAttempt(
            id=attempt_id,
            job_id=row.id,
            attempt_number=attempt_number,
            status=AnalysisJobStatus.QUEUED.value,
            queued_at=queued,
            created_at=queued,
            updated_at=queued,
        )
        self._session.add(attempt)
        self._session.flush()

        command = _command_from_job(row)
        payload = prepare_delivery_payload(command)
        message, created = self._delivery.publish(
            job_id=row.id,
            attempt_id=attempt_id,
            correlation_id=row.correlation_id,
            payload=payload,
            available_at=queued,
            max_deliveries=max_deliveries,
        )
        if not created:
            raise DeliveryPersistenceConflict(
                "un intento nuevo no puede reutilizar un mensaje previo."
            )

        row.status = decision.target.value
        row.updated_at = queued
        self._session.flush()
        return AnalysisCommandEnqueueEvidence(
            job_id=row.id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            job_status=AnalysisJobStatus.QUEUED,
            message=message,
            created=True,
        )

    def publish_analysis_result(
        self,
        result: AnalysisJobResult,
        *,
        available_at: datetime,
        max_deliveries: int = 5,
    ) -> tuple[DeliveryEnvelope, bool]:
        """Publica un resultado terminal sin persistir dominio ni artefactos."""

        if not isinstance(result, AnalysisJobResult):
            raise DeliveryPersistenceConflict("result debe ser AnalysisJobResult.")
        available = _utc(available_at, field_name="available_at")
        job_id = _uuid_ref(result.job_id, field_name="result.job_id")
        attempt_id = _uuid_ref(result.attempt_id, field_name="result.attempt_id")

        correlation = self._session.execute(
            select(AnalysisJob.correlation_id)
            .join(AnalysisJobAttempt, AnalysisJobAttempt.job_id == AnalysisJob.id)
            .where(
                AnalysisJob.id == job_id,
                AnalysisJobAttempt.id == attempt_id,
                AnalysisJobAttempt.job_id == job_id,
            )
        ).scalar_one_or_none()
        if correlation is None or correlation != result.correlation_id:
            raise DeliveryPersistenceConflict(
                "resultado no corresponde al job/attempt/correlation persistido."
            )

        payload = prepare_delivery_payload(result)
        return self._delivery.publish(
            job_id=job_id,
            attempt_id=attempt_id,
            correlation_id=result.correlation_id,
            payload=payload,
            available_at=available,
            max_deliveries=max_deliveries,
        )

    def _existing_queued(self, row: AnalysisJob) -> AnalysisCommandEnqueueEvidence:
        attempts = self._session.execute(
            select(AnalysisJobAttempt)
            .where(
                AnalysisJobAttempt.job_id == row.id,
                AnalysisJobAttempt.status == AnalysisJobStatus.QUEUED.value,
            )
            .order_by(AnalysisJobAttempt.attempt_number.desc())
            .limit(2)
            .with_for_update()
        ).scalars().all()
        if len(attempts) != 1:
            raise DeliveryPersistenceConflict(
                "queued exige exactamente un intento queued activo."
            )
        attempt = attempts[0]
        message_row = self._session.execute(
            select(DBIDeliveryMessage)
            .where(
                DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_COMMAND.value,
                DBIDeliveryMessage.attempt_id == attempt.id,
                DBIDeliveryMessage.job_id == row.id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if message_row is None:
            raise DeliveryPersistenceConflict(
                "queued exige un mensaje de comando durable."
            )
        message = DeliveryEnvelope(
            message_id=message_row.id,
            stream=DeliveryStream(message_row.stream),
            job_id=message_row.job_id,
            attempt_id=message_row.attempt_id,
            correlation_id=message_row.correlation_id,
            payload=prepare_delivery_payload(_command_from_job(row)),
            status=DeliveryMessageStatus(message_row.status),
            available_at=message_row.available_at,
            delivery_count=message_row.delivery_count,
            max_deliveries=message_row.max_deliveries,
        )
        if (
            message.payload.payload_json != message_row.payload_json
            or message.payload.payload_sha256 != message_row.payload_sha256
        ):
            raise DeliveryPersistenceConflict(
                "mensaje queued no coincide con el comando persistido."
            )
        return AnalysisCommandEnqueueEvidence(
            job_id=row.id,
            attempt_id=attempt.id,
            attempt_number=attempt.attempt_number,
            job_status=AnalysisJobStatus.QUEUED,
            message=message,
            created=False,
        )
