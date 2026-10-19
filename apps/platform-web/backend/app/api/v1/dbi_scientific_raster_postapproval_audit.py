"""H14/2H-2D/3C: institutional post-approval audit, strictly read-only."""
from __future__ import annotations

import os
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_raster_local_provider import _provider, _upload_contract
from app.api.v1.dbi_scientific_raster_preflight import _raster_address
from app.dbi.asset_multipart_provider import DBIMultipartProviderError
from app.api.v1.dbi_scientific_raster_reconciliation import State, classify_inventory
from app.api.v1.dbi_scientific_raster_reservations import (
    RasterRole, RasterIndex, _expected, _manifest, _read_slot,
    _role_index, _slot_address,
)
from app.dbi.authorization import DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission
from app.dbi.campaigns.repository import DBICampaignRepository
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.models.scientific_raster_assets import DBIScientificRasterInputAsset
from app.dbi.models.scientific_raster_bindings import DBIScientificRasterBinding
from app.dbi.models.scientific_raster_session_preparations import DBIScientificRasterSessionPreparation
from app.dbi.models.scientific_raster_provider_starts import DBIScientificRasterProviderStart
from app.dbi.scientific_raster_asset_repository import _asset_matches, _binding_matches, scientific_asset_id
from app.dbi.scientific_raster_binding_repository import ScientificRasterBindingIntent
from app.dbi.scientific_raster_provider_start_repository import _verify
from app.dbi.scientific_raster_session_repository import SessionPreparationRequest, _id
from app.dbi.storage_contracts import DBIStorageConflict, DBIStorageError, DBIStorageNotFound
from app.dbi.storage_policy import validate_sha256

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-postapproval-audit"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["dbi-h14-postapproval-audit-request.v1"]
    manifest_sha256: str
    reservation_sha256: str

    @field_validator("manifest_sha256", "reservation_sha256")
    @classmethod
    def canonical(cls, value: str) -> str:
        try:
            return validate_sha256(value)
        except DBIStorageConflict as exc:
            raise ValueError("SHA-256 inválido.") from exc


class AuditReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["dbi-h14-postapproval-audit-receipt.v1"]
    campaign_id: UUID
    asset_id: UUID
    role: RasterRole
    index: RasterIndex | None
    campaign_status: str
    approved_at_present: bool
    published_at_present: bool
    status: State
    incomplete_upload_count: int
    unexpected_upload_count: int
    recorded_upload_present: bool
    sql_start_recorded: bool
    target_tiff_object_present: bool
    manual_review_required: bool
    automatic_cleanup_performed: Literal[False]
    ready_for_upload: Literal[False]
    grants_issued: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    published_by_this_audit: Literal[False]


def _hidden() -> HTTPException:
    return HTTPException(404, detail="Auditoría postaprobación no disponible.")


