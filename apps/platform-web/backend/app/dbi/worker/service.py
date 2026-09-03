"""Servicio de aplicación del Worker DBI: claim → ejecución → resultado → ACK."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.dbi.delivery.contracts import DeliveryPersistenceConflict, DeliveryStream
from app.dbi.delivery.repository import DBIDeliveryRepository
from app.dbi.storage_contracts import (
    DBIPrivateObjectStore,
    DBIStorageError,
    DBIStorageIntegrityError,
)
from app.dbi.worker.artifacts import publish_artifacts
from app.dbi.worker.contracts import (
    DBIWorkerAckPending,
    DBIWorkerConflict,
    DBIWorkerFailureCode,
    DBIWorkerLeaseLost,
    DBIWorkerUnavailable,
    WORKER_PIPELINE_BUILD,
    WorkerProcessingEvidence,
)
from app.dbi.worker.heartbeat import DBIWorkerLeaseHeartbeat
from app.dbi.worker.materialization import DBIWorkerWorkspace, DBIWorkerWorkspaceManager
from app.dbi.worker.pipeline_adapter import DBILegacyPipelineAdapter
from app.dbi.worker.repository import (
    DBIWorkerRepository,
    WorkerStartDecision,
    WorkerStartDisposition,
)
from app.dbi.worker.resolution import DBIWorkerPlanResolver
from app.schemas.dbi_analysis_jobs import AnalysisJobResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _bounded_error(code: DBIWorkerFailureCode) -> list[str]:
    return [code.value]


class DBIAnalysisWorkerService:
    """Procesa como máximo un comando durable sin autoridad fuera de sus puertos."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        object_store: DBIPrivateObjectStore,
        *,
        workspace_root: str | Path,
        worker_ref: str,
        pipeline_adapter: DBILegacyPipelineAdapter | None = None,
        clock: Callable[[], datetime] = _utc_now,
        lease_seconds: int = 300,
        heartbeat_seconds: int = 60,
    ) -> None:
        if not callable(session_factory) or not callable(clock):
            raise TypeError("session_factory y clock deben ser invocables.")
        if not isinstance(worker_ref, str) or not worker_ref or worker_ref != worker_ref.strip():
            raise ValueError("worker_ref debe ser una referencia canónica.")
        if len(worker_ref) > 128:
            raise ValueError("worker_ref excede 128 caracteres.")
        self._session_factory = session_factory
        self._store = object_store
        self._workspace = DBIWorkerWorkspaceManager(workspace_root)
        self._worker_ref = worker_ref
        self._pipeline = pipeline_adapter or DBILegacyPipelineAdapter()
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise DBIWorkerConflict("clock del worker debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _claim(self):
        session = self._session_factory()
        try:
            lease = DBIDeliveryRepository(session).claim_one(
                stream=DeliveryStream.ANALYSIS_COMMAND,
                claimed_at=self._now(),
                lease_seconds=self._lease_seconds,
            )
            session.commit()
            return lease
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _ack(self, *, message_id, lease_ref) -> bool:
        session = self._session_factory()
        try:
            evidence = DBIDeliveryRepository(session).ack(
                message_id=message_id,
                lease_ref=lease_ref,
                delivered_at=self._now(),
            )
            session.commit()
            return evidence.changed
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _nack(self, *, message_id, lease_ref, code: DBIWorkerFailureCode) -> None:
        now = self._now()
        session = self._session_factory()
        try:
            DBIDeliveryRepository(session).nack(
                message_id=message_id,
                lease_ref=lease_ref,
                changed_at=now,
                available_at=now,
                error_code=code.value,
            )
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _begin(self, *, lease, command) -> WorkerStartDecision:
        session = self._session_factory()
        try:
            decision = DBIWorkerRepository(session).begin_attempt(
                job_id=lease.envelope.job_id,
                attempt_id=lease.envelope.attempt_id,
                correlation_id=command.correlation_id,
                worker_ref=self._worker_ref,
                pipeline_build_ref=WORKER_PIPELINE_BUILD,
                started_at=self._now(),
            )
            session.commit()
            return decision
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _parse_command(self, *, lease):
        session = self._session_factory()
        try:
            command = DBIWorkerPlanResolver(session, self._store).parse_command(
                lease.envelope
            )
            session.commit()
            return command
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _resolve_plan(self, *, lease):
        session = self._session_factory()
        try:
            plan = DBIWorkerPlanResolver(session, self._store).resolve(
                lease.envelope
            )
            session.commit()
            return plan
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _cancel_requested(self, *, job_id) -> bool:
        session = self._session_factory()
        try:
            requested = DBIWorkerRepository(session).cancel_requested(job_id=job_id)
            session.commit()
            return requested
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _finish(self, result: AnalysisJobResult, *, failure_code):
        session = self._session_factory()
        try:
            evidence = DBIWorkerRepository(session).finish_attempt_and_publish(
                result,
                failure_code=failure_code,
                finished_at=result.finished_at,
            )
            session.commit()
            return evidence
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _terminal_result(
        self,
        *,
        lease,
        started_at: datetime,
        status: str,
        failure_code: DBIWorkerFailureCode | None,
        artifacts=None,
        metrics=None,
        warnings=None,
    ) -> AnalysisJobResult:
        finished = self._now()
        if finished < started_at:
            finished = started_at
        return AnalysisJobResult(
            correlation_id=lease.envelope.correlation_id,
            job_id=str(lease.envelope.job_id),
            attempt_id=str(lease.envelope.attempt_id),
            status=status,
            pipeline_build=WORKER_PIPELINE_BUILD,
            started_at=started_at,
            finished_at=finished,
            artifacts=list(artifacts or []),
            metrics=dict(metrics or {}),
            findings=[],
            warnings=list(warnings or []),
            errors=([] if failure_code is None else _bounded_error(failure_code)),
        )

    def _finalize_and_ack(
        self,
        *,
        lease,
        result: AnalysisJobResult,
        failure_code: DBIWorkerFailureCode | None,
        replayed: bool,
    ) -> WorkerProcessingEvidence:
        self._finish(result, failure_code=failure_code)
        try:
            self._ack(
                message_id=lease.envelope.message_id,
                lease_ref=lease.lease_ref,
            )
        except BaseException as error:
            raise DBIWorkerAckPending(
                "resultado durable confirmado; ACK pendiente de recuperación."
            ) from error
        return WorkerProcessingEvidence(
            message_id=lease.envelope.message_id,
            job_id=lease.envelope.job_id,
            attempt_id=lease.envelope.attempt_id,
            terminal_status=result.status,
            replayed=replayed,
            acknowledged=True,
            failure_code=failure_code,
        )

    def process_one(self) -> WorkerProcessingEvidence | None:
        """Procesa un comando o devuelve None cuando no existe trabajo disponible."""

        lease = self._claim()
        if lease is None:
            return None

        heartbeat = DBIWorkerLeaseHeartbeat(
            self._session_factory,
            message_id=lease.envelope.message_id,
            lease_ref=lease.lease_ref,
            lease_seconds=self._lease_seconds,
            interval_seconds=self._heartbeat_seconds,
            clock=self._clock,
        )
        workspace: DBIWorkerWorkspace | None = None
        decision: WorkerStartDecision | None = None
        command = None
        phase = "command"

        try:
            heartbeat.beat(force=True)
            try:
                command = self._parse_command(lease=lease)
            except (DBIWorkerConflict, ValueError):
                self._nack(
                    message_id=lease.envelope.message_id,
                    lease_ref=lease.lease_ref,
                    code=DBIWorkerFailureCode.INVALID_COMMAND,
                )
                return WorkerProcessingEvidence(
                    message_id=lease.envelope.message_id,
                    job_id=lease.envelope.job_id,
                    attempt_id=lease.envelope.attempt_id,
                    terminal_status="failed",
                    replayed=False,
                    acknowledged=False,
                    failure_code=DBIWorkerFailureCode.INVALID_COMMAND,
                )

            decision = self._begin(lease=lease, command=command)
            if decision.disposition is WorkerStartDisposition.REPLAY_TERMINAL:
                assert decision.existing_result is not None
                self._workspace.cleanup_identity(
                    tenant_ref=command.tenant_id,
                    attempt_id=lease.envelope.attempt_id,
                )
                self._ack(
                    message_id=lease.envelope.message_id,
                    lease_ref=lease.lease_ref,
                )
                return WorkerProcessingEvidence(
                    message_id=lease.envelope.message_id,
                    job_id=lease.envelope.job_id,
                    attempt_id=lease.envelope.attempt_id,
                    terminal_status=decision.existing_result.status,
                    replayed=True,
                    acknowledged=True,
                    failure_code=(
                        None
                        if decision.existing_result.status == "succeeded"
                        else DBIWorkerFailureCode.CANCELED
                        if decision.existing_result.status == "canceled"
                        else DBIWorkerFailureCode.PIPELINE_FAILED
                    ),
                )

            if decision.disposition is WorkerStartDisposition.CANCEL_BEFORE_START:
                result = self._terminal_result(
                    lease=lease,
                    started_at=decision.started_at,
                    status="canceled",
                    failure_code=DBIWorkerFailureCode.CANCELED,
                )
                evidence = self._finalize_and_ack(
                    lease=lease,
                    result=result,
                    failure_code=DBIWorkerFailureCode.CANCELED,
                    replayed=False,
                )
                self._workspace.cleanup_identity(
                    tenant_ref=command.tenant_id,
                    attempt_id=lease.envelope.attempt_id,
                )
                return evidence

            phase = "resolution"
            heartbeat.beat(force=True)
            plan = self._resolve_plan(lease=lease)

            phase = "materialization"
            workspace = self._workspace.prepare(plan)
            self._workspace.materialize(
                self._store,
                plan=plan,
                workspace=workspace,
                progress=heartbeat.progress,
            )
            heartbeat.beat(force=True)

            if self._cancel_requested(job_id=plan.job_id):
                result = self._terminal_result(
                    lease=lease,
                    started_at=decision.started_at,
                    status="canceled",
                    failure_code=DBIWorkerFailureCode.CANCELED,
                )
                evidence = self._finalize_and_ack(
                    lease=lease,
                    result=result,
                    failure_code=DBIWorkerFailureCode.CANCELED,
                    replayed=False,
                )
                self._workspace.cleanup(workspace)
                return evidence

            phase = "pipeline"
            execution = self._pipeline.run(
                plan=plan,
                workspace=workspace,
                heartbeat=lambda: heartbeat.beat(force=False),
                cancel_requested=lambda: self._cancel_requested(job_id=plan.job_id),
            )
            heartbeat.beat(force=True)

            cancellation_wins = self._cancel_requested(job_id=plan.job_id)
            if execution.status == "canceled" or cancellation_wins:
                result = self._terminal_result(
                    lease=lease,
                    started_at=decision.started_at,
                    status="canceled",
                    failure_code=DBIWorkerFailureCode.CANCELED,
                )
                evidence = self._finalize_and_ack(
                    lease=lease,
                    result=result,
                    failure_code=DBIWorkerFailureCode.CANCELED,
                    replayed=False,
                )
                self._workspace.cleanup(workspace)
                return evidence

            if execution.status == "failed":
                result = self._terminal_result(
                    lease=lease,
                    started_at=decision.started_at,
                    status="failed",
                    failure_code=DBIWorkerFailureCode.PIPELINE_FAILED,
                    metrics={"return_code": execution.return_code},
                )
                evidence = self._finalize_and_ack(
                    lease=lease,
                    result=result,
                    failure_code=DBIWorkerFailureCode.PIPELINE_FAILED,
                    replayed=False,
                )
                self._workspace.cleanup(workspace)
                return evidence

            phase = "artifacts"
            if execution.run_directory is None:
                raise DBIWorkerConflict("pipeline exitoso no declaró su ejecución.")
            artifacts = publish_artifacts(
                self._store,
                plan=plan,
                workspace=workspace,
                run_directory=Path(execution.run_directory),
                created_at=self._now(),
            )
            heartbeat.beat(force=True)

            if self._cancel_requested(job_id=plan.job_id):
                result = self._terminal_result(
                    lease=lease,
                    started_at=decision.started_at,
                    status="canceled",
                    failure_code=DBIWorkerFailureCode.CANCELED,
                )
                evidence = self._finalize_and_ack(
                    lease=lease,
                    result=result,
                    failure_code=DBIWorkerFailureCode.CANCELED,
                    replayed=False,
                )
                self._workspace.cleanup(workspace)
                return evidence

            result = self._terminal_result(
                lease=lease,
                started_at=decision.started_at,
                status="succeeded",
                failure_code=None,
                artifacts=artifacts,
                metrics={"artifact_count": len(artifacts)},
            )
            evidence = self._finalize_and_ack(
                lease=lease,
                result=result,
                failure_code=None,
                replayed=False,
            )
            self._workspace.cleanup(workspace)
            return evidence

        except DBIWorkerAckPending:
            if workspace is not None:
                self._workspace.cleanup(workspace)
            raise
        except DBIWorkerLeaseLost:
            if workspace is not None:
                self._workspace.cleanup(workspace)
            raise
        except BaseException as error:
            if decision is None or command is None:
                try:
                    self._nack(
                        message_id=lease.envelope.message_id,
                        lease_ref=lease.lease_ref,
                        code=DBIWorkerFailureCode.INTERNAL_FAILURE,
                    )
                except DeliveryPersistenceConflict:
                    pass
                raise

            if isinstance(error, DBIStorageIntegrityError):
                failure = DBIWorkerFailureCode.STORAGE_INTEGRITY
            elif isinstance(error, DBIWorkerUnavailable):
                failure = DBIWorkerFailureCode.RESOURCE_UNAVAILABLE
            elif isinstance(error, DBIStorageError):
                failure = DBIWorkerFailureCode.RESOURCE_UNAVAILABLE
            elif phase == "resolution":
                failure = DBIWorkerFailureCode.RESOURCE_UNAVAILABLE
            elif phase == "materialization":
                failure = DBIWorkerFailureCode.STORAGE_INTEGRITY
            elif phase == "pipeline":
                failure = DBIWorkerFailureCode.PIPELINE_FAILED
            elif phase == "artifacts":
                failure = DBIWorkerFailureCode.STORAGE_INTEGRITY
            else:
                failure = DBIWorkerFailureCode.INTERNAL_FAILURE

            try:
                heartbeat.beat(force=True)
                if self._cancel_requested(job_id=lease.envelope.job_id):
                    failure = DBIWorkerFailureCode.CANCELED
                    status = "canceled"
                else:
                    status = "failed"
                result = self._terminal_result(
                    lease=lease,
                    started_at=decision.started_at,
                    status=status,
                    failure_code=failure,
                )
                evidence = self._finalize_and_ack(
                    lease=lease,
                    result=result,
                    failure_code=failure,
                    replayed=False,
                )
                if workspace is not None:
                    self._workspace.cleanup(workspace)
                return evidence
            except DBIWorkerAckPending:
                if workspace is not None:
                    self._workspace.cleanup(workspace)
                raise
            except DBIWorkerLeaseLost:
                if workspace is not None:
                    self._workspace.cleanup(workspace)
                raise
