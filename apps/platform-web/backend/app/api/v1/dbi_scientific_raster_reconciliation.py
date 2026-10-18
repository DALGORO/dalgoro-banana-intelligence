"""H14/2H-2D/3A: reconcile incomplete local S3 uploads with scoped SQL, READ ONLY.

No permissions, URLs, multipart initiation, abortion or server-side cleanup.
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
from app.api.v1.dbi_scientific_raster_session_preparations import (
    ScientificSessionPreparationPayload, _verified_intent,
)
from app.api.v1.dbi_scientific_raster_sql_bindings import _locked_campaign
from app.api.v1.dbi_scientific_raster_reservations import RasterRole, RasterIndex, _role_index
from app.dbi.asset_multipart_provider import DBIMultipartProviderError
from app.dbi.asset_multipart_s3 import DBIS3IncompleteUploadInventory
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_raster_provider_start_repository import (
    DBIScientificProviderStartRepository, ScientificProviderStartConflict,
)
from app.dbi.scientific_raster_session_repository import (
    DBIScientificSessionPreparationRepository, ScientificSessionPreparationConflict,
    SessionPreparationRequest, _id,
)
from app.dbi.storage_contracts import DBIStorageError, DBIStorageNotFound

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-raster-reconciliation"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
State = Literal[
    "no_remote_no_sql", "remote_orphan_without_sql",
    "active_exact_single_upload", "sql_active_remote_missing",
    "sql_active_remote_replaced", "sql_active_remote_extra",
    "sql_aborted_no_remote", "sql_aborted_remote_remains",
]


class ReconciliationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["dbi-h14-raster-readonly-reconciliation.v1"]
    campaign_id: UUID
    preparation_id: UUID
    asset_id: UUID
    role: RasterRole
    index: RasterIndex | None
    status: State
    incomplete_upload_count: int
    unexpected_upload_count: int
    recorded_upload_present: bool
    sql_start_recorded: bool
    manual_review_required: bool
    ready_for_upload: Literal[False]
    grants_issued: Literal[False]
    parts_received: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_RASTER_RECONCILIATION_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Conciliación local no disponible.")


def classify_inventory(
    status: str | None, evidence: DBIS3IncompleteUploadInventory,
) -> State:
    """Pure classification. Never infer completed TIFF or verified data."""
    if not isinstance(evidence, DBIS3IncompleteUploadInventory):
        raise ScientificProviderStartConflict("Inventario S3 no canónico.")
    if (
        type(evidence.incomplete_count) is not int or evidence.incomplete_count < 0
        or type(evidence.unexpected_count) is not int
        or not 0 <= evidence.unexpected_count <= evidence.incomplete_count
        or type(evidence.expected_present) is not bool
        or evidence.unexpected_count != (
            evidence.incomplete_count - int(evidence.expected_present)
        )
    ):
        raise ScientificProviderStartConflict("Contadores S3 no canónicos.")
    if status is None:
        if evidence.expected_present or evidence.unexpected_count != evidence.incomplete_count:
            raise ScientificProviderStartConflict("S3 devolvió ref sin registro SQL.")
        return "no_remote_no_sql" if evidence.incomplete_count == 0 else "remote_orphan_without_sql"
    if status == "aborted_no_grants":
        return "sql_aborted_no_remote" if evidence.incomplete_count == 0 else "sql_aborted_remote_remains"
    if status != "initiated_no_grants":
        raise ScientificProviderStartConflict("Estado SQL de proveedor desconocido.")
    if evidence.expected_present:
        return "active_exact_single_upload" if evidence.unexpected_count == 0 else "sql_active_remote_extra"
    return "sql_active_remote_missing" if evidence.incomplete_count == 0 else "sql_active_remote_replaced"


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-local-reconciliation"
    "/{role}/{index}",
    response_model=ReconciliationReceipt,
)
def reconcile_private_raster_s3(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: ScientificSessionPreparationPayload,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> ReconciliationReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    mapped = None if index == "_" else index
    try:
        _locked_campaign(
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
        # Recheck immutable SQL ticket and lock exact Campaign, Asset, Binding,
        # ticket, provider ledger before reading S3 incomplete uploads.
        ticket = DBIScientificSessionPreparationRepository(session).inspect(
            value, now=datetime.now(timezone.utc),
        )
        recorded = DBIScientificProviderStartRepository(session).get(value)
        provider = _provider(request)
        contract = _upload_contract(value, now=ticket.created_at)
        evidence = provider.inspect_incomplete_uploads(
            contract, expected_upload_ref=(
                recorded.provider_upload_ref if recorded is not None else None
            ),
        )
        status = classify_inventory(
            recorded.status if recorded is not None else None, evidence,
        )
        session.rollback()  # release read-only row locks, NEVER write
    except HTTPException:
        session.rollback()
        raise
    except DBIStorageNotFound as error:
        session.rollback()
        raise HTTPException(404, detail="Expediente científico privado incompleto.") from error
    except (ScientificSessionPreparationConflict, ScientificProviderStartConflict) as error:
        session.rollback()
        raise HTTPException(409, detail="Conciliación bloqueada por evidencia divergente.") from error
    except (DBIStorageError, DBIMultipartProviderError, SQLAlchemyError,
            ValueError, TypeError, KeyError) as error:
        session.rollback()
        raise HTTPException(503, detail="No se pudo conciliar S3 con el estado SQL.") from error
    manual = status not in {
        "no_remote_no_sql", "active_exact_single_upload", "sql_aborted_no_remote",
    }
    return ReconciliationReceipt(
        schema_version="dbi-h14-raster-readonly-reconciliation.v1",
        campaign_id=campaign_id, preparation_id=_id(value.asset_id),
        asset_id=value.asset_id, role=role, index=mapped,
        status=status, incomplete_upload_count=evidence.incomplete_count,
        unexpected_upload_count=evidence.unexpected_count,
        recorded_upload_present=evidence.expected_present,
        sql_start_recorded=recorded is not None,
        manual_review_required=manual,
        ready_for_upload=False, grants_issued=False, parts_received=False,
        file_received=False, content_verified=False,
        institutional_approved=False, published=False,
    )
