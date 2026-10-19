"""H14/2H-2D/3B: read-only forensic S3 inventory AFTER Campaign approval.

NOT a cleanup API. It never authorizes or revives any upload or grant.
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
from app.api.v1.dbi_scientific_raster_reconciliation import (
    State, classify_inventory,
)
from app.api.v1.dbi_scientific_raster_reservations import RasterRole, RasterIndex, _role_index
from app.api.v1.dbi_scientific_raster_session_preparations import (
    ScientificSessionPreparationPayload, _verified_intent,
)
from app.dbi.asset_multipart_provider import DBIMultipartProviderError
from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.campaigns.contracts import DBICampaignStatus
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

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-raster-forensic-inventory"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


class PostapprovalForensicReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["dbi-h14-postapproval-forensic-raster-inventory.v1"]
    campaign_id: UUID
    campaign_status: Literal["APPROVED", "PUBLISHED"]
    preparation_id: UUID
    asset_id: UUID
    role: RasterRole
    index: RasterIndex | None
    inventory_status: State
    incomplete_upload_count: int
    unexpected_upload_count: int
    recorded_upload_present: bool
    sql_start_recorded: bool
    manual_review_required: bool
    possible_incomplete_uploads_remaining: bool
    cleanup_performed: Literal[False]
    upload_access_blocked: Literal[True]
    ready_for_upload: Literal[False]
    provider_started_by_this_request: Literal[False]
    grants_issued: Literal[False]
    parts_received: Literal[False]
    file_received: Literal[False]
    raster_scientifically_validated: Literal[False]
    raster_institutionally_approved: Literal[False]
    raster_published: Literal[False]


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_INVENTORY_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Inventario institucional no disponible.")


def _locked_postapproval_campaign(
    session: Session, context: DBIAccessContext,
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
) -> Literal["APPROVED", "PUBLISHED"]:
    """A separate, read-only exception to the *preapproval-only* upload guards."""
    try:
        DBIAuthorizationPolicy.require_plot(
            context, tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, permission=DBIPermission.MANAGE,
        )
    except DBIAccessDenied as error:
        raise HTTPException(404, detail="Campaña no disponible.") from error
    row = DBICampaignRepository(session).get_campaign_for_update(
        campaign_id=campaign_id, tenant_ref=context.tenant_ref,
        organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
    )
    if (
        row is None or row.id != campaign_id
        or row.tenant_ref != context.tenant_ref
        or row.organization_ref != organization_ref
        or row.farm_id != farm_id or row.plot_id != plot_id
        or row.analysis_type != "multispectral"
    ):
        raise HTTPException(404, detail="Campaña no disponible.")
    if (
        row.status == DBICampaignStatus.APPROVED
        and row.approved_at is not None and row.published_at is None
    ):
        return "APPROVED"
    if (
        row.status == DBICampaignStatus.PUBLISHED
        and row.approved_at is not None and row.published_at is not None
    ):
        return "PUBLISHED"
    # No bypass for DRAFT/review/inconsistent approval timestamps.
    raise HTTPException(404, detail="Campaña no disponible.")


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake"
    "/private-raster-postapproval-forensic/{role}/{index}",
    response_model=PostapprovalForensicReceipt,
)
def inspect_postapproval_raster_orphans(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: ScientificSessionPreparationPayload,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> PostapprovalForensicReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    mapped = None if index == "_" else index
    try:
        # Exclusive Campaign lock first; never invoke the preapproval writer.
        campaign_status = _locked_postapproval_campaign(
            session, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        _role_index(role, mapped)
        raster = _verified_intent(
            request, context, organization_ref, farm_id, plot_id, campaign_id,
            role, mapped, payload,
        )
        value = SessionPreparationRequest(
            raster=raster, idempotency_key=payload.idempotency_key,
            requested_by=context.principal_ref,
        )
        ticket = DBIScientificSessionPreparationRepository(session).inspect(
            value, now=datetime.now(timezone.utc),
        )
        recorded = DBIScientificProviderStartRepository(session).get(value)
        provider = _provider(request)  # insists on the loopback adapter
        contract = _upload_contract(value, now=ticket.created_at)
        evidence = provider.inspect_incomplete_uploads(
            contract, expected_upload_ref=(
                recorded.provider_upload_ref if recorded is not None else None
            ),
        )
        state = classify_inventory(
            recorded.status if recorded is not None else None, evidence,
        )
        sql_start_recorded = recorded is not None
        # Forensic read-only: release all SQL row locks without a commit.
        session.rollback()
    except HTTPException:
        session.rollback()
        raise
    except DBIStorageNotFound as error:
        session.rollback()
        raise HTTPException(404, detail="Expediente privado no disponible.") from error
    except (ScientificSessionPreparationConflict, ScientificProviderStartConflict) as error:
        session.rollback()
        raise HTTPException(409, detail="Expediente institucional divergente.") from error
    except (DBIStorageError, DBIMultipartProviderError, SQLAlchemyError,
            ValueError, TypeError, KeyError) as error:
        session.rollback()
        raise HTTPException(503, detail="Inventario institucional no verificable.") from error
    manual = state not in {"no_remote_no_sql", "sql_aborted_no_remote"}
    return PostapprovalForensicReceipt(
        schema_version="dbi-h14-postapproval-forensic-raster-inventory.v1",
        campaign_id=campaign_id, campaign_status=campaign_status,
        preparation_id=_id(value.asset_id),
        asset_id=value.asset_id, role=role, index=mapped,
        inventory_status=state,
        incomplete_upload_count=evidence.incomplete_count,
        unexpected_upload_count=evidence.unexpected_count,
        recorded_upload_present=evidence.expected_present,
        sql_start_recorded=sql_start_recorded,
        manual_review_required=manual,
        possible_incomplete_uploads_remaining=evidence.incomplete_count > 0,
        cleanup_performed=False, upload_access_blocked=True,
        ready_for_upload=False, provider_started_by_this_request=False,
        grants_issued=False, parts_received=False, file_received=False,
        raster_scientifically_validated=False,
        raster_institutionally_approved=False, raster_published=False,
    )
