"""Contratos puros para el servicio autorizado de trabajos DBI."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.dbi.jobs.state_machine import AnalysisJobStatus
from app.schemas.dbi_analysis_jobs import OpaqueReference

ANALYSIS_JOB_REQUEST_SCHEMA_VERSION = "dbi-analysis-job-request.v1"
ANALYSIS_JOB_RESPONSE_SCHEMA_VERSION = "dbi-analysis-job-response.v1"
ANALYSIS_JOB_INTENT_SCHEMA_VERSION = "dbi-analysis-job-intent.v1"
ANALYSIS_PROFILE_SCHEMA_VERSION = "dbi-analysis-profile.v1"


class _StrictJobServiceModel(BaseModel):
    """Base inmutable que rechaza campos no declarados."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
        frozen=True,
    )


class AnalysisJobCreateRequest(_StrictJobServiceModel):
    """Solicitud HTTP segura: solo UUID y una clave idempotente."""

    schema_version: Literal["dbi-analysis-job-request.v1"] = (
        ANALYSIS_JOB_REQUEST_SCHEMA_VERSION
    )
    request_id: OpaqueReference
    campaign_id: UUID | None = None
    orthophoto_asset_id: UUID
    boundary_asset_id: UUID
    exclusions_asset_id: UUID | None = None


class AnalysisJobCreateResponse(_StrictJobServiceModel):
    """Respuesta pública sin referencias internas ni huellas."""

    schema_version: Literal["dbi-analysis-job-response.v1"] = (
        ANALYSIS_JOB_RESPONSE_SCHEMA_VERSION
    )
    job_id: UUID
    status: AnalysisJobStatus
    accepted_at: AwareDatetime
    created: bool


class AnalysisJobRequestIntent(_StrictJobServiceModel):
    """Intención estable usada para neutralizar reintentos HTTP."""

    schema_version: Literal["dbi-analysis-job-intent.v1"] = (
        ANALYSIS_JOB_INTENT_SCHEMA_VERSION
    )
    tenant_ref: OpaqueReference
    request_id: OpaqueReference
    farm_id: UUID
    plot_id: UUID
    campaign_id: UUID | None = None
    orthophoto_asset_id: UUID
    boundary_asset_id: UUID
    exclusions_asset_id: UUID | None = None
    requested_by_ref: OpaqueReference


class ApprovedAnalysisProfile(_StrictJobServiceModel):
    """Perfil versionado resuelto por una política confiable del servidor."""

    schema_version: Literal["dbi-analysis-profile.v1"] = (
        ANALYSIS_PROFILE_SCHEMA_VERSION
    )
    model_version_id: OpaqueReference
    pipeline_config_version: OpaqueReference
    policy_ref: OpaqueReference


class AnalysisProfileResolutionContext(_StrictJobServiceModel):
    """Ámbito mínimo que una política puede usar para resolver el perfil."""

    tenant_ref: OpaqueReference
    organization_ref: OpaqueReference
    farm_id: UUID
    plot_id: UUID
    campaign_id: UUID | None = None


class AnalysisProfileUnavailable(RuntimeError):
    """Indica que no existe un perfil único, aprobado y utilizable."""


@runtime_checkable
class AnalysisProfilePolicy(Protocol):
    """Puerto puro para seleccionar un perfil aprobado por el servidor."""

    def resolve(
        self,
        *,
        context: AnalysisProfileResolutionContext,
    ) -> ApprovedAnalysisProfile:
        """Devuelve exactamente un perfil aprobado o falla cerrada."""

        ...


def canonical_contract_bytes(contract: BaseModel) -> bytes:
    """Serializa un contrato de manera determinista y reproducible."""

    payload = contract.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=False,
    )
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return canonical_json.encode("utf-8")


def contract_sha256(contract: BaseModel) -> str:
    """Calcula SHA-256 hexadecimal sobre la serialización canónica."""

    return hashlib.sha256(canonical_contract_bytes(contract)).hexdigest()


def analysis_job_request_fingerprint(
    intent: AnalysisJobRequestIntent,
) -> str:
    """Calcula la huella estable de una intención de solicitud."""

    return contract_sha256(intent)
