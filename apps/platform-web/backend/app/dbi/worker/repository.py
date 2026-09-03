"""Persistencia operacional mínima del Worker DBI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.delivery.contracts import (
    DeliveryEnvelope,
    DeliveryPersistenceConflict,
    DeliveryStream,
)
from app.dbi.delivery.service import DBIAnalysisDeliveryService
from app.dbi.jobs.service_contracts import contract_sha256
from app.dbi.jobs.state_machine import (
    AnalysisJobStatus,
    InvalidAnalysisJobTransition,
    evaluate_analysis_job_transition,
)
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt
from app.dbi.models.delivery import DBIDeliveryMessage
from app.dbi.worker.contracts import DBIWorkerConflict, DBIWorkerFailureCode
from app.schemas.dbi_analysis_jobs import AnalysisJobResult


class WorkerStartDisposition(StrEnum):
    STARTED = "started"
    RESUMED = "resumed"
    CANCEL_BEFORE_START = "cancel_before_start"
    REPLAY_TERMINAL = "replay_terminal"


@dataclass(frozen=True, slots=True)
class WorkerStartDecision:
    disposition: WorkerStartDisposition
    started_at: datetime
    existing_result: AnalysisJobResult | None = None


def _utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DBIWorkerConflict(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _job_status(value: str) -> AnalysisJobStatus:
    try:
        return AnalysisJobStatus(value)
    except ValueError as error:
        raise DBIWorkerConflict("estado de Job persistido inválido.") from error


def _terminal_status_for_result(result: AnalysisJobResult) -> AnalysisJobStatus:
    if result.status == "succeeded":
        return AnalysisJobStatus.SUCCEEDED
    if result.status == "failed":
        return AnalysisJobStatus.FAILED
    return AnalysisJobStatus.CANCELED


def _attempt_terminal_status(result: AnalysisJobResult) -> str:
    return result.status


class DBIWorkerRepository:
    """Opera sobre una sesión externa; nunca hace commit/rollback ni I/O externo."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session debe ser Session.")
        self._session = session

    def _lock_job_attempt(
        self,
        *,
        job_id: UUID,
        attempt_id: UUID,
    ) -> tuple[AnalysisJob, AnalysisJobAttempt]:
        job = self._session.execute(
            select(AnalysisJob)
            .where(AnalysisJob.id == job_id)
            .with_for_update()
        ).scalar_one_or_none()
        attempt = self._session.execute(
            select(AnalysisJobAttempt)
            .where(
                AnalysisJobAttempt.id == attempt_id,
                AnalysisJobAttempt.job_id == job_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if job is None or attempt is None:
            raise DBIWorkerConflict("job/attempt no disponible para el worker.")
        return job, attempt

    def _existing_result_message(
        self,
        *,
        job_id: UUID,
        attempt_id: UUID,
        lock: bool,
    ) -> DBIDeliveryMessage | None:
        statement = select(DBIDeliveryMessage).where(
            DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_RESULT.value,
            DBIDeliveryMessage.job_id == job_id,
            DBIDeliveryMessage.attempt_id == attempt_id,
        )
        if lock:
            statement = statement.with_for_update()
        return self._session.execute(statement).scalar_one_or_none()

    def existing_terminal_result(
        self,
        *,
        job_id: UUID,
        attempt_id: UUID,
    ) -> AnalysisJobResult | None:
        row = self._existing_result_message(
            job_id=job_id,
            attempt_id=attempt_id,
            lock=False,
        )
        if row is None:
            return None
        try:
            return AnalysisJobResult.model_validate_json(row.payload_json)
        except ValidationError as error:
            raise DBIWorkerConflict("resultado durable existente es inválido.") from error

    def begin_attempt(
        self,
        *,
        job_id: UUID,
        attempt_id: UUID,
        correlation_id: str,
        worker_ref: str,
        pipeline_build_ref: str,
        started_at: datetime,
    ) -> WorkerStartDecision:
        started = _utc(started_at, field_name="started_at")
        job, attempt = self._lock_job_attempt(job_id=job_id, attempt_id=attempt_id)
        if job.correlation_id != correlation_id:
            raise DBIWorkerConflict("correlation_id del attempt no coincide.")

        result_row = self._existing_result_message(
            job_id=job_id,
            attempt_id=attempt_id,
            lock=True,
        )
        if result_row is not None:
            try:
                result = AnalysisJobResult.model_validate_json(result_row.payload_json)
            except ValidationError as error:
                raise DBIWorkerConflict("resultado durable existente es inválido.") from error
            expected_job = _terminal_status_for_result(result).value
            expected_attempt = _attempt_terminal_status(result)
            if job.status != expected_job or attempt.status != expected_attempt:
                raise DBIWorkerConflict(
                    "resultado durable terminal diverge del estado operacional."
                )
            if attempt.result_sha256 != contract_sha256(result):
                raise DBIWorkerConflict("result_sha256 terminal no coincide.")
            return WorkerStartDecision(
                disposition=WorkerStartDisposition.REPLAY_TERMINAL,
                started_at=result.started_at,
                existing_result=result,
            )

        job_status = _job_status(job.status)
        if job_status is AnalysisJobStatus.CANCEL_REQUESTED:
            if attempt.status not in {"queued", "running"}:
                raise DBIWorkerConflict("attempt cancelable en estado inválido.")
            effective_started = (
                started
                if attempt.started_at is None
                else _utc(attempt.started_at, field_name="attempt.started_at")
            )
            return WorkerStartDecision(
                disposition=WorkerStartDisposition.CANCEL_BEFORE_START,
                started_at=effective_started,
            )

        if job_status is AnalysisJobStatus.QUEUED and attempt.status == "queued":
            try:
                decision = evaluate_analysis_job_transition(
                    job_status,
                    AnalysisJobStatus.RUNNING,
                )
            except InvalidAnalysisJobTransition as error:
                raise DBIWorkerConflict(str(error)) from error
            job.status = decision.target.value
            job.updated_at = started
            attempt.status = "running"
            attempt.worker_ref = worker_ref
            attempt.pipeline_build_ref = pipeline_build_ref
            attempt.started_at = started
            attempt.updated_at = started
            self._session.flush()
            return WorkerStartDecision(
                disposition=WorkerStartDisposition.STARTED,
                started_at=started,
            )

        if job_status is AnalysisJobStatus.RUNNING and attempt.status == "running":
            if attempt.started_at is None:
                raise DBIWorkerConflict("attempt running carece de started_at.")
            effective_started = _utc(
                attempt.started_at,
                field_name="attempt.started_at",
            )
            if (
                attempt.pipeline_build_ref is not None
                and attempt.pipeline_build_ref != pipeline_build_ref
            ):
                raise DBIWorkerConflict(
                    "un attempt no puede reanudarse con otro pipeline build."
                )
            attempt.worker_ref = worker_ref
            if attempt.pipeline_build_ref is None:
                attempt.pipeline_build_ref = pipeline_build_ref
            attempt.updated_at = started
            self._session.flush()
            return WorkerStartDecision(
                disposition=WorkerStartDisposition.RESUMED,
                started_at=effective_started,
            )

        raise DBIWorkerConflict(
            "job/attempt no se encuentran en un estado ejecutable."
        )

    def cancel_requested(self, *, job_id: UUID) -> bool:
        status = self._session.execute(
            select(AnalysisJob.status).where(AnalysisJob.id == job_id)
        ).scalar_one_or_none()
        if status is None:
            raise DBIWorkerConflict("Job no disponible durante cancelación.")
        return status == AnalysisJobStatus.CANCEL_REQUESTED.value

    def finish_attempt_and_publish(
        self,
        result: AnalysisJobResult,
        *,
        failure_code: DBIWorkerFailureCode | None,
        finished_at: datetime,
        max_deliveries: int = 5,
    ) -> tuple[DeliveryEnvelope, bool]:
        finished = _utc(finished_at, field_name="finished_at")
        try:
            job_id = UUID(result.job_id)
            attempt_id = UUID(result.attempt_id)
        except ValueError as error:
            raise DBIWorkerConflict("resultado terminal contiene IDs inválidos.") from error
        job, attempt = self._lock_job_attempt(job_id=job_id, attempt_id=attempt_id)
        if job.correlation_id != result.correlation_id:
            raise DBIWorkerConflict("resultado terminal no corresponde al Job.")

        expected_job = _terminal_status_for_result(result)
        expected_attempt = _attempt_terminal_status(result)
        digest = contract_sha256(result)
        existing = self._existing_result_message(
            job_id=job_id,
            attempt_id=attempt_id,
            lock=True,
        )
        if existing is not None:
            try:
                persisted = AnalysisJobResult.model_validate_json(existing.payload_json)
            except ValidationError as error:
                raise DBIWorkerConflict("resultado durable existente es inválido.") from error
            if contract_sha256(persisted) != digest:
                raise DBIWorkerConflict("attempt ya posee un resultado diferente.")
            if job.status != expected_job.value or attempt.status != expected_attempt:
                raise DBIWorkerConflict("estado terminal existente diverge del resultado.")
            service = DBIAnalysisDeliveryService(self._session)
            return service.publish_analysis_result(
                result,
                available_at=finished,
                max_deliveries=max_deliveries,
            )

        current_job = _job_status(job.status)
        if result.status == "canceled":
            if current_job is not AnalysisJobStatus.CANCEL_REQUESTED:
                raise DBIWorkerConflict("canceled exige Job cancel_requested.")
            if attempt.status not in {"queued", "running"}:
                raise DBIWorkerConflict("attempt no admite cancelación terminal.")
            if attempt.started_at is None:
                attempt.started_at = result.started_at
            elif _utc(attempt.started_at, field_name="attempt.started_at") != result.started_at:
                raise DBIWorkerConflict("result.started_at diverge del attempt cancelado.")
        else:
            if current_job is not AnalysisJobStatus.RUNNING or attempt.status != "running":
                raise DBIWorkerConflict("resultado no cancelado exige ejecución running.")
            if attempt.started_at is None:
                raise DBIWorkerConflict("attempt running carece de started_at terminal.")
            if _utc(attempt.started_at, field_name="attempt.started_at") != result.started_at:
                raise DBIWorkerConflict("result.started_at diverge del attempt.")
            try:
                evaluate_analysis_job_transition(current_job, expected_job)
            except InvalidAnalysisJobTransition as error:
                raise DBIWorkerConflict(str(error)) from error

        service = DBIAnalysisDeliveryService(self._session)
        envelope, created = service.publish_analysis_result(
            result,
            available_at=finished,
            max_deliveries=max_deliveries,
        )
        if not created:
            raise DeliveryPersistenceConflict(
                "resultado nuevo no puede reutilizar un mensaje no observado."
            )

        job.status = expected_job.value
        job.updated_at = finished
        attempt.status = expected_attempt
        attempt.result_sha256 = digest
        attempt.failure_code = (
            None if failure_code is None else failure_code.value
        )
        attempt.finished_at = finished
        attempt.updated_at = finished
        self._session.flush()
        return envelope, True
