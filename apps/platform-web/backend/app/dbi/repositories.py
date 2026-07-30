"""Repositorios DBI explícitos y acotados por ámbito."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, defer

from app.dbi.models import (
    AnalysisArtifact,
    AnalysisInputAsset,
    AnalysisJob,
    AnalysisJobAttempt,
    Campaign,
    Farm,
    Plot,
)
from app.dbi.spatial import DBI_SPATIAL_RESULT_LIMIT, DBI_SPATIAL_SRID

ModelT = TypeVar("ModelT")
DBI_READ_LIST_LIMIT = 100


class _DBIRepository(Generic[ModelT]):
    """Base mínima que conserva una única sesión recibida."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entity: ModelT) -> ModelT:
        """Añade una entidad a la transacción actual sin confirmarla."""

        self._session.add(entity)
        return entity

    def _one_or_none(
        self,
        statement: Select[tuple[ModelT]],
    ) -> ModelT | None:
        return self._session.execute(statement).scalar_one_or_none()

    def _all(
        self,
        statement: Select[tuple[ModelT]],
    ) -> Sequence[ModelT]:
        return self._session.execute(statement).scalars().all()


class FarmRepository(_DBIRepository[Farm]):
    """Acceso a fincas limitado por la organización referenciada."""

    def get_by_id(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
    ) -> Farm | None:
        return self._one_or_none(
            select(Farm).where(
                Farm.id == farm_id,
                Farm.organization_ref == organization_ref,
            )
        )

    def get_by_code(
        self,
        *,
        organization_ref: str,
        code: str,
    ) -> Farm | None:
        return self._one_or_none(
            select(Farm).where(
                Farm.organization_ref == organization_ref,
                Farm.code == code,
            )
        )

    def list_by_organization(self, *, organization_ref: str) -> Sequence[Farm]:
        return self._all(
            select(Farm)
            .where(Farm.organization_ref == organization_ref)
            .order_by(Farm.code, Farm.id)
            .limit(DBI_READ_LIST_LIMIT)
        )


class PlotRepository(_DBIRepository[Plot]):
    """Acceso a lotes acotado mediante la organización de su finca."""

    def get_by_id(
        self,
        *,
        organization_ref: str,
        plot_id: UUID,
    ) -> Plot | None:
        return self._one_or_none(
            select(Plot)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(
                Plot.id == plot_id,
                Farm.organization_ref == organization_ref,
            )
        )

    def list_by_farm(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
    ) -> Sequence[Plot]:
        return self._all(
            select(Plot)
            .options(defer(Plot.boundary))
            .join(Farm, Plot.farm_id == Farm.id)
            .where(
                Plot.farm_id == farm_id,
                Farm.organization_ref == organization_ref,
            )
            .order_by(Plot.code, Plot.id)
            .limit(DBI_READ_LIST_LIMIT)
        )

    def list_intersecting_boundary(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_ids: frozenset[UUID],
        min_longitude: float,
        min_latitude: float,
        max_longitude: float,
        max_latitude: float,
        limit: int,
    ) -> Sequence[Plot]:
        """Lista lotes autorizados que intersectan una envolvente EPSG:4326."""

        if not plot_ids:
            return ()

        envelope = func.ST_MakeEnvelope(
            min_longitude,
            min_latitude,
            max_longitude,
            max_latitude,
            DBI_SPATIAL_SRID,
        )
        return self._all(
            select(Plot)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(
                Plot.farm_id == farm_id,
                Farm.organization_ref == organization_ref,
                Plot.id.in_(plot_ids),
                Plot.boundary.is_not(None),
                func.ST_Intersects(Plot.boundary, envelope),
            )
            .order_by(Plot.code, Plot.id)
            .limit(min(limit, DBI_SPATIAL_RESULT_LIMIT))
        )


class CampaignRepository(_DBIRepository[Campaign]):
    """Acceso a campañas acotado mediante la organización de su finca."""

    def get_by_id(
        self,
        *,
        organization_ref: str,
        campaign_id: UUID,
    ) -> Campaign | None:
        return self._one_or_none(
            select(Campaign)
            .join(Farm, Campaign.farm_id == Farm.id)
            .where(
                Campaign.id == campaign_id,
                Farm.organization_ref == organization_ref,
            )
        )

    def list_by_farm(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
    ) -> Sequence[Campaign]:
        return self._all(
            select(Campaign)
            .join(Farm, Campaign.farm_id == Farm.id)
            .where(
                Campaign.farm_id == farm_id,
                Farm.organization_ref == organization_ref,
            )
            .order_by(Campaign.starts_at.desc(), Campaign.id)
            .limit(DBI_READ_LIST_LIMIT)
        )


