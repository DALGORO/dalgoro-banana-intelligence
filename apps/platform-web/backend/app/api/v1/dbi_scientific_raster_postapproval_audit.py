"""H14/2H-2D/3C: diagnosticar cargas remotas tras aprobación, SIN modificarlas.

Este expediente permite SOLO inventariar residuos del S3 local, bajo MANAGE
del operador reservador y bloqueo SQL de Campaign APPROVED/PUBLISHED.
No amplía las rutas anteriores que siguen cerradas tras aprobación.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_raster_local_provider import _provider, _upload_contract
from app.api.v1.dbi_scientific_raster_reconciliation import classify_inventory, State
from app.api.v1.dbi_scientific_raster_session_preparations import (
    ScientificSessionPreparationPayload, _verified_intent,
)
from app.api.v1.dbi_scientific_raster_reservations import RasterRole, RasterIndex, _role_index
from app.dbi.asset_multipart_provider import DBIMultipartProviderError
from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.campaigns.repository import DBICampaignRepository
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_raster_provider_start_repository import (
    DBIScientificProviderStartRepository, ScientificProviderStartConflict,
)
from app.dbi.scientific_raster_session_repository import (
    DBIScientificSessionPreparationRepository, ScientificSessionPreparationConflict,
    SessionPreparationRequest, _id,
)
from app.dbi.storage_contracts import DBIStorageError, DBIStorageNotFound

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-raster-postapproval-audit"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


class PostApprovalAuditReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["dbi-h14-postapproval-readonly-upload-audit.v1"]
    campaign_id: UUID
    campaign_status: Literal["APPROVED", "PUBLISHED"]
    preparation_id: UUID
    asset_id: UUID
    role: RasterRole
    index: RasterIndex | None
    reconciliation_status: State
    incomplete_upload_count: int
    unexpected_upload_count: int
    recorded_upload_present: bool
    sql_start_recorded: bool
    remote_cleanup_required: bool
    manual_review_required: bool
    ready_for_upload: Literal[False]
    grants_issued: Literal[False]
    parts_received: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    asset_institutionally_approved: Literal[False]
    asset_published: Literal[False]
    cleanup_performed: Literal[False]


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Auditoría postaprobación no disponible.")


def _locked_approved_campaign(
    session: Session, context: DBIAccessContext,
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
) -> Literal["APPROVED", "PUBLISHED"]:
    """Never reuse the preapproval _locked_campaign gate for this narrow audit."""
    try:
        DBIAuthorizationPolicy.require_plot(
            context, tenant_ref=context.tenant_ref,
            organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
            permission=DBIPermission.MANAGE,
        )
    except DBIAccessDenied as error:
        raise HTTPException(404, detail="Campaign no disponible.") from error
    campaign = DBICampaignRepository(session).get_campaign_for_update(
        campaign_id=campaign_id, tenant_ref=context.tenant_ref,
        organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
    )
    if (
        campaign is None
        or campaign.id != campaign_id
        or campaign.tenant_ref != context.tenant_ref
        or campaign.organization_ref != organization_ref
        or campaign.farm_id != farm_id
        or campaign.plot_id != plot_id
        or campaign.analysis_type != "multispectral"
        or campaign.status not in {"APPROVED", "PUBLISHED"}
        or campaign.approved_at is None
        or (campaign.status == "APPROVED" and campaign.published_at is not None)
        or (campaign.status == "PUBLISHED" and campaign.published_at is None)
    ):
        raise HTTPException(404, detail="Campaign no disponible.")
    return campaign.status


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-postapproval-audit"
    "/{role}/{index}",
    response_model=PostApprovalAuditReceipt,
)
def audit_postapproval_incomplete_raster_uploads(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: ScientificSessionPreparationPayload,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> PostApprovalAuditReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    mapped = None if index == "_" else index
    try:
        # Lock exact Campaign row. Approved is allowed ONLY for this read-only
        # diagnostic; start/inspect/abort/grants from earlier routes stay blocked.
        campaign_status = _locked_approved_campaign(
            session, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        _role_index(role, mapped)
        raster = _verified_intent(
            request, context, organization_ref, farm_id, plot_id,
            campaign_id, role, mapped, payload,
        )
        value = SessionPreparationRequest(
            raster=raster, idempotency_key=payload.idempotency_key,
            requested_by=context.principal_ref,
        )
        ticket = DBIScientificSessionPreparationRepository(session).inspect(
            value, now=datetime.now(timezone.utc),
        )
        recorded = DBIScientificProviderStartRepository(session).get(value)
        provider = _provider(request)  # DBIS3MultipartAdapter, strictly loopback
        contract = _upload_contract(value, now=ticket.created_at)
        evidence = provider.inspect_incomplete_uploads(
            contract,
            expected_upload_ref=(
                recorded.provider_upload_ref if recorded is not None else None
            ),
        )
        status = classify_inventory(
            recorded.status if recorded is not None else None, evidence,
        )
        # Read-only transaction, release Campaign/Asset/ticket/provider row locks.
        session.rollback()
    except HTTPException:
        session.rollback()
        raise
    except DBIStorageNotFound as error:
        session.rollback()
        raise HTTPException(404, detail="Expediente científico privado incompleto.") from error
    except (ScientificSessionPreparationConflict, ScientificProviderStartConflict) as error:
        session.rollback()
        raise HTTPException(409, detail="Auditoría bloqueada por evidencia divergente.") from error
    except (DBIStorageError, DBIMultipartProviderError, SQLAlchemyError,
            ValueError, TypeError, KeyError) as error:
        session.rollback()
        raise HTTPException(503, detail="No se pudo auditar la carga S3 local.") from error
    return PostApprovalAuditReceipt(
        schema_version="dbi-h14-postapproval-readonly-upload-audit.v1",
        campaign_id=campaign_id, campaign_status=campaign_status,
        preparation_id=_id(value.asset_id), asset_id=value.asset_id,
        role=role, index=mapped,
        reconciliation_status=status,
        incomplete_upload_count=evidence.incomplete_count,
        unexpected_upload_count=evidence.unexpected_count,
        recorded_upload_present=evidence.expected_present,
        sql_start_recorded=recorded is not None,
        remote_cleanup_required=evidence.incomplete_count > 0,
        manual_review_required=status not in {"no_remote_no_sql", "sql_aborted_no_remote"},
        ready_for_upload=False, grants_issued=False,
        parts_received=False, file_received=False, content_verified=False,
        asset_institutionally_approved=False, asset_published=False,
        cleanup_performed=False,
    )
