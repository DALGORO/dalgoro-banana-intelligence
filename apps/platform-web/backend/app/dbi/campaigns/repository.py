"""Persistencia idempotente y acotada de campañas técnicas DBI."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.campaigns.contracts import (
    DBICampaignConflict,
    DBICampaignCreate,
)
from app.dbi.models import Campaign, Farm, Plot


class DBICampaignRepository:
    """Lee y escribe campañas técnicas sin commit/rollback propios."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBICampaignConflict("session debe ser Session.")
        self._session = session

    def scope_exists(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> bool:
        return (
            self._session.execute(
                select(Plot.id)
                .join(Farm, Plot.farm_id == Farm.id)
                .where(
                    Plot.id == plot_id,
                    Plot.farm_id == farm_id,
                    Farm.id == farm_id,
                    Farm.organization_ref == organization_ref,
                )
            ).scalar_one_or_none()
            is not None
        )

    def persist_campaign(
        self,
        *,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        request: DBICampaignCreate,
    ) -> tuple[Campaign, bool]:
        """Inserta por campaign_id o valida que el replay sea exactamente igual."""

        code = f"dbi-{request.campaign_id}"
        name = f"DBI {request.analysis_type.value} {request.captured_at.isoformat()}"
        inserted_id = self._session.execute(
            postgresql_insert(Campaign)
            .values(
                id=request.campaign_id,
                tenant_ref=tenant_ref,
                organization_ref=organization_ref,
                farm_id=farm_id,
                plot_id=plot_id,
                code=code,
                name=name,
                analysis_type=request.analysis_type.value,
                captured_at=request.captured_at,
                starts_at=request.captured_at,
                ends_at=None,
                status="DRAFT",
            )
            .on_conflict_do_nothing(index_elements=[Campaign.id])
            .returning(Campaign.id)
        ).scalar_one_or_none()
        self._session.flush()

        row = self._session.get(Campaign, request.campaign_id)
        if row is None:
            raise DBICampaignConflict("La campaña no quedó persistida.")

        immutable_exact = (
            row.tenant_ref == tenant_ref
            and row.organization_ref == organization_ref
            and row.farm_id == farm_id
            and row.plot_id == plot_id
            and row.analysis_type == request.analysis_type.value
            and row.captured_at == request.captured_at
        )
        if not immutable_exact:
            raise DBICampaignConflict(
                "campaign_id ya representa una campaña con identidad divergente."
            )
        return row, inserted_id is not None

    def get_campaign(
        self,
        *,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> Campaign | None:
        return self._session.execute(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.tenant_ref == tenant_ref,
                Campaign.organization_ref == organization_ref,
                Campaign.farm_id == farm_id,
                Campaign.plot_id == plot_id,
                Campaign.analysis_type.is_not(None),
            )
        ).scalar_one_or_none()

    def get_campaign_for_update(
        self,
        *,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> Campaign | None:
        return self._session.execute(
            select(Campaign)
            .where(
                Campaign.id == campaign_id,
                Campaign.tenant_ref == tenant_ref,
                Campaign.organization_ref == organization_ref,
                Campaign.farm_id == farm_id,
                Campaign.plot_id == plot_id,
                Campaign.analysis_type.is_not(None),
            )
            .with_for_update()
        ).scalar_one_or_none()

    def flush(self) -> None:
        self._session.flush()
