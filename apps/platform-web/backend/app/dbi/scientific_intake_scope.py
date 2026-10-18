"""Contratos de preautorización científica H14: metadata declarada, SIN carga.

La respuesta solo acredita identidad de Campaign en DBI bajo MANAGE.
Ningún byte del archivo ni hash se verifica, ni se concede grant/publicación.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.dbi.campaigns.contracts import (
    DBICampaignAnalysisType, DBICampaignSnapshot, DBICampaignStatus,
)

INDEXES = frozenset({"ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"})
ROLES = {("rgb", None)} | {
    (role, name) for name in INDEXES for role in ("scientific_cog", "qml_style")
}
PRE_INTAKE_STATUSES = frozenset({
    DBICampaignStatus.DRAFT, DBICampaignStatus.PROCESSING,
    DBICampaignStatus.ANALYZED, DBICampaignStatus.TECHNICAL_REVIEW,
})


class ScientificScopeUnavailable(ValueError):
    """Una Campaign no admite el borrador; no revela datos de otra organización."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, frozen=True)


def _canonical_ref(value: str) -> bool:
    return (
        1 <= len(value) <= 128 and value == value.strip()
        and "*" not in value
        and all(ord(char) >= 32 and ord(char) != 127 for char in value)
    )


class ScientificScope(_Strict):
    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    campaign_id: UUID

    @field_validator("tenant_ref", "organization_ref")
    @classmethod
    def require_canonical_ref(cls, value: str) -> str:
        if not _canonical_ref(value):
            raise ValueError("Referencia no canónica.")
        return value


class ScientificFolders(_Strict):
    geospatial: str = Field(min_length=1, max_length=180)
    multispectral: str = Field(min_length=1, max_length=180)

    @model_validator(mode="after")
    def check_roots(self) -> "ScientificFolders":
        for root in (self.geospatial, self.multispectral):
            if (
                root in {".", ".."} or "/" in root or "\\" in root
                or root != root.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in root)
            ):
                raise ValueError("Nombre de carpeta inválido.")
        if self.geospatial.casefold() == self.multispectral.casefold():
            raise ValueError("Las carpetas deben tener nombres distintos.")
        return self


class ScientificDraftItem(_Strict):
    folder: Literal["geospatial", "multispectral"]
    role: Literal["rgb", "scientific_cog", "qml_style"]
    index: Literal["ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"] | None
    relative_path: str = Field(min_length=3, max_length=512)
    size_bytes: int = Field(strict=True, gt=0, le=1_000_000_000_000)
    sha256: None
    file_content_verified: Literal[False]


class ScientificDraftScopeRequest(_Strict):
    schema_version: Literal["dbi-h14-scientific-reception-draft.v1"]
    state: Literal["local_metadata_only_not_uploaded"]
    scope: ScientificScope
    folders: ScientificFolders
    files: list[ScientificDraftItem] = Field(min_length=13, max_length=13)
    blockers: list[str] = Field(max_length=0)
    structural_ready: Literal[True]
    scientific_validated: Literal[False]
    server_received: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]

    @model_validator(mode="after")
    def require_exact_distinct_pairing(self) -> "ScientificDraftScopeRequest":
        pairs: set[tuple[str, str | None]] = set()
        paths: set[tuple[str, str]] = set()
        for file in self.files:
            kind = file.folder
            if (file.role, file.index) not in ROLES:
                raise ValueError("Un archivo no corresponde a uno de los 13 roles exigidos.")
            if kind != ("geospatial" if file.role == "rgb" else "multispectral"):
                raise ValueError("Carpeta y tipo de producto científico divergen.")
            root = getattr(self.folders, kind)
            if not file.relative_path.startswith(root + "/") or "\\" in file.relative_path:
                raise ValueError("El archivo no pertenece al directorio declarado.")
            parts = file.relative_path.split("/")
            if any(
                not seg or seg in {".", ".."}
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in seg)
                for seg in parts
            ):
                raise ValueError("Ruta relativa inválida.")
            lower_name = parts[-1].lower()
            allowed = (".qml",) if file.role == "qml_style" else (".tif", ".tiff")
            if not lower_name.endswith(allowed):
                raise ValueError("Extensión incompatible con el tipo de producto.")
            pair = (file.role, file.index)
            pathkey = (kind, file.relative_path.casefold())
            if pair in pairs or pathkey in paths:
                raise ValueError("Índices o rutas duplicadas.")
            pairs.add(pair)
            paths.add(pathkey)
        if pairs != ROLES:
            raise ValueError("Se requieren exactamente 1 RGB, 6 COG y 6 QML.")
        return self


class ScientificScopePreflightResponse(_Strict):
    schema_version: Literal["dbi-h14-scientific-scope-preflight.v1"]
    disposition: Literal["campaign_scope_verified_only_no_upload"]
    campaign_id: UUID
    campaign_status: DBICampaignStatus
    campaign_link_verified: Literal[True]
    file_content_verified: Literal[False]
    hashes_verified: Literal[False]
    scientific_validated: Literal[False]
    server_received: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def check_scientific_campaign_scope(
    *, request: ScientificDraftScopeRequest, campaign: DBICampaignSnapshot,
    tenant_ref: str, organization_ref: str, farm_id: UUID, plot_id: UUID,
) -> ScientificScopePreflightResponse:
    """Solo cruce exacto de scope/Campaign real. No persiste ni certifica archivos."""
    if (
        request.scope.tenant_ref != tenant_ref
        or request.scope.organization_ref != organization_ref
        or request.scope.farm_id != farm_id
        or request.scope.plot_id != plot_id
        or request.scope.campaign_id != campaign.campaign_id
        or campaign.tenant_ref != tenant_ref
        or campaign.organization_ref != organization_ref
        or campaign.farm_id != farm_id
        or campaign.plot_id != plot_id
        or campaign.analysis_type != DBICampaignAnalysisType.MULTISPECTRAL
        or campaign.status not in PRE_INTAKE_STATUSES
        or campaign.approved_at is not None
        or campaign.published_at is not None
    ):
        raise ScientificScopeUnavailable("Campaña o ámbito no disponible para preparación científica.")
    return ScientificScopePreflightResponse(
        schema_version="dbi-h14-scientific-scope-preflight.v1",
        disposition="campaign_scope_verified_only_no_upload",
        campaign_id=campaign.campaign_id,
        campaign_status=campaign.status,
        campaign_link_verified=True,
        file_content_verified=False,
        hashes_verified=False,
        scientific_validated=False,
        server_received=False,
        institutional_approved=False,
        published=False,
    )