class AnalysisJobRepository(_DBIRepository[AnalysisJob]):
    """Acceso a trabajos limitado por tenant e idempotencia."""

    def get_by_id(
        self,
        *,
        tenant_ref: str,
        job_id: UUID,
    ) -> AnalysisJob | None:
        return self._one_or_none(
            select(AnalysisJob).where(
                AnalysisJob.id == job_id,
                AnalysisJob.tenant_ref == tenant_ref,
            )
        )

    def get_by_request_id(
        self,
        *,
        tenant_ref: str,
        request_id: str,
    ) -> AnalysisJob | None:
        return self._one_or_none(
            select(AnalysisJob).where(
                AnalysisJob.tenant_ref == tenant_ref,
                AnalysisJob.request_id == request_id,
            )
        )

    def list_by_farm(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
    ) -> Sequence[AnalysisJob]:
        return self._all(
            select(AnalysisJob)
            .where(
                AnalysisJob.tenant_ref == tenant_ref,
                AnalysisJob.farm_id == farm_id,
            )
            .order_by(AnalysisJob.created_at.desc(), AnalysisJob.id)
            .limit(DBI_READ_LIST_LIMIT)
        )


class AnalysisJobAttemptRepository(_DBIRepository[AnalysisJobAttempt]):
    """Acceso a intentos acotado mediante el tenant de su trabajo."""

    def get_by_id(
        self,
        *,
        tenant_ref: str,
        attempt_id: UUID,
    ) -> AnalysisJobAttempt | None:
        return self._one_or_none(
            select(AnalysisJobAttempt)
            .join(
                AnalysisJob,
                AnalysisJobAttempt.job_id == AnalysisJob.id,
            )
            .where(
                AnalysisJobAttempt.id == attempt_id,
                AnalysisJob.tenant_ref == tenant_ref,
            )
        )


class AnalysisInputAssetRepository(_DBIRepository[AnalysisInputAsset]):
    """Acceso a activos de entrada limitado por tenant."""

    def get_by_id(
        self,
        *,
        tenant_ref: str,
        asset_id: UUID,
    ) -> AnalysisInputAsset | None:
        return self._one_or_none(
            select(AnalysisInputAsset).where(
                AnalysisInputAsset.id == asset_id,
                AnalysisInputAsset.tenant_ref == tenant_ref,
            )
        )

    def list_by_farm(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
    ) -> Sequence[AnalysisInputAsset]:
        return self._all(
            select(AnalysisInputAsset)
            .where(
                AnalysisInputAsset.tenant_ref == tenant_ref,
                AnalysisInputAsset.farm_id == farm_id,
            )
            .order_by(AnalysisInputAsset.created_at.desc(), AnalysisInputAsset.id)
            .limit(DBI_READ_LIST_LIMIT)
        )


class AnalysisArtifactRepository(_DBIRepository[AnalysisArtifact]):
    """Acceso a artefactos acotado mediante el tenant de su trabajo."""

    def get_by_id(
        self,
        *,
        tenant_ref: str,
        artifact_id: UUID,
    ) -> AnalysisArtifact | None:
        return self._one_or_none(
            select(AnalysisArtifact)
            .join(
                AnalysisJob,
                AnalysisArtifact.job_id == AnalysisJob.id,
            )
            .where(
                AnalysisArtifact.id == artifact_id,
                AnalysisJob.tenant_ref == tenant_ref,
            )
        )

    def list_by_job(
        self,
        *,
        tenant_ref: str,
        job_id: UUID,
    ) -> Sequence[AnalysisArtifact]:
        return self._all(
            select(AnalysisArtifact)
            .join(
                AnalysisJob,
                AnalysisArtifact.job_id == AnalysisJob.id,
            )
            .where(
                AnalysisArtifact.job_id == job_id,
                AnalysisJob.tenant_ref == tenant_ref,
            )
            .order_by(AnalysisArtifact.created_at, AnalysisArtifact.id)
            .limit(DBI_READ_LIST_LIMIT)
        )
