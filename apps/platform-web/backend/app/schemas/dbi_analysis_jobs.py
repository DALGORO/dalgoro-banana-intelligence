"""Contratos versionados para trabajos geoespaciales DBI."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

ANALYSIS_JOB_COMMAND_SCHEMA_VERSION = "analysis-job-command.v1"
ANALYSIS_JOB_RESULT_SCHEMA_VERSION = "analysis-job-result.v1"
ARTIFACT_MANIFEST_SCHEMA_VERSION = "artifact-manifest.v1"

OpaqueReference = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
    ),
]
ShortText = Annotated[str, Field(min_length=1, max_length=240)]
Sha256Digest = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{64}$"),
]


class StrictContractModel(BaseModel):
    """Base estricta para impedir ampliaciones silenciosas."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class ArtifactRole(str, Enum):
    """Roles canónicos de los artefactos producidos por el pipeline."""

    VALIDATED_INVENTORY = "validated_inventory"
    ANALYSIS_BOUNDARY = "analysis_boundary"
    HEX_DENSITY = "hex_density"
    PLANTING_PRIORITY = "planting_priority"
    KDE_DENSITY = "kde_density"
    CARTOGRAPHIC_PACKAGE = "cartographic_package"
    TECHNICAL_REPORT = "technical_report"
    PIPELINE_STATE = "pipeline_state"
    PIPELINE_MANIFEST = "pipeline_manifest"


class PipelineStage(str, Enum):
    """Etapas conocidas del pipeline actual de densidad."""

    VALIDATE_ENVIRONMENT = "validate_environment"
    VALIDATE_RASTER = "validate_raster"
    VALIDATE_BOUNDARY = "validate_boundary"
    CLIP_RASTER = "clip_raster"
    GENERATE_TILES = "generate_tiles"
    RUN_YOLO = "run_yolo"
    GEOREFERENCE_DETECTIONS = "georeference_detections"
    EXPORT_RAW_GIS = "export_raw_gis"
    DEDUPLICATE_DETECTIONS = "deduplicate_detections"
    CALCULATE_STATISTICS = "calculate_statistics"
    ANALYZE_SPATIAL_PATTERN = "analyze_spatial_pattern"
    GENERATE_HEX_DENSITY = "generate_hex_density"
    DETECT_PLANTING_OPPORTUNITIES = "detect_planting_opportunities"
    PRIORITIZE_PLANTING_OPPORTUNITIES = (
        "prioritize_planting_opportunities"
    )
    GENERATE_KDE_DENSITY = "generate_kde_density"
    GENERATE_CARTOGRAPHIC_PACKAGE = "generate_cartographic_package"
    GENERATE_TECHNICAL_REPORT = "generate_technical_report"


class FindingClassification(str, Enum):
    """Naturaleza técnica de un hallazgo."""

    OBSERVED = "observed"
    INFERENCE = "inference"
    HYPOTHESIS = "hypothesis"
    RECOMMENDATION = "recommendation"


