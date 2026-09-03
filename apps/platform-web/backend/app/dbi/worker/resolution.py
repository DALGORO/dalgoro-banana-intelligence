"""Resolución server-side de todos los recursos congelados del Worker DBI."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.delivery.contracts import (
    DeliveryEnvelope,
    DeliveryPersistenceConflict,
    DeliveryStream,
)
from app.dbi.jobs.service_contracts import contract_sha256
from app.dbi.models.agriculture import Farm, Plot
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt
from app.dbi.models.assets import AnalysisInputAsset
from app.dbi.models.model_registry import DBIModelVersion, DBIPipelineConfigVersion
from app.dbi.storage_contracts import (
    DBIPrivateObjectStore,
    DBIStorageObjectMetadata,
    DBIStoragePurpose,
)
from app.dbi.storage_policy import DBIStoragePolicy
from app.dbi.worker.contracts import (
    DBIWorkerConflict,
    DBIWorkerUnavailable,
    MODEL_ARTIFACT_TENANT_REF,
    ResolvedAnalysisPlan,
    ResolvedModelArtifact,
    ResolvedPipelineConfig,
    ResolvedPrivateObject,
)
from app.schemas.dbi_analysis_jobs import AnalysisJobCommand

_ANALYSIS_MODEL_FAMILY = "banana_detection"
_BOUNDARY_CONTENT_TYPES = frozenset(
    {
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)
_ORTHOPHOTO_CONTENT_TYPES = frozenset({"image/tiff"})
_EXCLUSIONS_CONTENT_TYPES = frozenset({"application/geopackage+sqlite3"})
_MODEL_CONTENT_TYPES = frozenset({"application/octet-stream"})


def _uuid_ref(value: str, *, field_name: str) -> UUID:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise DBIWorkerConflict(f"{field_name} no es UUID canónico.") from error
    if value != str(parsed):
        raise DBIWorkerConflict(f"{field_name} no es UUID canónico.")
    return parsed


def _canonical_config(payload_json: str) -> tuple[dict[str, object], str]:
    try:
        decoded = json.loads(payload_json)
    except json.JSONDecodeError as error:
        raise DBIWorkerConflict("configuración de pipeline persistida inválida.") from error
    if not isinstance(decoded, dict):
        raise DBIWorkerConflict("configuración de pipeline debe ser un objeto JSON.")
    canonical = json.dumps(
        decoded,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    if canonical != payload_json:
        raise DBIWorkerConflict("configuración de pipeline no es canónica.")
    return dict(decoded), hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _metadata_from_asset(row: AnalysisInputAsset) -> DBIStorageObjectMetadata:
    address = DBIStoragePolicy.build_address(
        tenant_ref=row.tenant_ref,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=row.id,
    )
    if row.object_key != address.object_key:
        raise DBIWorkerConflict("activo persistido contiene una clave no canónica.")
    return DBIStoragePolicy.build_metadata(
        address=address,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        sha256_hex=row.sha256,
    )


class DBIWorkerPlanResolver:
    """Lee recursos exactos sin commit, rollback ni selección de Champion."""

    def __init__(self, session: Session, object_store: DBIPrivateObjectStore) -> None:
        if not isinstance(session, Session):
            raise TypeError("session debe ser Session.")
        self._session = session
        self._store = object_store

    def parse_command(self, envelope: DeliveryEnvelope) -> AnalysisJobCommand:
        if not isinstance(envelope, DeliveryEnvelope):
            raise DBIWorkerConflict("envelope inválido.")
        if envelope.stream is not DeliveryStream.ANALYSIS_COMMAND:
            raise DBIWorkerConflict("el worker sólo consume analysis_command.")
        try:
            command = AnalysisJobCommand.model_validate_json(
                envelope.payload.payload_json
            )
        except ValidationError as error:
            raise DBIWorkerConflict("payload de comando inválido.") from error
        if _uuid_ref(command.job_id, field_name="command.job_id") != envelope.job_id:
            raise DBIWorkerConflict("command.job_id diverge del envelope.")
        if command.correlation_id != envelope.correlation_id:
            raise DBIWorkerConflict("correlation_id diverge del envelope.")
        return command

    def _resolve_asset(
        self,
        *,
        asset_id: UUID,
        command: AnalysisJobCommand,
        expected_kind: str,
        allowed_content_types: frozenset[str],
    ) -> ResolvedPrivateObject:
        farm_id = _uuid_ref(command.farm_id, field_name="command.farm_id")
        plot_id = _uuid_ref(command.lot_id, field_name="command.lot_id")
        row = self._session.execute(
            select(AnalysisInputAsset).where(AnalysisInputAsset.id == asset_id)
        ).scalar_one_or_none()
        if row is None:
            raise DBIWorkerUnavailable("activo congelado no disponible.")
        if (
            row.tenant_ref != command.tenant_id
            or row.farm_id != farm_id
            or row.plot_id != plot_id
            or row.asset_kind != expected_kind
            or row.status != "verified"
        ):
            raise DBIWorkerConflict("activo congelado no pertenece al ámbito esperado.")
        if row.content_type not in allowed_content_types:
            raise DBIWorkerConflict(
                f"formato no ejecutable para activo {expected_kind}."
            )
        metadata = _metadata_from_asset(row)
        persisted = self._store.stat(metadata.address)
        if persisted.metadata != metadata:
            raise DBIWorkerConflict("metadatos privados del activo divergen de PostgreSQL.")
        return ResolvedPrivateObject(
            object_id=row.id,
            kind=row.asset_kind,
            metadata=metadata,
            crs=row.crs,
        )

    def resolve(self, envelope: DeliveryEnvelope) -> ResolvedAnalysisPlan:
        command = self.parse_command(envelope)
        job_id = envelope.job_id
        attempt_id = envelope.attempt_id
        farm_id = _uuid_ref(command.farm_id, field_name="command.farm_id")
        plot_id = _uuid_ref(command.lot_id, field_name="command.lot_id")

        job = self._session.execute(
            select(AnalysisJob).where(AnalysisJob.id == job_id)
        ).scalar_one_or_none()
        attempt = self._session.execute(
            select(AnalysisJobAttempt).where(
                AnalysisJobAttempt.id == attempt_id,
                AnalysisJobAttempt.job_id == job_id,
            )
        ).scalar_one_or_none()
        if job is None or attempt is None:
            raise DBIWorkerUnavailable("job/attempt congelado no disponible.")
        exact_job = (
            job.tenant_ref == command.tenant_id
            and job.farm_id == farm_id
            and job.plot_id == plot_id
            and job.correlation_id == command.correlation_id
            and job.model_version_ref == command.model_version_id
            and job.pipeline_config_version == command.pipeline_config_version
            and job.orthophoto_asset_ref == command.inputs.orthophoto_asset_id
            and job.boundary_asset_ref == command.inputs.boundary_asset_id
            and job.exclusions_asset_ref == command.inputs.exclusions_asset_id
            and contract_sha256(command) == job.command_sha256
        )
        if not exact_job:
            raise DBIWorkerConflict("Job persistido diverge del comando durable.")

        farm = self._session.execute(
            select(Farm).where(Farm.id == farm_id)
        ).scalar_one_or_none()
        plot = self._session.execute(
            select(Plot).where(Plot.id == plot_id, Plot.farm_id == farm_id)
        ).scalar_one_or_none()
        if farm is None or plot is None:
            raise DBIWorkerUnavailable("finca/lote del trabajo no disponible.")

        orthophoto = self._resolve_asset(
            asset_id=_uuid_ref(
                command.inputs.orthophoto_asset_id,
                field_name="orthophoto_asset_id",
            ),
            command=command,
            expected_kind="orthophoto",
            allowed_content_types=_ORTHOPHOTO_CONTENT_TYPES,
        )
        boundary = self._resolve_asset(
            asset_id=_uuid_ref(
                command.inputs.boundary_asset_id,
                field_name="boundary_asset_id",
            ),
            command=command,
            expected_kind="boundary",
            allowed_content_types=_BOUNDARY_CONTENT_TYPES,
        )
        exclusions = None
        if command.inputs.exclusions_asset_id is not None:
            exclusions = self._resolve_asset(
                asset_id=_uuid_ref(
                    command.inputs.exclusions_asset_id,
                    field_name="exclusions_asset_id",
                ),
                command=command,
                expected_kind="exclusions",
                allowed_content_types=_EXCLUSIONS_CONTENT_TYPES,
            )

        model = self._session.execute(
            select(DBIModelVersion).where(
                DBIModelVersion.model_family == _ANALYSIS_MODEL_FAMILY,
                DBIModelVersion.model_version == command.model_version_id,
                DBIModelVersion.status == "approved",
            )
        ).scalar_one_or_none()
        if model is None or model.artifact_ref is None:
            raise DBIWorkerUnavailable("modelo congelado no es ejecutable.")
        artifact_id = _uuid_ref(model.artifact_ref, field_name="model.artifact_ref")
        model_address = DBIStoragePolicy.build_address(
            tenant_ref=MODEL_ARTIFACT_TENANT_REF,
            purpose=DBIStoragePurpose.MODEL_ARTIFACT,
            object_id=artifact_id,
        )
        model_record = self._store.stat(model_address)
        if model_record.metadata.content_type not in _MODEL_CONTENT_TYPES:
            raise DBIWorkerConflict("artefacto de modelo no es un peso ejecutable.")
        resolved_model = ResolvedModelArtifact(
            model_family=model.model_family,
            model_version=model.model_version,
            artifact_id=artifact_id,
            metadata=model_record.metadata,
            input_contract_version=model.input_contract_version,
            output_contract_version=model.output_contract_version,
        )

        pipeline = self._session.execute(
            select(DBIPipelineConfigVersion).where(
                DBIPipelineConfigVersion.model_family == model.model_family,
                DBIPipelineConfigVersion.config_version
                == command.pipeline_config_version,
                DBIPipelineConfigVersion.status == "approved",
            )
        ).scalar_one_or_none()
        if pipeline is None:
            raise DBIWorkerUnavailable("configuración congelada no está aprobada.")
        payload, digest = _canonical_config(pipeline.config_json)
        if digest != pipeline.config_sha256:
            raise DBIWorkerConflict("config_sha256 persistido no coincide.")
        resolved_pipeline = ResolvedPipelineConfig(
            model_family=pipeline.model_family,
            config_version=pipeline.config_version,
            config_sha256=pipeline.config_sha256,
            payload=payload,
        )

        return ResolvedAnalysisPlan(
            job_id=job_id,
            attempt_id=attempt_id,
            correlation_id=command.correlation_id,
            tenant_ref=command.tenant_id,
            farm_id=farm_id,
            plot_id=plot_id,
            farm_name=farm.name,
            plot_name=plot.name,
            orthophoto=orthophoto,
            boundary=boundary,
            exclusions=exclusions,
            model=resolved_model,
            pipeline=resolved_pipeline,
        )
