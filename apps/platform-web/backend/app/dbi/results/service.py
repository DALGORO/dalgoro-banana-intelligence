"""Servicio transaccional de verificación e ingesta de resultados DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.delivery.contracts import (
    DeliveryLease,
    DeliveryStream,
    prepare_delivery_payload,
)
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt
from app.dbi.results.contracts import (
    DBIResultIngestionConflict,
    DBIResultIngestionUnavailable,
    ResultIngestionEvidence,
    canonical_uuid,
    prepare_analysis_result,
)
from app.dbi.results.repository import DBIResultRepository
from app.dbi.storage_contracts import (
    DBIPrivateObjectStore,
    DBIStorageError,
    DBIStorageObjectState,
    DBIStoragePurpose,
)
from app.dbi.storage_policy import DBIStoragePolicy
from app.schemas.dbi_analysis_jobs import AnalysisJobResult, ArtifactManifest

_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled"})


def _utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DBIResultIngestionConflict(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


class DBIAnalysisResultIngestionService:
    """Valida autoridad + Storage y persiste sin commit, rollback ni ACK."""

    def __init__(
        self,
        session: Session,
        object_store: DBIPrivateObjectStore,
    ) -> None:
        if not isinstance(session, Session):
            raise DBIResultIngestionConflict("session debe ser Session.")
        self._session = session
        self._store = object_store
        self._repository = DBIResultRepository(session)

    def _parse(self, lease: DeliveryLease) -> AnalysisJobResult:
        if not isinstance(lease, DeliveryLease):
            raise DBIResultIngestionConflict("lease debe ser DeliveryLease.")
        envelope = lease.envelope
        if envelope.stream is not DeliveryStream.ANALYSIS_RESULT:
            raise DBIResultIngestionConflict(
                "Result sólo consume DeliveryStream.ANALYSIS_RESULT."
            )
        try:
            result = AnalysisJobResult.model_validate_json(
                envelope.payload.payload_json
            )
        except (ValidationError, ValueError) as error:
            raise DBIResultIngestionConflict(
                "payload durable no es analysis-job-result.v1 válido."
            ) from error
        canonical = prepare_delivery_payload(result)
        if (
            canonical.stream is not DeliveryStream.ANALYSIS_RESULT
            or canonical.payload_json != envelope.payload.payload_json
            or canonical.payload_sha256 != envelope.payload.payload_sha256
        ):
            raise DBIResultIngestionConflict(
                "payload durable diverge de su representación canónica."
            )
        return result

    def _authority(
        self,
        lease: DeliveryLease,
        result: AnalysisJobResult,
        *,
        result_sha256: str,
    ) -> tuple[AnalysisJob, AnalysisJobAttempt, UUID, UUID]:
        job_id = canonical_uuid(result.job_id, field_name="result.job_id")
        attempt_id = canonical_uuid(
            result.attempt_id,
            field_name="result.attempt_id",
        )
        envelope = lease.envelope
        if (
            envelope.job_id != job_id
            or envelope.attempt_id != attempt_id
            or envelope.correlation_id != result.correlation_id
        ):
            raise DBIResultIngestionConflict(
                "envelope no coincide con job/attempt/correlation del resultado."
            )

        row = self._session.execute(
            select(AnalysisJob, AnalysisJobAttempt)
            .join(
                AnalysisJobAttempt,
                AnalysisJobAttempt.job_id == AnalysisJob.id,
            )
            .where(
                AnalysisJob.id == job_id,
                AnalysisJobAttempt.id == attempt_id,
                AnalysisJobAttempt.job_id == job_id,
            )
        ).one_or_none()
        if row is None:
            raise DBIResultIngestionUnavailable("job/attempt no disponible.")
        job, attempt = row

        if (
            job.correlation_id != result.correlation_id
            or job.status not in _TERMINAL_STATUSES
            or attempt.status not in _TERMINAL_STATUSES
            or job.status != result.status
            or attempt.status != result.status
        ):
            raise DBIResultIngestionConflict(
                "estado/correlation del resultado diverge de Job/Attempt."
            )
        if attempt.result_sha256 != result_sha256:
            raise DBIResultIngestionConflict(
                "result_sha256 no coincide con el Attempt terminal."
            )
        if attempt.pipeline_build_ref != result.pipeline_build:
            raise DBIResultIngestionConflict(
                "pipeline_build no coincide con el Attempt terminal."
            )
        if attempt.started_at is None or attempt.finished_at is None:
            raise DBIResultIngestionConflict(
                "Attempt terminal carece de timestamps completos."
            )
        if (
            _utc(attempt.started_at, field_name="attempt.started_at")
            != _utc(result.started_at, field_name="result.started_at")
            or _utc(attempt.finished_at, field_name="attempt.finished_at")
            != _utc(result.finished_at, field_name="result.finished_at")
        ):
            raise DBIResultIngestionConflict(
                "timestamps del resultado divergen del Attempt terminal."
            )
        for finding in result.findings:
            if finding.model_version_id != job.model_version_ref:
                raise DBIResultIngestionConflict(
                    "finding no usa el modelo congelado del Job."
                )
        return job, attempt, job_id, attempt_id

    def _verify_artifact(
        self,
        manifest: ArtifactManifest,
        *,
        tenant_ref: str,
        job_id: UUID,
    ) -> None:
        if canonical_uuid(manifest.job_id, field_name="artifact.job_id") != job_id:
            raise DBIResultIngestionConflict(
                "artifact.job_id no coincide con el resultado."
            )
        artifact_id = canonical_uuid(
            manifest.artifact_id,
            field_name="artifact.artifact_id",
        )
        address = DBIStoragePolicy.build_address(
            tenant_ref=tenant_ref,
            purpose=DBIStoragePurpose.ANALYSIS_ARTIFACT,
            object_id=artifact_id,
        )
        if manifest.object_key != address.object_key:
            raise DBIResultIngestionConflict(
                "object_key del manifest no es la clave privada canónica."
            )
        expected = DBIStoragePolicy.build_metadata(
            address=address,
            content_type=manifest.content_type,
            size_bytes=manifest.size_bytes,
            sha256_hex=manifest.sha256,
        )
        try:
            record = self._store.stat(address)
        except DBIStorageError as error:
            raise DBIResultIngestionUnavailable(
                "artifact privado no disponible para verificación."
            ) from error
        if record.state is not DBIStorageObjectState.ACTIVE:
            raise DBIResultIngestionUnavailable(
                "artifact privado no está activo."
            )
        if record.metadata != expected:
            raise DBIResultIngestionConflict(
                "metadata privada diverge del manifest."
            )

    def ingest(
        self,
        lease: DeliveryLease,
        *,
        ingested_at: datetime,
    ) -> ResultIngestionEvidence:
        result = self._parse(lease)
        prepared = prepare_analysis_result(result)
        if prepared.result_sha256 != lease.envelope.payload.payload_sha256:
            raise DBIResultIngestionConflict(
                "huella preparada no coincide con el mensaje durable."
            )
        job, _attempt, job_id, attempt_id = self._authority(
            lease,
            result,
            result_sha256=prepared.result_sha256,
        )

        if result.status == "succeeded":
            for manifest in result.artifacts:
                self._verify_artifact(
                    manifest,
                    tenant_ref=job.tenant_ref,
                    job_id=job_id,
                )

        _row, created = self._repository.persist_result(
            prepared,
            job_id=job_id,
            attempt_id=attempt_id,
            ingested_at=_utc(ingested_at, field_name="ingested_at"),
        )
        for manifest in result.artifacts:
            self._repository.persist_artifact(
                manifest,
                job_id=job_id,
                attempt_id=attempt_id,
            )

        return ResultIngestionEvidence(
            message_id=lease.envelope.message_id,
            job_id=job_id,
            attempt_id=attempt_id,
            status=result.status,
            created=created,
            artifact_count=len(result.artifacts),
            acknowledged=False,
        )
