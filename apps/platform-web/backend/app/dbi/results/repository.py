"""Persistencia idempotente de resultados y manifests DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid5

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.models.analysis_results import DBIAnalysisResult
from app.dbi.models.assets import AnalysisArtifact
from app.dbi.results.contracts import (
    DBIResultIngestionConflict,
    PreparedAnalysisResult,
    canonical_uuid,
)
from app.schemas.dbi_analysis_jobs import ArtifactManifest

_RESULT_NAMESPACE = UUID("7bd48850-d479-46d3-88cc-74db5884ab1d")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DBIResultIngestionConflict("timestamp debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _same_time(left: datetime, right: datetime) -> bool:
    return _utc(left) == _utc(right)


class DBIResultRepository:
    """Repository sin commit, rollback ni acceso a almacenamiento externo."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBIResultIngestionConflict("session debe ser Session.")
        self._session = session

    def persist_result(
        self,
        prepared: PreparedAnalysisResult,
        *,
        job_id: UUID,
        attempt_id: UUID,
        ingested_at: datetime,
    ) -> tuple[DBIAnalysisResult, bool]:
        result = prepared.result
        stable_id = uuid5(
            _RESULT_NAMESPACE,
            f"dbi:analysis-result:v1:{attempt_id}",
        )
        ingested = _utc(ingested_at)
        inserted = self._session.execute(
            postgresql_insert(DBIAnalysisResult)
            .values(
                id=stable_id,
                job_id=job_id,
                attempt_id=attempt_id,
                schema_version=result.schema_version,
                status=result.status,
                result_sha256=prepared.result_sha256,
                pipeline_build_ref=result.pipeline_build,
                started_at=_utc(result.started_at),
                finished_at=_utc(result.finished_at),
                metrics_json=prepared.metrics.json_text,
                metrics_sha256=prepared.metrics.sha256,
                findings_json=prepared.findings.json_text,
                findings_sha256=prepared.findings.sha256,
                warnings_json=prepared.warnings.json_text,
                warnings_sha256=prepared.warnings.sha256,
                errors_json=prepared.errors.json_text,
                errors_sha256=prepared.errors.sha256,
                ingested_at=ingested,
            )
            .on_conflict_do_nothing(
                constraint="uq_dbi_analysis_results_attempt"
            )
            .returning(DBIAnalysisResult.id)
        ).scalar_one_or_none()

        row = self._session.execute(
            select(DBIAnalysisResult).where(
                DBIAnalysisResult.attempt_id == attempt_id
            )
        ).scalar_one_or_none()
        if row is None:
            raise DBIResultIngestionConflict("resultado persistido no recuperable.")

        exact = (
            row.id == stable_id
            and row.job_id == job_id
            and row.attempt_id == attempt_id
            and row.schema_version == result.schema_version
            and row.status == result.status
            and row.result_sha256 == prepared.result_sha256
            and row.pipeline_build_ref == result.pipeline_build
            and _same_time(row.started_at, result.started_at)
            and _same_time(row.finished_at, result.finished_at)
            and row.metrics_json == prepared.metrics.json_text
            and row.metrics_sha256 == prepared.metrics.sha256
            and row.findings_json == prepared.findings.json_text
            and row.findings_sha256 == prepared.findings.sha256
            and row.warnings_json == prepared.warnings.json_text
            and row.warnings_sha256 == prepared.warnings.sha256
            and row.errors_json == prepared.errors.json_text
            and row.errors_sha256 == prepared.errors.sha256
        )
        if not exact:
            raise DBIResultIngestionConflict(
                "attempt_id ya representa otro resultado terminal."
            )
        if inserted is not None and inserted != row.id:
            raise DBIResultIngestionConflict("identidad de resultado divergente.")
        return row, inserted is not None

    def persist_artifact(
        self,
        manifest: ArtifactManifest,
        *,
        job_id: UUID,
        attempt_id: UUID,
    ) -> tuple[AnalysisArtifact, bool]:
        artifact_id = canonical_uuid(
            manifest.artifact_id,
            field_name="artifact.artifact_id",
        )
        inserted = self._session.execute(
            postgresql_insert(AnalysisArtifact)
            .values(
                id=artifact_id,
                job_id=job_id,
                attempt_id=attempt_id,
                manifest_schema_version=manifest.schema_version,
                role=manifest.role.value,
                object_key=manifest.object_key,
                content_type=manifest.content_type,
                size_bytes=manifest.size_bytes,
                sha256=manifest.sha256,
                produced_by_stage=manifest.produced_by_stage.value,
                crs=manifest.crs,
                created_at=_utc(manifest.created_at),
            )
            .on_conflict_do_nothing()
            .returning(AnalysisArtifact.id)
        ).scalar_one_or_none()

        rows = self._session.execute(
            select(AnalysisArtifact).where(
                or_(
                    AnalysisArtifact.id == artifact_id,
                    AnalysisArtifact.object_key == manifest.object_key,
                )
            )
        ).scalars().all()
        if len(rows) != 1:
            raise DBIResultIngestionConflict(
                "artifact_id/object_key colisionan con otra identidad."
            )
        row = rows[0]
        exact = (
            row.id == artifact_id
            and row.job_id == job_id
            and row.attempt_id == attempt_id
            and row.manifest_schema_version == manifest.schema_version
            and row.role == manifest.role.value
            and row.object_key == manifest.object_key
            and row.content_type == manifest.content_type
            and row.size_bytes == manifest.size_bytes
            and row.sha256 == manifest.sha256
            and row.produced_by_stage == manifest.produced_by_stage.value
            and row.crs == manifest.crs
            and _same_time(row.created_at, manifest.created_at)
        )
        if not exact:
            raise DBIResultIngestionConflict(
                "artifact persistido diverge del manifest recibido."
            )
        if inserted is not None and inserted != row.id:
            raise DBIResultIngestionConflict("identidad de artifact divergente.")
        return row, inserted is not None