class ProfessionalReviewStatus(str, Enum):
    """Estado de revisión profesional de un hallazgo."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AnalysisJobInputs(StrictContractModel):
    """Referencias autorizadas de entrada, nunca rutas locales."""

    orthophoto_asset_id: OpaqueReference
    boundary_asset_id: OpaqueReference
    exclusions_asset_id: OpaqueReference | None = None


class AnalysisJobCommand(StrictContractModel):
    """Comando que la API podrá entregar al worker."""

    schema_version: Literal["analysis-job-command.v1"] = (
        ANALYSIS_JOB_COMMAND_SCHEMA_VERSION
    )
    request_id: OpaqueReference
    correlation_id: OpaqueReference
    job_id: OpaqueReference
    tenant_id: OpaqueReference
    farm_id: OpaqueReference
    lot_id: OpaqueReference
    inputs: AnalysisJobInputs
    model_version_id: OpaqueReference
    pipeline_config_version: OpaqueReference
    requested_by: OpaqueReference


class ArtifactManifest(StrictContractModel):
    """Metadatos verificables de un artefacto privado."""

    schema_version: Literal["artifact-manifest.v1"] = (
        ARTIFACT_MANIFEST_SCHEMA_VERSION
    )
    artifact_id: OpaqueReference
    job_id: OpaqueReference
    role: ArtifactRole
    object_key: str = Field(min_length=1, max_length=512)
    content_type: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$",
    )
    size_bytes: int = Field(gt=0)
    sha256: Sha256Digest
    produced_by_stage: PipelineStage
    crs: str | None = Field(default=None, min_length=1, max_length=80)
    created_at: AwareDatetime

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        """Rechaza URLs y rutas locales disfrazadas de clave de objeto."""

        lowered = value.lower()
        segments = value.split("/")
        if (
            "://" in lowered
            or value.startswith(("/", "\\"))
            or "\\" in value
            or any(segment in {"", ".", ".."} for segment in segments)
        ):
            raise ValueError(
                "object_key debe ser una referencia relativa de objeto."
            )
        return value


class FindingConfidence(StrictContractModel):
    """Confianza técnica sin equivaler a aprobación."""

    level: Literal["low", "medium", "high"]
    score: float | None = Field(default=None, ge=0, le=1)
    method: OpaqueReference


class ProfessionalReview(StrictContractModel):
    """Revisión profesional coherente con su estado."""

    status: ProfessionalReviewStatus
    reviewer_id: OpaqueReference | None = None
    reviewed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_review_state(self) -> "ProfessionalReview":
        """Exige actor y fecha únicamente para una decisión final."""

        final = self.status in {
            ProfessionalReviewStatus.APPROVED,
            ProfessionalReviewStatus.REJECTED,
        }
        if final and (self.reviewer_id is None or self.reviewed_at is None):
            raise ValueError(
                "Una revisión final exige reviewer_id y reviewed_at."
            )
        if not final and (
            self.reviewer_id is not None or self.reviewed_at is not None
        ):
            raise ValueError(
                "Una revisión no final no puede declarar actor o fecha."
            )
        return self


class AgronomicFinding(StrictContractModel):
    """Hallazgo trazable emitido por un resultado futuro."""

    schema_version: Literal["agronomic-finding.v1"] = (
        "agronomic-finding.v1"
    )
    finding_id: OpaqueReference
    job_id: OpaqueReference
    classification: FindingClassification
    statement: ShortText
    source_artifact_ids: list[OpaqueReference] = Field(
        min_length=1,
        max_length=32,
    )
    technical_source_refs: list[OpaqueReference] = Field(
        default_factory=list,
        max_length=32,
    )
    model_version_id: OpaqueReference
    confidence: FindingConfidence
    professional_review: ProfessionalReview


class AnalysisJobResult(StrictContractModel):
    """Resultado terminal publicado por un intento del worker."""

    schema_version: Literal["analysis-job-result.v1"] = (
        ANALYSIS_JOB_RESULT_SCHEMA_VERSION
    )
    correlation_id: OpaqueReference
    job_id: OpaqueReference
    attempt_id: OpaqueReference
    status: Literal["succeeded", "failed", "canceled"]
    pipeline_build: OpaqueReference
    started_at: AwareDatetime
    finished_at: AwareDatetime
    artifacts: list[ArtifactManifest] = Field(
        default_factory=list,
        max_length=128,
    )
    metrics: dict[str, int | float] = Field(
        default_factory=dict,
        max_length=128,
    )
    findings: list[AgronomicFinding] = Field(
        default_factory=list,
        max_length=1024,
    )
    warnings: list[ShortText] = Field(default_factory=list, max_length=128)
    errors: list[ShortText] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_time_order(self) -> "AnalysisJobResult":
        """Evita resultados que terminen antes de comenzar."""

        if self.finished_at < self.started_at:
            raise ValueError(
                "finished_at no puede ser anterior a started_at."
            )
        return self
