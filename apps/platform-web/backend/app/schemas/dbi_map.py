"""Contratos versionados para la interfaz cronológica de mapas DBI."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FARM_MAP_TIMELINE_SCHEMA_VERSION = "farm-map-timeline.v1"


class StrictContractModel(BaseModel):
    """Base estricta para impedir ampliaciones silenciosas del contrato."""

    model_config = ConfigDict(extra="forbid")


class MapLayerType(str, Enum):
    """Tipos de capa previstos para la cronología agrícola."""

    RGB = "rgb"
    NDVI = "ndvi"
    NDRE = "ndre"
    DENSITY = "density"
    ANOMALIES = "anomalies"
    INSPECTIONS = "inspections"
    PRODUCTION = "production"
    SST = "sst"


class EvidenceClassification(str, Enum):
    """Naturaleza técnica de una entrada de la cronología."""

    OBSERVED = "observed"
    INFERENCE = "inference"
    HYPOTHESIS = "hypothesis"
    RECOMMENDATION = "recommendation"


class ProfessionalReviewStatus(str, Enum):
    """Estado de revisión profesional de una entrada."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MapLayerCatalogEntry(StrictContractModel):
    """Metadatos de una capa admitida, no evidencia disponible."""

    layer_type: MapLayerType
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=240)
    default_classification: EvidenceClassification


class Confidence(StrictContractModel):
    """Confianza declarada sin equivaler a aprobación profesional."""

    level: Literal["low", "medium", "high"]
    score: float | None = Field(default=None, ge=0, le=1)
    method_ref: str = Field(min_length=1, max_length=160)


class MapTimelineEntry(StrictContractModel):
    """Entrada futura de la cronología con procedencia obligatoria."""

    entry_id: str = Field(min_length=1, max_length=128)
    layer_type: MapLayerType
    captured_at: datetime
    title: str = Field(min_length=1, max_length=160)
    classification: EvidenceClassification
    source_artifact_id: str = Field(min_length=1, max_length=128)
    confidence: Confidence | None = None
    professional_review_status: ProfessionalReviewStatus


class MapComparisonCapability(StrictContractModel):
    """Disponibilidad de comparación entre fechas reales."""

    minimum_dates: Literal[2] = 2
    available_dates: list[datetime] = Field(default_factory=list)
    enabled: bool = False


class FarmMapTimelineResponse(StrictContractModel):
    """Respuesta v1 consumida por la interfaz cronológica."""

    schema_version: Literal["farm-map-timeline.v1"] = (
        FARM_MAP_TIMELINE_SCHEMA_VERSION
    )
    farm_id: str = Field(min_length=1, max_length=128)
    status: Literal["awaiting_data"] = "awaiting_data"
    available_layers: list[MapLayerCatalogEntry]
    timeline: list[MapTimelineEntry] = Field(default_factory=list)
    comparison: MapComparisonCapability = Field(
        default_factory=MapComparisonCapability
    )


MAP_LAYER_CATALOG = (
    MapLayerCatalogEntry(
        layer_type=MapLayerType.RGB,
        label="RGB",
        description="Imagen visible capturada para la campaña.",
        default_classification=EvidenceClassification.OBSERVED,
    ),
    MapLayerCatalogEntry(
        layer_type=MapLayerType.NDVI,
        label="NDVI",
        description="Índice de vegetación calculado a partir de bandas espectrales.",
        default_classification=EvidenceClassification.INFERENCE,
    ),
    MapLayerCatalogEntry(
        layer_type=MapLayerType.NDRE,
        label="NDRE",
        description="Índice de borde rojo calculado para análisis de vigor.",
        default_classification=EvidenceClassification.INFERENCE,
    ),
    MapLayerCatalogEntry(
        layer_type=MapLayerType.DENSITY,
        label="Densidad",
        description="Resultado espacial derivado del inventario de plantas.",
        default_classification=EvidenceClassification.INFERENCE,
    ),
    MapLayerCatalogEntry(
        layer_type=MapLayerType.ANOMALIES,
        label="Anomalías",
        description="Señales espaciales que requieren revisión técnica.",
        default_classification=EvidenceClassification.INFERENCE,
    ),
    MapLayerCatalogEntry(
        layer_type=MapLayerType.INSPECTIONS,
        label="Inspecciones",
        description="Registros georreferenciados levantados en campo.",
        default_classification=EvidenceClassification.OBSERVED,
    ),
    MapLayerCatalogEntry(
        layer_type=MapLayerType.PRODUCTION,
        label="Producción",
        description="Registros operativos de producción asociados al territorio.",
        default_classification=EvidenceClassification.OBSERVED,
    ),
    MapLayerCatalogEntry(
        layer_type=MapLayerType.SST,
        label="SST",
        description="Registros georreferenciados de seguridad y salud en el trabajo.",
        default_classification=EvidenceClassification.OBSERVED,
    ),
)


def build_empty_farm_map_timeline(farm_id: str) -> FarmMapTimelineResponse:
    """Construye el estado inicial sin inventar campañas o resultados."""

    return FarmMapTimelineResponse(
        farm_id=farm_id,
        available_layers=list(MAP_LAYER_CATALOG),
    )
