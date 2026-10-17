"""Ficha PDF de evidencia PUBLICADA por Campaign; nunca expone originales privados.

No sustituye al informe técnico íntegro de densidad ni la firma institucional.
Toda cifra se obtiene de registros del mismo tenant/lote/Campaign y de extracción
multiespectral cuya procedencia científica fue verificada. La falta de evidencia
se representa como ausencia de datos, no como un resultado favorable.
"""
from __future__ import annotations

from io import BytesIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.models.agriculture import Campaign
from app.dbi.models.portal_vectors import DBIPortalVectorLayer
from app.dbi.multispectral.repository import DBIMultispectralExtractionRepository
from app.api.v1.dbi_multispectral import _checked_multispectral_row

router = APIRouter(prefix="/dbi", tags=["dbi-client-reports"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]

INDICES = (
    ("ndvi", "NDVI"), ("ndre", "NDRE"), ("gndvi", "GNDVI"),
    ("evi2", "EVI2"), ("ci_red_edge", "CI Red Edge"), ("ci_green", "CI Green"),
)


def _unavailable() -> HTTPException:
    return HTTPException(status_code=404, detail="Informe de campaña publicada no disponible.")


def _fmt(value: float | None) -> str:
    if value is None:
        return "Sin píxeles válidos"
    return f"{value:.4f}"


def _create_pdf(*, campaign: Campaign, layer_counts: list[tuple[str, int, int]],
                index_values: dict[str, tuple[float | None, int, int]],
                evidence_scope: str) -> bytes:
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream, pagesize=A4, topMargin=46, bottomMargin=50,
        leftMargin=46, rightMargin=46,
        title="DALGORO | Evidencias publicadas", author="DALGORO Banana Intelligence",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DALGOROTitle", parent=styles["Heading1"], textColor=colors.HexColor("#17383b"),
        fontSize=17, leading=21, spaceAfter=12,
    )
    body = ParagraphStyle("DALGOROBody", parent=styles["BodyText"], leading=15, alignment=TA_LEFT)
    story = [
        Paragraph("DALGORO Banana Intelligence", title_style),
        Paragraph("Ficha de evidencias publicadas del levantamiento", styles["Heading2"]),
        Paragraph("Este documento contiene datos almacenados y autorizados. No es diagnóstico "
                  "de enfermedad, estimación de rendimiento ni prescripción de tratamiento.", body),
        Spacer(1, 12),
        Paragraph(f"Tipo de análisis: {campaign.analysis_type or 'No informado'}", body),
        Paragraph(f"Captura registrada (UTC): {campaign.captured_at.isoformat() if campaign.captured_at else 'No disponible'}", body),
        Paragraph(f"Aprobación registrada (UTC): {campaign.approved_at.isoformat()}", body),
        Paragraph(f"Publicación registrada (UTC): {campaign.published_at.isoformat()}", body),
        Paragraph(f"Identificador de trazabilidad: {campaign.id}", body),
        Spacer(1, 14),
        Paragraph("Seis índices espectrales", styles["Heading2"]),
        Paragraph(evidence_scope, body),
    ]
    table_data = [["Índice", "Mediana", "Píxeles válidos"]]
    for ref, label in INDICES:
        item = index_values.get(ref)
        table_data.append([
            label,
            _fmt(item[0]) if item else "No disponible",
            f"{item[1]} de {item[2]}" if item else "No disponible",
        ])
    index_table = Table(table_data, colWidths=[140, 165, 170], repeatRows=1)
    index_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6efeb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17383b")),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#cddbd4")),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([Spacer(1, 9), index_table, Spacer(1, 15),
                  Paragraph("Cartografía de población y otras capas GIS", styles["Heading2"])])
    if layer_counts:
        for kind, layers, features in layer_counts:
            story.append(Paragraph(
                f"{kind}: {layers} capa(s) · {features} elementos geográficos registrados.", body))
    else:
        story.append(Paragraph("No hay capas GIS registradas para esta Campaign.", body))
    story.extend([
        Spacer(1, 12),
        Paragraph("Los conteos de elementos GIS no equivalen automáticamente a plantas "
                  "válidas, hectáreas, densidad por hectárea ni sanidad vegetal.", body),
        Paragraph("Los índices se resumen por muestra y no representan mapas temáticos "
                  "ni pueden compararse entre vuelos sin verificar calibración y soporte espacial.", body),
    ])
    doc.build(story)
    return stream.getvalue()


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/published-evidence.pdf",
    responses={200: {"content": {"application/pdf": {}}}, 404: {"description": "No publicado"}},
)
def published_evidence_pdf(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    session: SessionDep, context: AccessDep,
) -> Response:
    try:
        DBIAuthorizationPolicy.require_plot(
            context, tenant_ref=context.tenant_ref,
            organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
            permission=DBIPermission.READ,
        )
    except DBIAccessDenied as error:
        raise _unavailable() from error

    campaign = session.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_ref == context.tenant_ref,
            Campaign.organization_ref == organization_ref,
            Campaign.farm_id == farm_id, Campaign.plot_id == plot_id,
            Campaign.analysis_type.in_(("density", "multispectral")),
            Campaign.status == "PUBLISHED",
            Campaign.approved_at.is_not(None),
            Campaign.published_at.is_not(None),
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise _unavailable()

    layer_counts = [
        (str(kind), int(count), int(features))
        for kind, count, features in session.execute(
            select(
                DBIPortalVectorLayer.layer_kind,
                func.count(DBIPortalVectorLayer.id),
                func.sum(DBIPortalVectorLayer.feature_count),
            ).where(
                DBIPortalVectorLayer.tenant_ref == context.tenant_ref,
                DBIPortalVectorLayer.organization_ref == organization_ref,
                DBIPortalVectorLayer.farm_id == farm_id,
                DBIPortalVectorLayer.plot_id == plot_id,
                DBIPortalVectorLayer.campaign_id == campaign_id,
            ).group_by(DBIPortalVectorLayer.layer_kind)
        ).all()
    ]
    values: dict[str, tuple[float | None, int, int]] = {}
    evidence_scope = "Sin extracción multiespectral verificada entre las últimas 20 muestras del lote."
    if campaign.analysis_type == "multispectral":
        repository = DBIMultispectralExtractionRepository(session)
        rows = repository.list_scoped(
            tenant_ref=context.tenant_ref, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id,
        )
        provenance = repository.campaign_provenance_by_extraction_scoped(
            extraction_ids=[row.id for row in rows],
            tenant_ref=context.tenant_ref, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id,
        )
        matching = [row for row in rows if provenance.get(row.id, (None,))[0] == campaign_id]
        if matching:
            selected = matching[0]
            observed = repository.observed_at_by_extraction_scoped(
                extraction_ids=[selected.id],
                tenant_ref=context.tenant_ref, organization_ref=organization_ref,
                farm_id=farm_id, plot_id=plot_id,
            ).get(selected.id)
            result = _checked_multispectral_row(
                selected, observed, provenance[selected.id], context,
                organization_ref, farm_id, plot_id,
            )
            evidence_scope = ("Mediana de la última muestra de procedencia verificada "
                              "de esta Campaign entre las 20 extracciones recientes del lote; "
                              "no representa necesariamente la finca completa.")
            for item in result.payload.summaries:
                if item.variable_kind == "index" and item.variable_ref in dict(INDICES):
                    values[item.variable_ref] = (
                        item.median, item.valid_count, item.selected_count,
                    )

    pdf = _create_pdf(campaign=campaign, layer_counts=layer_counts,
                      index_values=values, evidence_scope=evidence_scope)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="dbi-evidencias-publicadas.pdf"',
                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
