"""Contratos internos, pequeños e inmutables para el worker DBI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.dbi.storage_contracts import DBIStorageObjectMetadata

MODEL_ARTIFACT_TENANT_REF = "dbi-model-registry"
WORKER_PIPELINE_BUILD = "dbi-worker-v1"


class DBIWorkerConflict(RuntimeError):
    """El estado o contrato recibido no permite una ejecución segura."""


class DBIWorkerUnavailable(LookupError):
    """Un recurso congelado del comando no está disponible."""


class DBIWorkerFailureCode(StrEnum):
    """Códigos acotados aptos para persistencia sin detalles sensibles."""

    INVALID_COMMAND = "WORKER_INVALID_COMMAND"
    RESOURCE_UNAVAILABLE = "WORKER_RESOURCE_UNAVAILABLE"
    STORAGE_INTEGRITY = "WORKER_STORAGE_INTEGRITY"
    MODEL_UNAVAILABLE = "WORKER_MODEL_UNAVAILABLE"
    PIPELINE_CONFIG_INVALID = "WORKER_PIPELINE_CONFIG_INVALID"
    PIPELINE_FAILED = "WORKER_PIPELINE_FAILED"
    LEASE_LOST = "WORKER_LEASE_LOST"
    CANCELED = "WORKER_CANCELED"
    INTERNAL_FAILURE = "WORKER_INTERNAL_FAILURE"


@dataclass(frozen=True, slots=True)
class ResolvedPrivateObject:
    """Objeto interno resuelto server-side; nunca se serializa hacia el cliente."""

    object_id: UUID
    kind: str
    metadata: DBIStorageObjectMetadata = field(repr=False)
    crs: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedModelArtifact:
    """Versión científica exacta y su artefacto privado verificable."""

    model_family: str
    model_version: str
    artifact_id: UUID
    metadata: DBIStorageObjectMetadata = field(repr=False)
    input_contract_version: str
    output_contract_version: str


@dataclass(frozen=True, slots=True)
class ResolvedPipelineConfig:
    """Configuración aprobada congelada por versión y huella."""

    model_family: str
    config_version: str
    config_sha256: str
    payload: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResolvedAnalysisPlan:
    """Plan interno completo para un único attempt."""

    job_id: UUID
    attempt_id: UUID
    correlation_id: str
    tenant_ref: str
    farm_id: UUID
    plot_id: UUID
    farm_name: str
    plot_name: str
    orthophoto: ResolvedPrivateObject
    boundary: ResolvedPrivateObject
    exclusions: ResolvedPrivateObject | None
    model: ResolvedModelArtifact
    pipeline: ResolvedPipelineConfig


class _StrictWorkerModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
        allow_inf_nan=False,
    )


class WorkerProcessingEvidence(_StrictWorkerModel):
    """Resultado observable de procesar un mensaje de comando."""

    message_id: UUID
    job_id: UUID
    attempt_id: UUID
    terminal_status: Literal["succeeded", "failed", "canceled"]
    replayed: bool
    acknowledged: bool
    failure_code: DBIWorkerFailureCode | None = None


class PipelineExecutionEvidence(_StrictWorkerModel):
    """Salida acotada del adaptador del pipeline heredado."""

    status: Literal["succeeded", "failed", "canceled"]
    return_code: int = Field(ge=0, le=255)
    run_directory: str | None = Field(default=None, repr=False)
    pipeline_manifest_path: str | None = Field(default=None, repr=False)
    pipeline_state_path: str | None = Field(default=None, repr=False)
