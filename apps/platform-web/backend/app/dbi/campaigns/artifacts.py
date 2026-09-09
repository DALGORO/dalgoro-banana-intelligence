"""Catálogo técnico versionado de productos finales de una Campaign DBI."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.campaigns.contracts import DBICampaignConflict, DBICampaignUnavailable
from app.dbi.campaigns.repository import DBICampaignRepository
from app.dbi.models import (
    AnalysisArtifact,
    AnalysisInputAsset,
    AnalysisJob,
    Campaign,
    DBICampaignArtifact,
)

_CAMPAIGN_ARTIFACT_NAMESPACE = UUID("c1b6f292-01a7-4d3d-9498-e35d8dff1495")


class DBICampaignArtifactType(StrEnum):
    """Productos técnicos admitidos por el plan maestro Campaign."""

    ORTHOPHOTO_SOURCE = "orthophoto_source"
    BOUNDARY = "boundary"
    VALIDATED_INVENTORY = "validated_inventory"
    DENSITY_HEXAGONS = "density_hexagons"
    PLANTING_CANDIDATES = "planting_candidates"
    OPERATIONAL_PRIORITY = "operational_priority"
    KDE = "kde"
    EXCLUSIONS = "exclusions"
    TECHNICAL_REPORT = "technical_report"
    SAMPLING_PLAN = "sampling_plan"
    SAMPLING_POINTS = "sampling_points"
    FIELD_OBSERVATIONS = "field_observations"


class DBICampaignArtifactSourceKind(StrEnum):
    """Familia de evidencia a la que apunta una entrada del catálogo."""

    INPUT_ASSET = "input_asset"
    ANALYSIS_ARTIFACT = "analysis_artifact"
    DOMAIN_RECORD = "domain_record"


class DBICampaignArtifactTechnicalStatus(StrEnum):
    CURRENT = "current"
    SUPERSEDED = "superseded"


class _CampaignArtifactModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class DBICampaignArtifactRegistration(_CampaignArtifactModel):
    """Solicitud idempotente de una versión técnica verificable."""

    artifact_type: DBICampaignArtifactType
    source_kind: DBICampaignArtifactSourceKind
    source_ref: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: int = Field(ge=1)
    source_revision_id: UUID | None = None


class DBICampaignArtifactSnapshot(_CampaignArtifactModel):
    campaign_artifact_id: UUID
    campaign_id: UUID
    artifact_type: DBICampaignArtifactType
    source_kind: DBICampaignArtifactSourceKind
    source_ref: UUID
    sha256: str
    created_at: datetime
    version: int
    technical_status: DBICampaignArtifactTechnicalStatus
    published: bool
    source_revision_id: UUID | None


class DBICampaignArtifactMutationResponse(DBICampaignArtifactSnapshot):
    created: bool


_INPUT_ASSET_KIND_BY_TYPE = {
    DBICampaignArtifactType.ORTHOPHOTO_SOURCE: "orthophoto",
    DBICampaignArtifactType.BOUNDARY: "boundary",
    DBICampaignArtifactType.EXCLUSIONS: "exclusions",
}

_ANALYSIS_ROLE_BY_TYPE = {
    DBICampaignArtifactType.BOUNDARY: "analysis_boundary",
    DBICampaignArtifactType.VALIDATED_INVENTORY: "validated_inventory",
    DBICampaignArtifactType.DENSITY_HEXAGONS: "hex_density",
    DBICampaignArtifactType.OPERATIONAL_PRIORITY: "planting_priority",
    DBICampaignArtifactType.KDE: "kde_density",
    DBICampaignArtifactType.TECHNICAL_REPORT: "technical_report",
}


class DBICampaignArtifactRepository:
    """Persistencia sin commit/rollback y con scope heredado desde Campaign."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBICampaignConflict("session debe ser Session.")
        self._session = session

    def get_by_version(
        self,
        *,
        campaign_id: UUID,
        artifact_type: DBICampaignArtifactType,
        version: int,
    ) -> DBICampaignArtifact | None:
        return self._session.execute(
            select(DBICampaignArtifact).where(
                DBICampaignArtifact.campaign_id == campaign_id,
                DBICampaignArtifact.artifact_type == artifact_type.value,
                DBICampaignArtifact.version == version,
            )
        ).scalar_one_or_none()

    def get_current_for_update(
        self,
        *,
        campaign_id: UUID,
        artifact_type: DBICampaignArtifactType,
    ) -> DBICampaignArtifact | None:
        return self._session.execute(
            select(DBICampaignArtifact)
            .where(
                DBICampaignArtifact.campaign_id == campaign_id,
                DBICampaignArtifact.artifact_type == artifact_type.value,
                DBICampaignArtifact.technical_status
                == DBICampaignArtifactTechnicalStatus.CURRENT.value,
            )
            .with_for_update()
        ).scalar_one_or_none()

    def get_scoped_artifact(
        self,
        *,
        campaign_artifact_id: UUID,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBICampaignArtifact | None:
        return self._session.execute(
            select(DBICampaignArtifact)
            .join(Campaign, DBICampaignArtifact.campaign_id == Campaign.id)
            .where(
                DBICampaignArtifact.id == campaign_artifact_id,
                DBICampaignArtifact.campaign_id == campaign_id,
                Campaign.tenant_ref == tenant_ref,
                Campaign.organization_ref == organization_ref,
                Campaign.farm_id == farm_id,
                Campaign.plot_id == plot_id,
                Campaign.analysis_type.is_not(None),
            )
        ).scalar_one_or_none()

    def list_scoped_artifacts(
        self,
        *,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> list[DBICampaignArtifact]:
        return list(
            self._session.execute(
                select(DBICampaignArtifact)
                .join(Campaign, DBICampaignArtifact.campaign_id == Campaign.id)
                .where(
                    DBICampaignArtifact.campaign_id == campaign_id,
                    Campaign.tenant_ref == tenant_ref,
                    Campaign.organization_ref == organization_ref,
                    Campaign.farm_id == farm_id,
                    Campaign.plot_id == plot_id,
                    Campaign.analysis_type.is_not(None),
                )
                .order_by(
                    DBICampaignArtifact.artifact_type,
                    DBICampaignArtifact.version,
                )
            ).scalars()
        )

    def get_input_asset(
        self,
        *,
        source_ref: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> AnalysisInputAsset | None:
        return self._session.execute(
            select(AnalysisInputAsset).where(
                AnalysisInputAsset.id == source_ref,
                AnalysisInputAsset.tenant_ref == tenant_ref,
                AnalysisInputAsset.farm_id == farm_id,
                or_(
                    AnalysisInputAsset.plot_id == plot_id,
                    AnalysisInputAsset.plot_id.is_(None),
                ),
            )
        ).scalar_one_or_none()

    def get_analysis_artifact(
        self,
        *,
        source_ref: UUID,
        campaign_id: UUID,
        source_job_id: UUID | None,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> AnalysisArtifact | None:
        job_scope = AnalysisJob.campaign_id == campaign_id
        if source_job_id is not None:
            job_scope = or_(job_scope, AnalysisJob.id == source_job_id)
        return self._session.execute(
            select(AnalysisArtifact)
            .join(AnalysisJob, AnalysisArtifact.job_id == AnalysisJob.id)
            .where(
                AnalysisArtifact.id == source_ref,
                AnalysisJob.tenant_ref == tenant_ref,
                AnalysisJob.farm_id == farm_id,
                AnalysisJob.plot_id == plot_id,
                job_scope,
            )
        ).scalar_one_or_none()

    def persist_current(
        self,
        *,
        campaign_id: UUID,
        request: DBICampaignArtifactRegistration,
    ) -> tuple[DBICampaignArtifact, bool]:
        stable_id = uuid5(
            _CAMPAIGN_ARTIFACT_NAMESPACE,
            f"dbi:campaign-artifact:v1:{campaign_id}:{request.artifact_type.value}:{request.version}",
        )
        inserted = self._session.execute(
            postgresql_insert(DBICampaignArtifact)
            .values(
                id=stable_id,
                campaign_id=campaign_id,
                artifact_type=request.artifact_type.value,
                source_kind=request.source_kind.value,
                source_ref=request.source_ref,
                sha256=request.sha256,
                version=request.version,
                technical_status=DBICampaignArtifactTechnicalStatus.CURRENT.value,
                published=False,
                source_revision_id=request.source_revision_id,
            )
            .on_conflict_do_nothing()
            .returning(DBICampaignArtifact.id)
        ).scalar_one_or_none()
        self._session.flush()
        row = self.get_by_version(
            campaign_id=campaign_id,
            artifact_type=request.artifact_type,
            version=request.version,
        )
        if row is None:
            raise DBICampaignConflict("El artefacto de Campaign no quedó persistido.")
        if row.id != stable_id:
            raise DBICampaignConflict("La identidad del artefacto de Campaign diverge.")
        return row, inserted is not None

    def flush(self) -> None:
        self._session.flush()


def campaign_artifact_snapshot(row: DBICampaignArtifact) -> DBICampaignArtifactSnapshot:
    return DBICampaignArtifactSnapshot(
        campaign_artifact_id=row.id,
        campaign_id=row.campaign_id,
        artifact_type=DBICampaignArtifactType(row.artifact_type),
        source_kind=DBICampaignArtifactSourceKind(row.source_kind),
        source_ref=row.source_ref,
        sha256=row.sha256,
        created_at=row.created_at,
        version=row.version,
        technical_status=DBICampaignArtifactTechnicalStatus(row.technical_status),
        published=row.published,
        source_revision_id=row.source_revision_id,
    )


def _registration_matches(
    row: DBICampaignArtifact,
    request: DBICampaignArtifactRegistration,
) -> bool:
    return (
        row.artifact_type == request.artifact_type.value
        and row.source_kind == request.source_kind.value
        and row.source_ref == request.source_ref
        and row.sha256 == request.sha256
        and row.version == request.version
        and row.source_revision_id == request.source_revision_id
    )


class DBICampaignArtifactService:
    """Registra productos verificables sin publicar ni modificar ciencia."""

    def __init__(self, session: Session) -> None:
        self._campaigns = DBICampaignRepository(session)
        self._artifacts = DBICampaignArtifactRepository(session)

    def _validate_source(
        self,
        *,
        campaign: Campaign,
        request: DBICampaignArtifactRegistration,
    ) -> None:
        if campaign.plot_id is None or campaign.tenant_ref is None:
            raise DBICampaignUnavailable("Campaign técnica no disponible.")

        if request.source_kind is DBICampaignArtifactSourceKind.INPUT_ASSET:
            expected_kind = _INPUT_ASSET_KIND_BY_TYPE.get(request.artifact_type)
            if expected_kind is None:
                raise DBICampaignConflict(
                    "El tipo técnico solicitado no admite un input_asset como fuente."
                )
            asset = self._artifacts.get_input_asset(
                source_ref=request.source_ref,
                tenant_ref=campaign.tenant_ref,
                farm_id=campaign.farm_id,
                plot_id=campaign.plot_id,
            )
            if asset is None or asset.asset_kind != expected_kind:
                raise DBICampaignUnavailable("Activo fuente de Campaign no disponible.")
            if asset.sha256 != request.sha256:
                raise DBICampaignConflict("El SHA256 no coincide con el activo fuente.")
            return

        if request.source_kind is DBICampaignArtifactSourceKind.ANALYSIS_ARTIFACT:
            expected_role = _ANALYSIS_ROLE_BY_TYPE.get(request.artifact_type)
            if expected_role is None:
                raise DBICampaignConflict(
                    "El tipo técnico solicitado no admite un analysis_artifact como fuente."
                )
            artifact = self._artifacts.get_analysis_artifact(
                source_ref=request.source_ref,
                campaign_id=campaign.id,
                source_job_id=campaign.source_job_id,
                tenant_ref=campaign.tenant_ref,
                farm_id=campaign.farm_id,
                plot_id=campaign.plot_id,
            )
            if artifact is None or artifact.role != expected_role:
                raise DBICampaignUnavailable("Artefacto fuente de Campaign no disponible.")
            if artifact.sha256 != request.sha256:
                raise DBICampaignConflict("El SHA256 no coincide con el artefacto fuente.")
            return

        raise DBICampaignUnavailable(
            "domain_record está reservado para Sampling/campo y aún no puede catalogarse."
        )

    def register_artifact(
        self,
        *,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        request: DBICampaignArtifactRegistration,
    ) -> tuple[DBICampaignArtifactSnapshot, bool]:
        campaign = self._campaigns.get_campaign_for_update(
            campaign_id=campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if campaign is None:
            raise DBICampaignUnavailable("Campaign DBI no disponible.")

        existing = self._artifacts.get_by_version(
            campaign_id=campaign_id,
            artifact_type=request.artifact_type,
            version=request.version,
        )
        if existing is not None:
            if not _registration_matches(existing, request):
                raise DBICampaignConflict(
                    "La versión ya existe con una fuente técnica diferente."
                )
            return campaign_artifact_snapshot(existing), False

        self._validate_source(campaign=campaign, request=request)

        current = self._artifacts.get_current_for_update(
            campaign_id=campaign_id,
            artifact_type=request.artifact_type,
        )
        expected_version = 1 if current is None else current.version + 1
        if request.version != expected_version:
            raise DBICampaignConflict(
                f"La siguiente versión válida para {request.artifact_type.value} es {expected_version}."
            )

        if current is not None:
            current.technical_status = DBICampaignArtifactTechnicalStatus.SUPERSEDED.value
            self._artifacts.flush()

        row, created = self._artifacts.persist_current(
            campaign_id=campaign_id,
            request=request,
        )
        if not _registration_matches(row, request):
            raise DBICampaignConflict("El artefacto persistido diverge de la solicitud.")
        return campaign_artifact_snapshot(row), created


class DBICampaignArtifactReader:
    """Lee el catálogo únicamente a través del scope completo de Campaign."""

    def __init__(self, session: Session) -> None:
        self._campaigns = DBICampaignRepository(session)
        self._artifacts = DBICampaignArtifactRepository(session)

    def _require_campaign(
        self,
        *,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> None:
        if self._campaigns.get_campaign(
            campaign_id=campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        ) is None:
            raise DBICampaignUnavailable("Campaign DBI no disponible.")

    def read_artifact(
        self,
        *,
        campaign_artifact_id: UUID,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBICampaignArtifactSnapshot:
        self._require_campaign(
            campaign_id=campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        row = self._artifacts.get_scoped_artifact(
            campaign_artifact_id=campaign_artifact_id,
            campaign_id=campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if row is None:
            raise DBICampaignUnavailable("Artefacto de Campaign no disponible.")
        return campaign_artifact_snapshot(row)

    def list_artifacts(
        self,
        *,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> list[DBICampaignArtifactSnapshot]:
        self._require_campaign(
            campaign_id=campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        return [
            campaign_artifact_snapshot(row)
            for row in self._artifacts.list_scoped_artifacts(
                campaign_id=campaign_id,
                tenant_ref=tenant_ref,
                organization_ref=organization_ref,
                farm_id=farm_id,
                plot_id=plot_id,
            )
        ]
