"""Publicación del RGB para lectura HTTP de productores.

READ del lote no concede acceso automático al COG ready. Este predicate se
consulta desde las tres rutas públicas antes de tocar el almacenamiento.
No existe todavía un vínculo aprobado para seis rásteres de índice: el género
scientific queda deliberadamente fuera de esta frontera de lectura.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.dbi.models.agriculture import Campaign
from app.dbi.models.campaign_artifacts import DBICampaignArtifact
from app.dbi.models.raster_products import DBIRasterProduct


def is_published_rgb_raster(
    session: Session,
    *,
    tenant_ref: str,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    product_id: UUID,
) -> bool:
    """Sólo RGB real enlazado por fuente+SHA a ortofoto de Campaign PUBLISHED.

    Los parámetros provienen del contexto autenticado y la ruta validada, jamás
    de información de autorización aportada por el cliente. Ninguna coincidencia
    por fecha o nombre de fichero puede sustituir esta cadena de identidad.
    """
    statement = (
        select(DBIRasterProduct.id)
        .join(
            DBICampaignArtifact,
            and_(
                DBICampaignArtifact.source_kind == DBIRasterProduct.source_kind,
                DBICampaignArtifact.source_ref == DBIRasterProduct.source_ref,
                DBICampaignArtifact.sha256 == DBIRasterProduct.source_sha256,
            ),
        )
        .join(Campaign, Campaign.id == DBICampaignArtifact.campaign_id)
        .where(
            DBIRasterProduct.id == product_id,
            DBIRasterProduct.tenant_ref == tenant_ref,
            DBIRasterProduct.farm_id == farm_id,
            DBIRasterProduct.plot_id == plot_id,
            DBIRasterProduct.status == "ready",
            DBIRasterProduct.product_kind == "rgb_visual",
            DBICampaignArtifact.artifact_type == "orthophoto_source",
            DBICampaignArtifact.technical_status == "current",
            Campaign.tenant_ref == tenant_ref,
            Campaign.organization_ref == organization_ref,
            Campaign.farm_id == farm_id,
            Campaign.plot_id == plot_id,
            Campaign.analysis_type.is_not(None),
            Campaign.status == "PUBLISHED",
            Campaign.approved_at.is_not(None),
            Campaign.published_at.is_not(None),
        )
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none() == product_id
