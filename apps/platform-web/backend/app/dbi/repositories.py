"""Repositorios DBI explícitos y acotados por ámbito."""

from __future__ import annotations

from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.dbi.models import (
    AnalysisArtifact,
    AnalysisInputAsset,
    AnalysisJob,
    AnalysisJobAttempt,
    Campaign,
    Farm,
    Plot,
)

ModelT = TypeVar("ModelT")


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

