"""Gobernanza persistente de modelos, pipeline y perfiles Champion/Challenger DBI."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.jobs.service_contracts import (
    AnalysisProfileResolutionContext,
    AnalysisProfileUnavailable,
    ApprovedAnalysisProfile,
)
from app.dbi.models.model_registry import (
    DBIAnalysisProfile,
    DBIModelGovernanceEvent,
    DBIModelVersion,
    DBIPipelineConfigVersion,
)
from app.schemas.dbi_analysis_jobs import OpaqueReference, Sha256Digest

DEFAULT_ANALYSIS_MODEL_FAMILY = "banana_detection"
MAX_REGISTRY_JSON_BYTES = 64 * 1024
_FORBIDDEN_PAYLOAD_KEY_FRAGMENTS = (
    "password",
    "secret",
    "credential",
    "access_token",
    "refresh_token",
    "api_key",
    "signed_url",
    "presigned",
    "object_key",
    "bucket",
    "local_path",
    "file_path",
    "model_path",
)


class ModelRegistryConflict(RuntimeError):
    """La operación contradice el estado gobernado del registro."""


class ModelRegistryUnavailable(LookupError):
    """El modelo, configuración o perfil solicitado no está disponible."""


class ModelLifecycleStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    APPROVED = "approved"
    RETIRED = "retired"


class AnalysisProfileRole(StrEnum):
    CHAMPION = "champion"
    CHALLENGER = "challenger"


class AnalysisProfileStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class GovernanceAction(StrEnum):
    MODEL_REGISTERED = "model_registered"
    MODEL_VALIDATED = "model_validated"
    MODEL_APPROVED = "model_approved"
    MODEL_RETIRED = "model_retired"
    PIPELINE_REGISTERED = "pipeline_registered"
    PIPELINE_VALIDATED = "pipeline_validated"
    PIPELINE_APPROVED = "pipeline_approved"
    PIPELINE_RETIRED = "pipeline_retired"
    PROFILE_REGISTERED = "profile_registered"
    CHAMPION_PROMOTED = "champion_promoted"
    PROFILE_RETIRED = "profile_retired"


class _StrictRegistryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ModelVersionRegistration(_StrictRegistryModel):
    """Lineage inmutable requerido para registrar una versión científica."""

    model_family: OpaqueReference
    model_version: OpaqueReference
    training_dataset_version: OpaqueReference
    validation_dataset_version: OpaqueReference
    input_contract_version: OpaqueReference
    output_contract_version: OpaqueReference
    artifact_ref: OpaqueReference | None = None
    metrics: dict[str, Any] | None = Field(default=None)


class PipelineConfigRegistration(_StrictRegistryModel):
    """Configuración versionada del pipeline, sin rutas, URLs ni credenciales."""

    model_family: OpaqueReference
    config_version: OpaqueReference
    config: dict[str, Any]


class ModelVersionSnapshot(_StrictRegistryModel):
    model_id: UUID
    model_family: OpaqueReference
    model_version: OpaqueReference
    status: ModelLifecycleStatus
    training_dataset_version: OpaqueReference
    validation_dataset_version: OpaqueReference
    input_contract_version: OpaqueReference
    output_contract_version: OpaqueReference
    artifact_ref: OpaqueReference | None = None
    metrics_sha256: Sha256Digest | None = None
    created_by_ref: OpaqueReference
    approved_by_ref: OpaqueReference | None = None
    created_at: AwareDatetime
    approved_at: AwareDatetime | None = None
    retired_at: AwareDatetime | None = None


class PipelineConfigSnapshot(_StrictRegistryModel):
    pipeline_config_id: UUID
    model_family: OpaqueReference
    config_version: OpaqueReference
    status: ModelLifecycleStatus
    config_sha256: Sha256Digest
    created_by_ref: OpaqueReference
    approved_by_ref: OpaqueReference | None = None
    created_at: AwareDatetime
    approved_at: AwareDatetime | None = None
    retired_at: AwareDatetime | None = None


class AnalysisProfileRegistration(_StrictRegistryModel):
    """Nuevo Challenger; convertirse en Champion exige promoción explícita."""

    tenant_ref: OpaqueReference
    model_family: OpaqueReference
    model_version_id: UUID
    pipeline_config_id: UUID
    policy_ref: OpaqueReference


class AnalysisProfileSnapshot(_StrictRegistryModel):
    profile_id: UUID
    tenant_ref: OpaqueReference
    model_family: OpaqueReference
    model_version_id: UUID
    pipeline_config_id: UUID
    policy_ref: OpaqueReference
    role: AnalysisProfileRole
    status: AnalysisProfileStatus
    created_by_ref: OpaqueReference
    retired_by_ref: OpaqueReference | None = None
    created_at: AwareDatetime
    retired_at: AwareDatetime | None = None


class RegistryMutationEvidence(_StrictRegistryModel):
    changed: bool


class ModelRegistrationEvidence(_StrictRegistryModel):
    snapshot: ModelVersionSnapshot
    created: bool


class PipelineConfigRegistrationEvidence(_StrictRegistryModel):
    snapshot: PipelineConfigSnapshot
    created: bool


class ProfileRegistrationEvidence(_StrictRegistryModel):
    snapshot: AnalysisProfileSnapshot
    created: bool


def _utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelRegistryConflict(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _assert_safe_json(value: Any, *, field_name: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise ModelRegistryConflict(f"{field_name} contiene una clave inválida.")
            key = raw_key.strip().lower().replace("-", "_")
            if any(fragment in key for fragment in _FORBIDDEN_PAYLOAD_KEY_FRAGMENTS):
                raise ModelRegistryConflict(
                    f"{field_name} contiene una referencia sensible o de infraestructura."
                )
            _assert_safe_json(child, field_name=field_name)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _assert_safe_json(child, field_name=field_name)
        return
    if isinstance(value, str):
        normalized = value.strip().lower()
        if (
            "://" in normalized
            or normalized.startswith(("/", "\\", "s3:", "gs:", "file:"))
        ):
            raise ModelRegistryConflict(
                f"{field_name} no admite URLs, buckets ni rutas locales."
            )
        if len(value.encode("utf-8")) > 4096:
            raise ModelRegistryConflict(f"{field_name} contiene texto excesivo.")
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise ModelRegistryConflict(f"{field_name} contiene un tipo JSON no permitido.")


def _canonical_json(
    value: Mapping[str, Any], *, field_name: str
) -> tuple[str, str]:
    _assert_safe_json(value, field_name=field_name)
    try:
        payload = json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ModelRegistryConflict(f"{field_name} no es JSON canónico válido.") from error
    raw = payload.encode("utf-8")
    if not (2 <= len(raw) <= MAX_REGISTRY_JSON_BYTES):
        raise ModelRegistryConflict(f"{field_name} excede el límite permitido.")
    return payload, hashlib.sha256(raw).hexdigest()


def _canonical_metrics(
    metrics: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    if metrics is None:
        return None, None
    return _canonical_json(metrics, field_name="metrics")


def _model_snapshot(row: DBIModelVersion) -> ModelVersionSnapshot:
    return ModelVersionSnapshot(
        model_id=row.id,
        model_family=row.model_family,
        model_version=row.model_version,
        status=ModelLifecycleStatus(row.status),
        training_dataset_version=row.training_dataset_version,
        validation_dataset_version=row.validation_dataset_version,
        input_contract_version=row.input_contract_version,
        output_contract_version=row.output_contract_version,
        artifact_ref=row.artifact_ref,
        metrics_sha256=row.metrics_sha256,
        created_by_ref=row.created_by_ref,
        approved_by_ref=row.approved_by_ref,
        created_at=row.created_at,
        approved_at=row.approved_at,
        retired_at=row.retired_at,
    )


def _pipeline_snapshot(row: DBIPipelineConfigVersion) -> PipelineConfigSnapshot:
    return PipelineConfigSnapshot(
        pipeline_config_id=row.id,
        model_family=row.model_family,
        config_version=row.config_version,
        status=ModelLifecycleStatus(row.status),
        config_sha256=row.config_sha256,
        created_by_ref=row.created_by_ref,
        approved_by_ref=row.approved_by_ref,
        created_at=row.created_at,
        approved_at=row.approved_at,
        retired_at=row.retired_at,
    )


def _profile_snapshot(row: DBIAnalysisProfile) -> AnalysisProfileSnapshot:
    return AnalysisProfileSnapshot(
        profile_id=row.id,
        tenant_ref=row.tenant_ref,
        model_family=row.model_family,
        model_version_id=row.model_version_id,
        pipeline_config_id=row.pipeline_config_id,
        policy_ref=row.policy_ref,
        role=AnalysisProfileRole(row.role),
        status=AnalysisProfileStatus(row.status),
        created_by_ref=row.created_by_ref,
        retired_by_ref=row.retired_by_ref,
        created_at=row.created_at,
        retired_at=row.retired_at,
    )


class DBIModelRegistryRepository:
    """Repositorio DBI sin commit/rollback ni efectos externos."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session debe ser Session.")
        self._session = session

    def flush(self) -> None:
        self._session.flush()

    def get_model_by_identity(
        self, *, model_family: str, model_version: str
    ) -> DBIModelVersion | None:
        return self._session.execute(
            select(DBIModelVersion).where(
                DBIModelVersion.model_family == model_family,
                DBIModelVersion.model_version == model_version,
            )
        ).scalar_one_or_none()

    def get_model_for_update(self, *, model_id: UUID) -> DBIModelVersion | None:
        return self._session.execute(
            select(DBIModelVersion)
            .where(DBIModelVersion.id == model_id)
            .with_for_update()
        ).scalar_one_or_none()

    def persist_model(
        self,
        *,
        registration: ModelVersionRegistration,
        actor_ref: str,
        created_at: datetime,
    ) -> DBIModelVersion:
        metrics_json, metrics_sha256 = _canonical_metrics(registration.metrics)
        row = DBIModelVersion(
            id=uuid4(),
            model_family=registration.model_family,
            model_version=registration.model_version,
            status=ModelLifecycleStatus.DRAFT.value,
            training_dataset_version=registration.training_dataset_version,
            validation_dataset_version=registration.validation_dataset_version,
            input_contract_version=registration.input_contract_version,
            output_contract_version=registration.output_contract_version,
            artifact_ref=registration.artifact_ref,
            metrics_json=metrics_json,
            metrics_sha256=metrics_sha256,
            created_by_ref=actor_ref,
            created_at=_utc(created_at, field_name="created_at"),
        )
        self._session.add(row)
        self.flush()
        return row

    def get_pipeline_by_identity(
        self, *, model_family: str, config_version: str
    ) -> DBIPipelineConfigVersion | None:
        return self._session.execute(
            select(DBIPipelineConfigVersion).where(
                DBIPipelineConfigVersion.model_family == model_family,
                DBIPipelineConfigVersion.config_version == config_version,
            )
        ).scalar_one_or_none()

    def get_pipeline_for_update(
        self, *, pipeline_config_id: UUID
    ) -> DBIPipelineConfigVersion | None:
        return self._session.execute(
            select(DBIPipelineConfigVersion)
            .where(DBIPipelineConfigVersion.id == pipeline_config_id)
            .with_for_update()
        ).scalar_one_or_none()

    def persist_pipeline_config(
        self,
        *,
        registration: PipelineConfigRegistration,
        actor_ref: str,
        created_at: datetime,
    ) -> DBIPipelineConfigVersion:
        config_json, config_sha256 = _canonical_json(
            registration.config,
            field_name="pipeline_config",
        )
        row = DBIPipelineConfigVersion(
            id=uuid4(),
            model_family=registration.model_family,
            config_version=registration.config_version,
            status=ModelLifecycleStatus.DRAFT.value,
            config_json=config_json,
            config_sha256=config_sha256,
            created_by_ref=actor_ref,
            created_at=_utc(created_at, field_name="created_at"),
        )
        self._session.add(row)
        self.flush()
        return row

    def get_profile_by_policy(
        self, *, tenant_ref: str, policy_ref: str
    ) -> DBIAnalysisProfile | None:
        return self._session.execute(
            select(DBIAnalysisProfile).where(
                DBIAnalysisProfile.tenant_ref == tenant_ref,
                DBIAnalysisProfile.policy_ref == policy_ref,
            )
        ).scalar_one_or_none()

    def get_profile_for_update(self, *, profile_id: UUID) -> DBIAnalysisProfile | None:
        return self._session.execute(
            select(DBIAnalysisProfile)
            .where(DBIAnalysisProfile.id == profile_id)
            .with_for_update()
        ).scalar_one_or_none()

    def persist_challenger(
        self,
        *,
        registration: AnalysisProfileRegistration,
        actor_ref: str,
        created_at: datetime,
    ) -> DBIAnalysisProfile:
        row = DBIAnalysisProfile(
            id=uuid4(),
            tenant_ref=registration.tenant_ref,
            model_family=registration.model_family,
            model_version_id=registration.model_version_id,
            pipeline_config_id=registration.pipeline_config_id,
            policy_ref=registration.policy_ref,
            role=AnalysisProfileRole.CHALLENGER.value,
            status=AnalysisProfileStatus.ACTIVE.value,
            created_by_ref=actor_ref,
            created_at=_utc(created_at, field_name="created_at"),
        )
        self._session.add(row)
        self.flush()
        return row

    def lock_active_profiles(
        self, *, tenant_ref: str, model_family: str
    ) -> list[DBIAnalysisProfile]:
        return list(
            self._session.execute(
                select(DBIAnalysisProfile)
                .where(
                    DBIAnalysisProfile.tenant_ref == tenant_ref,
                    DBIAnalysisProfile.model_family == model_family,
                    DBIAnalysisProfile.status == AnalysisProfileStatus.ACTIVE.value,
                )
                .order_by(DBIAnalysisProfile.id)
                .with_for_update()
            ).scalars()
        )

    def has_active_profiles_for_model(self, *, model_id: UUID) -> bool:
        return (
            self._session.execute(
                select(DBIAnalysisProfile.id)
                .where(
                    DBIAnalysisProfile.model_version_id == model_id,
                    DBIAnalysisProfile.status == AnalysisProfileStatus.ACTIVE.value,
                )
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def has_active_profiles_for_pipeline(self, *, pipeline_config_id: UUID) -> bool:
        return (
            self._session.execute(
                select(DBIAnalysisProfile.id)
                .where(
                    DBIAnalysisProfile.pipeline_config_id == pipeline_config_id,
                    DBIAnalysisProfile.status == AnalysisProfileStatus.ACTIVE.value,
                )
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def record_event(
        self,
        *,
        action: GovernanceAction,
        model_family: str,
        actor_ref: str,
        occurred_at: datetime,
        tenant_ref: str | None = None,
        model_version_id: UUID | None = None,
        pipeline_config_id: UUID | None = None,
        profile_id: UUID | None = None,
        previous_champion_profile_id: UUID | None = None,
    ) -> None:
        self._session.add(
            DBIModelGovernanceEvent(
                id=uuid4(),
                action=action.value,
                model_family=model_family,
                tenant_ref=tenant_ref,
                model_version_id=model_version_id,
                pipeline_config_id=pipeline_config_id,
                profile_id=profile_id,
                previous_champion_profile_id=previous_champion_profile_id,
                actor_ref=actor_ref,
                occurred_at=_utc(occurred_at, field_name="occurred_at"),
            )
        )

    def resolve_champion(
        self, *, tenant_ref: str, model_family: str
    ) -> ApprovedAnalysisProfile:
        rows = self._session.execute(
            select(DBIAnalysisProfile, DBIModelVersion, DBIPipelineConfigVersion)
            .join(
                DBIModelVersion,
                (DBIAnalysisProfile.model_version_id == DBIModelVersion.id)
                & (DBIAnalysisProfile.model_family == DBIModelVersion.model_family),
            )
            .join(
                DBIPipelineConfigVersion,
                (DBIAnalysisProfile.pipeline_config_id == DBIPipelineConfigVersion.id)
                & (
                    DBIAnalysisProfile.model_family
                    == DBIPipelineConfigVersion.model_family
                ),
            )
            .where(
                DBIAnalysisProfile.tenant_ref == tenant_ref,
                DBIAnalysisProfile.model_family == model_family,
                DBIAnalysisProfile.role == AnalysisProfileRole.CHAMPION.value,
                DBIAnalysisProfile.status == AnalysisProfileStatus.ACTIVE.value,
                DBIModelVersion.status == ModelLifecycleStatus.APPROVED.value,
                DBIPipelineConfigVersion.status == ModelLifecycleStatus.APPROVED.value,
            )
            .with_for_update()
        ).all()
        if len(rows) != 1:
            raise AnalysisProfileUnavailable(
                "No existe exactamente un Champion DBI aprobado para el ámbito."
            )
        profile, model, pipeline = rows[0]
        return ApprovedAnalysisProfile(
            model_version_id=model.model_version,
            pipeline_config_version=pipeline.config_version,
            policy_ref=profile.policy_ref,
        )


class DBIModelRegistryService:
    """Mutaciones explícitas; el llamador controla commit y rollback."""

    def __init__(self, repository: DBIModelRegistryRepository) -> None:
        if not isinstance(repository, DBIModelRegistryRepository):
            raise TypeError("repository debe ser DBIModelRegistryRepository.")
        self._repository = repository

    def register_model(
        self,
        registration: ModelVersionRegistration,
        *,
        actor_ref: OpaqueReference,
        created_at: datetime,
    ) -> ModelRegistrationEvidence:
        existing = self._repository.get_model_by_identity(
            model_family=registration.model_family,
            model_version=registration.model_version,
        )
        if existing is not None:
            metrics_json, metrics_sha256 = _canonical_metrics(registration.metrics)
            expected = (
                registration.training_dataset_version,
                registration.validation_dataset_version,
                registration.input_contract_version,
                registration.output_contract_version,
                registration.artifact_ref,
                metrics_json,
                metrics_sha256,
            )
            actual = (
                existing.training_dataset_version,
                existing.validation_dataset_version,
                existing.input_contract_version,
                existing.output_contract_version,
                existing.artifact_ref,
                existing.metrics_json,
                existing.metrics_sha256,
            )
            if actual != expected:
                raise ModelRegistryConflict(
                    "La identidad del modelo ya existe con lineage diferente."
                )
            return ModelRegistrationEvidence(
                snapshot=_model_snapshot(existing), created=False
            )
        row = self._repository.persist_model(
            registration=registration,
            actor_ref=actor_ref,
            created_at=created_at,
        )
        self._repository.record_event(
            action=GovernanceAction.MODEL_REGISTERED,
            model_family=row.model_family,
            actor_ref=actor_ref,
            model_version_id=row.id,
            occurred_at=created_at,
        )
        self._repository.flush()
        return ModelRegistrationEvidence(snapshot=_model_snapshot(row), created=True)

    def validate_model(
        self,
        *,
        model_id: UUID,
        actor_ref: OpaqueReference,
        changed_at: datetime,
    ) -> RegistryMutationEvidence:
        row = self._repository.get_model_for_update(model_id=model_id)
        if row is None:
            raise ModelRegistryUnavailable("modelo no disponible.")
        status = ModelLifecycleStatus(row.status)
        if status is ModelLifecycleStatus.VALIDATED:
            return RegistryMutationEvidence(changed=False)
        if status is not ModelLifecycleStatus.DRAFT:
            raise ModelRegistryConflict("sólo un modelo draft puede validarse.")
        row.status = ModelLifecycleStatus.VALIDATED.value
        self._repository.record_event(
            action=GovernanceAction.MODEL_VALIDATED,
            model_family=row.model_family,
            actor_ref=actor_ref,
            model_version_id=row.id,
            occurred_at=changed_at,
        )
        self._repository.flush()
        return RegistryMutationEvidence(changed=True)

    def approve_model(
        self,
        *,
        model_id: UUID,
        actor_ref: OpaqueReference,
        approved_at: datetime,
    ) -> RegistryMutationEvidence:
        row = self._repository.get_model_for_update(model_id=model_id)
        if row is None:
            raise ModelRegistryUnavailable("modelo no disponible.")
        status = ModelLifecycleStatus(row.status)
        if status is ModelLifecycleStatus.APPROVED:
            return RegistryMutationEvidence(changed=False)
        if status is not ModelLifecycleStatus.VALIDATED:
            raise ModelRegistryConflict("sólo un modelo validated puede aprobarse.")
        row.status = ModelLifecycleStatus.APPROVED.value
        row.approved_by_ref = actor_ref
        row.approved_at = _utc(approved_at, field_name="approved_at")
        self._repository.record_event(
            action=GovernanceAction.MODEL_APPROVED,
            model_family=row.model_family,
            actor_ref=actor_ref,
            model_version_id=row.id,
            occurred_at=approved_at,
        )
        self._repository.flush()
        return RegistryMutationEvidence(changed=True)

    def register_pipeline_config(
        self,
        registration: PipelineConfigRegistration,
        *,
        actor_ref: OpaqueReference,
        created_at: datetime,
    ) -> PipelineConfigRegistrationEvidence:
        existing = self._repository.get_pipeline_by_identity(
            model_family=registration.model_family,
            config_version=registration.config_version,
        )
        config_json, config_sha256 = _canonical_json(
            registration.config,
            field_name="pipeline_config",
        )
        if existing is not None:
            if (existing.config_json, existing.config_sha256) != (
                config_json,
                config_sha256,
            ):
                raise ModelRegistryConflict(
                    "La versión de configuración ya existe con contenido diferente."
                )
            return PipelineConfigRegistrationEvidence(
                snapshot=_pipeline_snapshot(existing), created=False
            )
        row = self._repository.persist_pipeline_config(
            registration=registration,
            actor_ref=actor_ref,
            created_at=created_at,
        )
        self._repository.record_event(
            action=GovernanceAction.PIPELINE_REGISTERED,
            model_family=row.model_family,
            actor_ref=actor_ref,
            pipeline_config_id=row.id,
            occurred_at=created_at,
        )
        self._repository.flush()
        return PipelineConfigRegistrationEvidence(
            snapshot=_pipeline_snapshot(row), created=True
        )

    def validate_pipeline_config(
        self,
        *,
        pipeline_config_id: UUID,
        actor_ref: OpaqueReference,
        changed_at: datetime,
    ) -> RegistryMutationEvidence:
        row = self._repository.get_pipeline_for_update(
            pipeline_config_id=pipeline_config_id
        )
        if row is None:
            raise ModelRegistryUnavailable("configuración no disponible.")
        status = ModelLifecycleStatus(row.status)
        if status is ModelLifecycleStatus.VALIDATED:
            return RegistryMutationEvidence(changed=False)
        if status is not ModelLifecycleStatus.DRAFT:
            raise ModelRegistryConflict("sólo una configuración draft puede validarse.")
        row.status = ModelLifecycleStatus.VALIDATED.value
        self._repository.record_event(
            action=GovernanceAction.PIPELINE_VALIDATED,
            model_family=row.model_family,
            actor_ref=actor_ref,
            pipeline_config_id=row.id,
            occurred_at=changed_at,
        )
        self._repository.flush()
        return RegistryMutationEvidence(changed=True)

    def approve_pipeline_config(
        self,
        *,
        pipeline_config_id: UUID,
        actor_ref: OpaqueReference,
        approved_at: datetime,
    ) -> RegistryMutationEvidence:
        row = self._repository.get_pipeline_for_update(
            pipeline_config_id=pipeline_config_id
        )
        if row is None:
            raise ModelRegistryUnavailable("configuración no disponible.")
        status = ModelLifecycleStatus(row.status)
        if status is ModelLifecycleStatus.APPROVED:
            return RegistryMutationEvidence(changed=False)
        if status is not ModelLifecycleStatus.VALIDATED:
            raise ModelRegistryConflict(
                "sólo una configuración validated puede aprobarse."
            )
        row.status = ModelLifecycleStatus.APPROVED.value
        row.approved_by_ref = actor_ref
        row.approved_at = _utc(approved_at, field_name="approved_at")
        self._repository.record_event(
            action=GovernanceAction.PIPELINE_APPROVED,
            model_family=row.model_family,
            actor_ref=actor_ref,
            pipeline_config_id=row.id,
            occurred_at=approved_at,
        )
        self._repository.flush()
        return RegistryMutationEvidence(changed=True)

    def register_challenger(
        self,
        registration: AnalysisProfileRegistration,
        *,
        actor_ref: OpaqueReference,
        created_at: datetime,
    ) -> ProfileRegistrationEvidence:
        model = self._repository.get_model_for_update(
            model_id=registration.model_version_id
        )
        pipeline = self._repository.get_pipeline_for_update(
            pipeline_config_id=registration.pipeline_config_id
        )
        if model is None or model.model_family != registration.model_family:
            raise ModelRegistryUnavailable("modelo no disponible para la familia.")
        if pipeline is None or pipeline.model_family != registration.model_family:
            raise ModelRegistryUnavailable(
                "configuración no disponible para la familia."
            )
        if ModelLifecycleStatus(model.status) is not ModelLifecycleStatus.APPROVED:
            raise ModelRegistryConflict("el modelo debe estar aprobado.")
        if ModelLifecycleStatus(pipeline.status) is not ModelLifecycleStatus.APPROVED:
            raise ModelRegistryConflict("la configuración debe estar aprobada.")
        existing = self._repository.get_profile_by_policy(
            tenant_ref=registration.tenant_ref,
            policy_ref=registration.policy_ref,
        )
        if existing is not None:
            expected = (
                registration.model_family,
                registration.model_version_id,
                registration.pipeline_config_id,
            )
            actual = (
                existing.model_family,
                existing.model_version_id,
                existing.pipeline_config_id,
            )
            if actual != expected:
                raise ModelRegistryConflict(
                    "policy_ref ya existe con una intención diferente."
                )
            return ProfileRegistrationEvidence(
                snapshot=_profile_snapshot(existing), created=False
            )
        row = self._repository.persist_challenger(
            registration=registration,
            actor_ref=actor_ref,
            created_at=created_at,
        )
        self._repository.record_event(
            action=GovernanceAction.PROFILE_REGISTERED,
            model_family=row.model_family,
            tenant_ref=row.tenant_ref,
            actor_ref=actor_ref,
            model_version_id=row.model_version_id,
            pipeline_config_id=row.pipeline_config_id,
            profile_id=row.id,
            occurred_at=created_at,
        )
        self._repository.flush()
        return ProfileRegistrationEvidence(snapshot=_profile_snapshot(row), created=True)

    def promote_challenger(
        self,
        *,
        tenant_ref: OpaqueReference,
        model_family: OpaqueReference,
        profile_id: UUID,
        actor_ref: OpaqueReference,
        promoted_at: datetime,
    ) -> RegistryMutationEvidence:
        profiles = self._repository.lock_active_profiles(
            tenant_ref=tenant_ref,
            model_family=model_family,
        )
        target = next((item for item in profiles if item.id == profile_id), None)
        if target is None:
            raise ModelRegistryUnavailable("perfil no disponible.")
        champions = [
            item for item in profiles if item.role == AnalysisProfileRole.CHAMPION.value
        ]
        if len(champions) > 1:
            raise ModelRegistryConflict("existen múltiples Champion activos.")
        model = self._repository.get_model_for_update(model_id=target.model_version_id)
        pipeline = self._repository.get_pipeline_for_update(
            pipeline_config_id=target.pipeline_config_id
        )
        if (
            model is None
            or ModelLifecycleStatus(model.status) is not ModelLifecycleStatus.APPROVED
            or pipeline is None
            or ModelLifecycleStatus(pipeline.status) is not ModelLifecycleStatus.APPROVED
        ):
            raise ModelRegistryConflict(
                "el perfil no apunta a modelo y configuración aprobados."
            )
        if target.role == AnalysisProfileRole.CHAMPION.value:
            return RegistryMutationEvidence(changed=False)
        previous = champions[0] if champions else None
        if previous is not None:
            previous.role = AnalysisProfileRole.CHALLENGER.value
            self._repository.flush()
        target.role = AnalysisProfileRole.CHAMPION.value
        self._repository.record_event(
            action=GovernanceAction.CHAMPION_PROMOTED,
            model_family=model_family,
            tenant_ref=tenant_ref,
            actor_ref=actor_ref,
            model_version_id=target.model_version_id,
            pipeline_config_id=target.pipeline_config_id,
            profile_id=target.id,
            previous_champion_profile_id=(None if previous is None else previous.id),
            occurred_at=promoted_at,
        )
        self._repository.flush()
        return RegistryMutationEvidence(changed=True)

    def retire_profile(
        self,
        *,
        profile_id: UUID,
        actor_ref: OpaqueReference,
        retired_at: datetime,
    ) -> RegistryMutationEvidence:
        row = self._repository.get_profile_for_update(profile_id=profile_id)
        if row is None:
            raise ModelRegistryUnavailable("perfil no disponible.")
        if AnalysisProfileStatus(row.status) is AnalysisProfileStatus.RETIRED:
            return RegistryMutationEvidence(changed=False)
        if AnalysisProfileRole(row.role) is AnalysisProfileRole.CHAMPION:
            raise ModelRegistryConflict(
                "un Champion debe ser reemplazado antes de retirarse."
            )
        row.status = AnalysisProfileStatus.RETIRED.value
        row.retired_by_ref = actor_ref
        row.retired_at = _utc(retired_at, field_name="retired_at")
        self._repository.record_event(
            action=GovernanceAction.PROFILE_RETIRED,
            model_family=row.model_family,
            tenant_ref=row.tenant_ref,
            actor_ref=actor_ref,
            model_version_id=row.model_version_id,
            pipeline_config_id=row.pipeline_config_id,
            profile_id=row.id,
            occurred_at=retired_at,
        )
        self._repository.flush()
        return RegistryMutationEvidence(changed=True)

    def retire_model(
        self,
        *,
        model_id: UUID,
        actor_ref: OpaqueReference,
        retired_at: datetime,
    ) -> RegistryMutationEvidence:
        row = self._repository.get_model_for_update(model_id=model_id)
        if row is None:
            raise ModelRegistryUnavailable("modelo no disponible.")
        status = ModelLifecycleStatus(row.status)
        if status is ModelLifecycleStatus.RETIRED:
            return RegistryMutationEvidence(changed=False)
        if status is not ModelLifecycleStatus.APPROVED:
            raise ModelRegistryConflict("sólo un modelo aprobado puede retirarse.")
        if self._repository.has_active_profiles_for_model(model_id=model_id):
            raise ModelRegistryConflict(
                "el modelo conserva perfiles activos y no puede retirarse."
            )
        row.status = ModelLifecycleStatus.RETIRED.value
        row.retired_at = _utc(retired_at, field_name="retired_at")
        self._repository.record_event(
            action=GovernanceAction.MODEL_RETIRED,
            model_family=row.model_family,
            actor_ref=actor_ref,
            model_version_id=row.id,
            occurred_at=retired_at,
        )
        self._repository.flush()
        return RegistryMutationEvidence(changed=True)

    def retire_pipeline_config(
        self,
        *,
        pipeline_config_id: UUID,
        actor_ref: OpaqueReference,
        retired_at: datetime,
    ) -> RegistryMutationEvidence:
        row = self._repository.get_pipeline_for_update(
            pipeline_config_id=pipeline_config_id
        )
        if row is None:
            raise ModelRegistryUnavailable("configuración no disponible.")
        status = ModelLifecycleStatus(row.status)
        if status is ModelLifecycleStatus.RETIRED:
            return RegistryMutationEvidence(changed=False)
        if status is not ModelLifecycleStatus.APPROVED:
            raise ModelRegistryConflict(
                "sólo una configuración aprobada puede retirarse."
            )
        if self._repository.has_active_profiles_for_pipeline(
            pipeline_config_id=pipeline_config_id
        ):
            raise ModelRegistryConflict(
                "la configuración conserva perfiles activos y no puede retirarse."
            )
        row.status = ModelLifecycleStatus.RETIRED.value
        row.retired_at = _utc(retired_at, field_name="retired_at")
        self._repository.record_event(
            action=GovernanceAction.PIPELINE_RETIRED,
            model_family=row.model_family,
            actor_ref=actor_ref,
            pipeline_config_id=row.id,
            occurred_at=retired_at,
        )
        self._repository.flush()
        return RegistryMutationEvidence(changed=True)


class DBIModelRegistryAnalysisProfilePolicy:
    """Política de Jobs respaldada por el Champion persistente del tenant."""

    def __init__(
        self,
        repository: DBIModelRegistryRepository,
        *,
        model_family: str = DEFAULT_ANALYSIS_MODEL_FAMILY,
    ) -> None:
        if not isinstance(repository, DBIModelRegistryRepository):
            raise TypeError("repository debe ser DBIModelRegistryRepository.")
        if not isinstance(model_family, str) or not model_family:
            raise TypeError("model_family es obligatorio.")
        self._repository = repository
        self._model_family = model_family

    def resolve(
        self,
        *,
        context: AnalysisProfileResolutionContext,
    ) -> ApprovedAnalysisProfile:
        if not isinstance(context, AnalysisProfileResolutionContext):
            raise TypeError("context debe ser AnalysisProfileResolutionContext.")
        return self._repository.resolve_champion(
            tenant_ref=context.tenant_ref,
            model_family=self._model_family,
        )