def _enabled():
    if os.environ.get("DBI_SCIENTIFIC_POSTAPPROVAL_AUDIT_ENABLED") != "1" or (
        os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise _hidden()


def _lock_approved(session, context, org, farm, plot, campaign_id):
    try:
        for permission in (DBIPermission.MANAGE, DBIPermission.APPROVE_AGRONOMIC):
            DBIAuthorizationPolicy.require_plot(
                context, tenant_ref=context.tenant_ref,
                organization_ref=org, farm_id=farm, plot_id=plot, permission=permission,
            )
    except DBIAccessDenied as exc:
        raise _hidden() from exc
    row = DBICampaignRepository(session).get_campaign_for_update(
        campaign_id=campaign_id, tenant_ref=context.tenant_ref,
        organization_ref=org, farm_id=farm, plot_id=plot,
    )
    if row is None or not (
        row.id == campaign_id and row.tenant_ref == context.tenant_ref
        and row.organization_ref == org and row.farm_id == farm
        and row.plot_id == plot and row.analysis_type == "multispectral"
        and (row.status in {"APPROVED", "PUBLISHED"} or
             row.approved_at is not None or row.published_at is not None)
    ):
        raise _hidden()
    return row


def _locked(session, model, filters):
    return session.execute(select(model).where(*filters).with_for_update()).scalar_one_or_none()


def _sql_evidence(session, intent):
    aid = scientific_asset_id(intent)
    b = _locked(session, DBIScientificRasterBinding, [
        DBIScientificRasterBinding.id == intent.binding_id,
        DBIScientificRasterBinding.tenant_ref == intent.tenant_ref,
        DBIScientificRasterBinding.organization_ref == intent.organization_ref,
        DBIScientificRasterBinding.farm_id == intent.farm_id,
        DBIScientificRasterBinding.plot_id == intent.plot_id,
        DBIScientificRasterBinding.campaign_id == intent.campaign_id,
        DBIScientificRasterBinding.role == intent.role,
        DBIScientificRasterBinding.index_ref == intent.index_ref,
    ])
    if b is None or not _binding_matches(b, intent, aid) or (
        b.status != "asset_registered_pending_bytes" or b.asset_id != aid
    ):
        raise DBIStorageConflict("Binding SQL divergente.")
    a = _locked(session, DBIScientificRasterInputAsset, [
        DBIScientificRasterInputAsset.id == aid,
        DBIScientificRasterInputAsset.binding_id == intent.binding_id,
        DBIScientificRasterInputAsset.tenant_ref == intent.tenant_ref,
        DBIScientificRasterInputAsset.campaign_id == intent.campaign_id,
        DBIScientificRasterInputAsset.role == intent.role,
        DBIScientificRasterInputAsset.index_ref == intent.index_ref,
    ])
    if a is None or not _asset_matches(a, intent, aid):
        raise DBIStorageConflict("Asset SQL divergente.")
    t = _locked(session, DBIScientificRasterSessionPreparation, [
        DBIScientificRasterSessionPreparation.id == _id(aid),
        DBIScientificRasterSessionPreparation.asset_id == aid,
        DBIScientificRasterSessionPreparation.binding_id == intent.binding_id,
        DBIScientificRasterSessionPreparation.tenant_ref == intent.tenant_ref,
        DBIScientificRasterSessionPreparation.campaign_id == intent.campaign_id,
    ])
    if t is None or not (
        t.organization_ref == intent.organization_ref and t.farm_id == intent.farm_id
        and t.plot_id == intent.plot_id
        and t.manifest_sha256 == intent.manifest_sha256
        and t.reservation_sha256 == intent.slot_sha256
        and t.declared_sha256 == intent.declared_sha256
        and t.size_bytes == intent.declared_size_bytes
        and t.created_by_ref == intent.created_by_ref
        and t.status in {"prepared_no_provider", "cancelled_no_provider"}
        and (t.status == "cancelled_no_provider") == (t.cancelled_at is not None)
    ):
        raise DBIStorageConflict("Ticket SQL divergente.")
    p = _locked(session, DBIScientificRasterProviderStart, [
        DBIScientificRasterProviderStart.preparation_id == t.id,
        DBIScientificRasterProviderStart.tenant_ref == intent.tenant_ref,
        DBIScientificRasterProviderStart.campaign_id == intent.campaign_id,
        DBIScientificRasterProviderStart.asset_id == aid,
        DBIScientificRasterProviderStart.binding_id == intent.binding_id,
    ])
    proof = SessionPreparationRequest(
        raster=intent, idempotency_key="h14-postapproval-readonly-audit",
        requested_by=intent.created_by_ref,
    )
    if p is not None:
        _verify(p, proof)
    return aid, t, p, proof


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-postapproval-audit"
    "/{role}/{index}", response_model=AuditReceipt,
)
def audit_approved_raster(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: AuditRequest,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> AuditReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    idx = None if index == "_" else index
    try:
        campaign = _lock_approved(session, context, organization_ref, farm_id, plot_id, campaign_id)
        _role_index(role, idx)
        store, manifest, record = _manifest(
            request, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        if record.metadata.sha256 != payload.manifest_sha256:
            raise HTTPException(409, detail="Manifiesto divergente.")
        address = _slot_address(context, organization_ref, farm_id, plot_id, campaign_id, role, idx)
        slot, srecord = _read_slot(store, address)
        if srecord.metadata.sha256 != payload.reservation_sha256:
            raise HTTPException(409, detail="Reserva divergente.")
        expected = _expected(
            context=context, organization_ref=organization_ref, farm_id=farm_id,
            plot_id=plot_id, campaign_id=campaign_id,
            role=role, index=idx, manifest=manifest, record=record,
        )
        if slot != expected.model_copy(update={"reserved_by": slot.reserved_by}):
            raise DBIStorageConflict("Reserva no corresponde al manifiesto.")
        intent = ScientificRasterBindingIntent(
            tenant_ref=context.tenant_ref, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
            manifest_object_id=record.metadata.address.object_id,
            manifest_sha256=record.metadata.sha256,
            slot_object_id=srecord.metadata.address.object_id,
            slot_sha256=srecord.metadata.sha256,
            role=role, index_ref=idx or "_", target_object_id=slot.target_object_id,
            declared_size_bytes=slot.declared_size_bytes,
            declared_sha256=slot.declared_sha256, reserved_by=slot.reserved_by,
            created_by_ref=slot.reserved_by,
        )
        asset_id, ticket, start, proof = _sql_evidence(session, intent)
        inventory = _provider(request).inspect_incomplete_uploads(
            _upload_contract(proof, now=ticket.created_at),
            expected_upload_ref=start.provider_upload_ref if start is not None else None,
        )
        status = classify_inventory(start.status if start is not None else None, inventory)
        target = _raster_address(context, organization_ref, farm_id, plot_id, campaign_id, role, idx)
        if target.object_id != intent.target_object_id:
            raise DBIStorageConflict("Objeto TIFF destino divergente.")
        try:
            store.stat(target)
        except DBIStorageNotFound:
            target_present = False
        else:
            target_present = True
        session.rollback()
    except HTTPException:
        session.rollback()
        raise
    except DBIStorageNotFound as exc:
        session.rollback()
        raise _hidden() from exc
    except DBIStorageConflict as exc:
        session.rollback()
        raise HTTPException(409, detail="Evidencia científica inconsistente.") from exc
    except (DBIStorageError, DBIMultipartProviderError, SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
        session.rollback()
        raise HTTPException(503, detail="Auditoría S3/SQL no disponible.") from exc

    inconsistent_campaign = (
        campaign.status not in {"APPROVED", "PUBLISHED"}
        or (campaign.status in {"APPROVED", "PUBLISHED"} and campaign.approved_at is None)
        or (campaign.status == "PUBLISHED" and campaign.published_at is None)
    )
    manual = target_present or status not in {"no_remote_no_sql", "sql_aborted_no_remote"} or inconsistent_campaign
    return AuditReceipt(
        schema_version="dbi-h14-postapproval-audit-receipt.v1",
        campaign_id=campaign_id, asset_id=asset_id, role=role, index=idx,
        campaign_status=campaign.status,
        approved_at_present=campaign.approved_at is not None,
        published_at_present=campaign.published_at is not None,
        status=status,
        incomplete_upload_count=inventory.incomplete_count,
        unexpected_upload_count=inventory.unexpected_count,
        recorded_upload_present=inventory.expected_present,
        sql_start_recorded=start is not None,
        target_tiff_object_present=target_present,
        manual_review_required=manual,
        automatic_cleanup_performed=False, ready_for_upload=False,
        grants_issued=False, file_received=False, content_verified=False,
        published_by_this_audit=False,
    )
