"""Vínculo Campaign–INSPECT y eventos auditables, sin endpoint de publicación.

Tablas aditivas; ninguna fila se crea automáticamente para observaciones legacy.
La autorización por roles, orden de firma y publicación son responsabilidad de
servicios futuros y no se habilitan en este microhito.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKeyConstraint, Index,
    String, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBIInspectionCampaignLinkRecord(DBIBase):
    """Una versión observada INSPECT se atribuye a UNA Campaign MULTI exacta."""

    __tablename__ = "dbi_inspect_campaign_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["campaign_id", "tenant_ref", "organization_ref",
             "farm_id", "plot_id", "campaign_analysis_type"],
            ["dbi_campaigns.id", "dbi_campaigns.tenant_ref",
             "dbi_campaigns.organization_ref", "dbi_campaigns.farm_id",
             "dbi_campaigns.plot_id", "dbi_campaigns.analysis_type"],
            name="fk_dbi_inspect_links_campaign_scope_multi", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["observation_id", "tenant_ref", "organization_ref", "farm_id", "plot_id"],
            ["dbi_field_observations.id", "dbi_field_observations.tenant_ref",
             "dbi_field_observations.organization_ref", "dbi_field_observations.farm_id",
             "dbi_field_observations.plot_id"],
            name="fk_dbi_inspect_links_observation_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["observation_id", "observation_version_id"],
            ["dbi_field_observation_versions.observation_id",
             "dbi_field_observation_versions.id"],
            name="fk_dbi_inspect_links_version_identity", ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "observation_version_id", name="uq_dbi_inspect_links_one_campaign_per_version",
        ),
        CheckConstraint(
            "campaign_analysis_type = 'multispectral'",
            name="ck_dbi_inspect_links_multispectral_only",
        ),
        CheckConstraint(
            "length(tenant_ref) BETWEEN 1 AND 128 "
            "AND btrim(tenant_ref) = tenant_ref AND tenant_ref NOT LIKE '%*%' "
            "AND length(organization_ref) BETWEEN 1 AND 128 "
            "AND btrim(organization_ref) = organization_ref AND organization_ref NOT LIKE '%*%' "
            "AND length(linked_by_ref) BETWEEN 1 AND 128 "
            "AND btrim(linked_by_ref) = linked_by_ref AND linked_by_ref NOT LIKE '%*%'",
            name="ck_dbi_inspect_links_canonical_refs",
        ),
        Index("ix_dbi_inspect_links_campaign", "campaign_id"),
        Index("ix_dbi_inspect_links_observation", "observation_id"),
        Index("ix_dbi_inspect_links_scope", "tenant_ref", "organization_ref", "farm_id", "plot_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    plot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    campaign_analysis_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="multispectral",
    )
    observation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    observation_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    linked_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )


class DBIInspectionApprovalEventRecord(DBIBase):
    """Evento de firma separado; sólo una firma por etapa para cada vínculo."""

    __tablename__ = "dbi_inspect_approval_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["link_id"], ["dbi_inspect_campaign_links.id"],
            name="fk_dbi_inspect_approval_events_link", ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "link_id", "event_kind", name="uq_dbi_inspect_approval_event_step",
        ),
        CheckConstraint(
            "event_kind IN ('technical_validated', 'administrative_authorized')",
            name="ck_dbi_inspect_approval_event_kind",
        ),
        CheckConstraint(
            "length(actor_ref) BETWEEN 1 AND 128 "
            "AND btrim(actor_ref) = actor_ref AND actor_ref NOT LIKE '%*%'",
            name="ck_dbi_inspect_approval_actor",
        ),
        Index("ix_dbi_inspect_approval_events_link", "link_id"),
        Index("ix_dbi_inspect_approval_events_actor", "actor_ref"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    link_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    event_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
