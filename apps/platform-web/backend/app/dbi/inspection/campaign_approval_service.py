"""Servicio interno transaccional Campaign–INSPECT con firmas independientes.

Sin rutas FastAPI ni publicación al cliente. El llamador es responsable de
commit/rollback y de resolver memberships DALGORO; la consulta cliente sigue
bloqueada por el guard READ+WRITE de INSPECT.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.inspection.dual_approval import (
    DBIInspectionApprovalConflict,
    DBIInspectionApprovalState,
)
from app.dbi.models.agriculture import Campaign
from app.dbi.models.inspection import (
    DBIFieldObservationRecord,
    DBIFieldObservationVersionRecord,
)
from app.dbi.models.inspection_campaign import (
    DBIInspectionApprovalEventRecord,
    DBIInspectionCampaignLinkRecord,
)
from app.dbi.models.multispectral import DBIMultispectralExtractionRecord
from app.dbi.multispectral.repository import DBIMultispectralExtractionRepository


class DBIInspectionCampaignApprovalService:
    """Sólo callable interno, sin endpoints ni permisos nuevos."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBIInspectionApprovalConflict("Se requiere una sesión DBI válida.")
        self._session = session

    @staticmethod
    def _scope(
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        permission: DBIPermission,
    ) -> None:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=permission,
        )

    def _locked_current(
        self,
        *,
        context: DBIAccessContext,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        observation_id: UUID,
        expected_version_id: UUID,
    ) -> DBIFieldObservationVersionRecord:
        # Mismo lock que correct_observation: impide firmar una versión
        # mientras otro técnico crea su sucesora concurrentemente.
        observation = self._session.execute(
            select(DBIFieldObservationRecord).where(
                DBIFieldObservationRecord.id == observation_id,
                DBIFieldObservationRecord.tenant_ref == context.tenant_ref,
                DBIFieldObservationRecord.organization_ref == organization_ref,
                DBIFieldObservationRecord.farm_id == farm_id,
                DBIFieldObservationRecord.plot_id == plot_id,
            ).with_for_update()
        ).scalar_one_or_none()
        if observation is None:
            raise DBIInspectionApprovalConflict("INSPECT no disponible en este lote.")

        latest = self._session.execute(
            select(DBIFieldObservationVersionRecord).where(
                DBIFieldObservationVersionRecord.observation_id == observation_id
            ).order_by(
                DBIFieldObservationVersionRecord.version.desc()
            ).limit(1)
        ).scalar_one_or_none()
        if (
            latest is None
            or latest.id != expected_version_id
            or latest.evidence_kind != "observed"
        ):
            raise DBIInspectionApprovalConflict(
                "La versión INSPECT no es la vigente y observada."
            )
        return latest

    def _campaign(
        self,
        *,
        context: DBIAccessContext,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        campaign_id: UUID,
    ) -> Campaign:
        campaign = self._session.execute(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.tenant_ref == context.tenant_ref,
                Campaign.organization_ref == organization_ref,
                Campaign.farm_id == farm_id,
                Campaign.plot_id == plot_id,
                Campaign.analysis_type == "multispectral",
                Campaign.captured_at.is_not(None),
            )
        ).scalar_one_or_none()
        if campaign is None:
            raise DBIInspectionApprovalConflict(
                "Campaign multiespectral no disponible en este lote."
            )
        return campaign

    def _state(self, link: DBIInspectionCampaignLinkRecord) -> DBIInspectionApprovalState:
        events = self._session.execute(
            select(DBIInspectionApprovalEventRecord).where(
                DBIInspectionApprovalEventRecord.link_id == link.id
            )
        ).scalars().all()
        by_kind: dict[str, DBIInspectionApprovalEventRecord] = {}
        for event in events:
            if event.event_kind in by_kind or event.event_kind not in {
                "technical_validated", "administrative_authorized"
            }:
                raise DBIInspectionApprovalConflict("Historial de firmas inválido.")
            by_kind[event.event_kind] = event
        tech = by_kind.get("technical_validated")
        admin = by_kind.get("administrative_authorized")
        # El contrato puro rechaza automáticamente firmas aisladas o repetidas,
        # fechas sin timezone y firma duplicada por un mismo principal.
        return DBIInspectionApprovalState(
            tenant_ref=link.tenant_ref,
            organization_ref=link.organization_ref,
            farm_id=link.farm_id,
            plot_id=link.plot_id,
            campaign_id=link.campaign_id,
            observation_id=link.observation_id,
            observation_version_id=link.observation_version_id,
            technical_by=tech.actor_ref if tech else None,
            technical_at=tech.decided_at if tech else None,
            administrative_by=admin.actor_ref if admin else None,
            administrative_at=admin.decided_at if admin else None,
        )

    def _locked_link(
        self,
        *,
        context: DBIAccessContext,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        link_id: UUID,
    ) -> DBIInspectionCampaignLinkRecord:
        # Recupera identidad del vínculo para bloquear en el orden constante:
        # observación primero, después link.
        lookup = self._session.execute(
            select(
                DBIInspectionCampaignLinkRecord.observation_id,
                DBIInspectionCampaignLinkRecord.observation_version_id,
            ).where(
                DBIInspectionCampaignLinkRecord.id == link_id,
                DBIInspectionCampaignLinkRecord.tenant_ref == context.tenant_ref,
                DBIInspectionCampaignLinkRecord.organization_ref == organization_ref,
                DBIInspectionCampaignLinkRecord.farm_id == farm_id,
                DBIInspectionCampaignLinkRecord.plot_id == plot_id,
            )
        ).one_or_none()
        if lookup is None:
            raise DBIInspectionApprovalConflict("Vínculo INSPECT no disponible.")
        observation_id, version_id = lookup
        self._locked_current(
            context=context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            observation_id=observation_id,
            expected_version_id=version_id,
        )
        link = self._session.execute(
            select(DBIInspectionCampaignLinkRecord).where(
                DBIInspectionCampaignLinkRecord.id == link_id,
                DBIInspectionCampaignLinkRecord.tenant_ref == context.tenant_ref,
                DBIInspectionCampaignLinkRecord.organization_ref == organization_ref,
                DBIInspectionCampaignLinkRecord.farm_id == farm_id,
                DBIInspectionCampaignLinkRecord.plot_id == plot_id,
                DBIInspectionCampaignLinkRecord.observation_id == observation_id,
                DBIInspectionCampaignLinkRecord.observation_version_id == version_id,
            ).with_for_update()
        ).scalar_one_or_none()
        if link is None:
            raise DBIInspectionApprovalConflict("Vínculo INSPECT cambió de identidad.")
        return link

    def register_link(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        campaign_id: UUID,
        observation_id: UUID,
        observation_version_id: UUID,
    ) -> DBIInspectionCampaignLinkRecord:
        """Vincula por identidad explícita; jamás por fecha, GPS o cercanía."""
        self._scope(
            context, organization_ref=organization_ref, farm_id=farm_id,
            plot_id=plot_id, permission=DBIPermission.WRITE,
        )
        self._locked_current(
            context=context, organization_ref=organization_ref, farm_id=farm_id,
            plot_id=plot_id, observation_id=observation_id,
            expected_version_id=observation_version_id,
        )
        self._campaign(
            context=context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
        )
        # Una observación corregida no puede cambiar silenciosamente de Campaign;
        # el vínculo anterior permanece para auditoría, sin heredarse la firma.
        prior_links = self._session.execute(
            select(DBIInspectionCampaignLinkRecord).where(
                DBIInspectionCampaignLinkRecord.observation_id == observation_id
            )
        ).scalars().all()
        for previous in prior_links:
            if previous.campaign_id != campaign_id:
                raise DBIInspectionApprovalConflict(
                    "INSPECT ya pertenece a otra Campaign; requiere revisión formal."
                )
            if previous.observation_version_id == observation_version_id:
                return previous  # replay inmutable sin nueva firma
        link = DBIInspectionCampaignLinkRecord(
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            campaign_id=campaign_id,
            campaign_analysis_type="multispectral",
            observation_id=observation_id,
            observation_version_id=observation_version_id,
            linked_by_ref=context.principal_ref,
        )
        self._session.add(link)
        self._session.flush()
        return link

    def _verified_scientific_chain(self, link: DBIInspectionCampaignLinkRecord) -> bool:
        """Verifica procedencia REAL por extracción, nunca un bool del navegador."""
        candidates = self._session.execute(
            select(DBIMultispectralExtractionRecord.id).where(
                DBIMultispectralExtractionRecord.tenant_ref == link.tenant_ref,
                DBIMultispectralExtractionRecord.organization_ref == link.organization_ref,
                DBIMultispectralExtractionRecord.farm_id == link.farm_id,
                DBIMultispectralExtractionRecord.plot_id == link.plot_id,
                DBIMultispectralExtractionRecord.observation_id == link.observation_id,
                DBIMultispectralExtractionRecord.observation_version_id
                == link.observation_version_id,
            ).order_by(
                DBIMultispectralExtractionRecord.created_at,
                DBIMultispectralExtractionRecord.id,
            ).limit(20)
        ).scalars().all()
        if not candidates:
            return False
        provenance = DBIMultispectralExtractionRepository(
            self._session
        ).campaign_provenance_by_extraction_scoped(
            extraction_ids=list(candidates),
            tenant_ref=link.tenant_ref,
            organization_ref=link.organization_ref,
            farm_id=link.farm_id,
            plot_id=link.plot_id,
        )
        return any(pair[0] == link.campaign_id for pair in provenance.values())

    def validate_technical(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        link_id: UUID,
    ) -> DBIInspectionApprovalState:
        """Añade evento técnico una sola vez bajo lock; no hace commit."""
        self._scope(
            context, organization_ref=organization_ref, farm_id=farm_id,
            plot_id=plot_id, permission=DBIPermission.WRITE,
        )
        link = self._locked_link(
            context=context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, link_id=link_id,
        )
        now = datetime.now(timezone.utc)
        updated = self._state(link).validate_technical(
            context, at=now, current_version_id=link.observation_version_id
        )
        self._session.add(DBIInspectionApprovalEventRecord(
            link_id=link.id,
            event_kind="technical_validated",
            actor_ref=context.principal_ref,
            decided_at=now,
        ))
        self._session.flush()
        return updated

    def authorize_administrative(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        link_id: UUID,
    ) -> DBIInspectionApprovalState:
        """Firma distinta tras verificar procedencia científica real en servidor."""
        for permission in (DBIPermission.APPROVE_AGRONOMIC, DBIPermission.MANAGE):
            self._scope(
                context, organization_ref=organization_ref,
                farm_id=farm_id, plot_id=plot_id, permission=permission,
            )
        link = self._locked_link(
            context=context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, link_id=link_id,
        )
        state = self._state(link)
        # Comprobar primero las firmas; nunca consultar el material científico
        # para un vínculo sin revisión técnica o para la misma identidad.
        if state.stage != "technical_validated" or state.technical_by == context.principal_ref:
            raise DBIInspectionApprovalConflict(
                "Falta validación técnica independiente."
            )
        now = datetime.now(timezone.utc)
        updated = state.approve_administrative(
            context, at=now, current_version_id=link.observation_version_id,
            campaign_link_verified=self._verified_scientific_chain(link),
        )
        self._session.add(DBIInspectionApprovalEventRecord(
            link_id=link.id,
            event_kind="administrative_authorized",
            actor_ref=context.principal_ref,
            decided_at=now,
        ))
        self._session.flush()
        return updated

    # Deliberadamente SIN endpoint cliente, publish(), client_read() ni modelo ML.
