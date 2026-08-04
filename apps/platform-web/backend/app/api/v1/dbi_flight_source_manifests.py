"""API autorizada y paginada para manifiestos de fuentes de vuelo."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.flight_source_manifest import (
    DBIFlightSourceEntryIntent,
    DBIFlightSourceManifestError,
    DBIFlightSourceManifestPage,
    DBIFlightSourceManifestRecord,
    DBIFlightSourceManifestService,
    DBIFlightSourceManifestUnavailable,
)
from app.dbi.flight_source_manifest_api_schemas import (
    DBIFlightSourceEntryResponse,
    DBIFlightSourceManifestCreateRequest,
    DBIFlightSourceManifestCreateResponse,
    DBIFlightSourceManifestPageResponse,
    DBIFlightSourceManifestSummaryResponse,
)
from app.dbi.flight_source_manifest_repository import (
    DBIFlightSourceManifestRepository,
)


router = APIRouter(
    prefix="/dbi/assets",
    tags=["dbi-flight-source-manifests"],
)

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


def get_dbi_flight_source_manifest_service(
    session: SessionDependency,
) -> DBIFlightSourceManifestService:
    return DBIFlightSourceManifestService(
        DBIFlightSourceManifestRepository(session)
    )


ServiceDependency = Annotated[
    DBIFlightSourceManifestService,
    Depends(get_dbi_flight_source_manifest_service),
]


def _summary(record: DBIFlightSourceManifestRecord):
    return DBIFlightSourceManifestSummaryResponse(
        bundle_id=record.bundle_id,
        schema_version=record.schema_version,
        flight_ref=record.flight_ref,
        master_asset_id=record.master_asset_id,
        farm_id=record.farm_id,
        plot_id=record.plot_id,
        manifest_sha256=record.manifest_sha256,
        entry_count=record.entry_count,
        total_size_bytes=record.total_size_bytes,
        created_by_ref=record.created_by_ref,
        created_at=record.created_at,
    )


def _page_response(page: DBIFlightSourceManifestPage):
    return DBIFlightSourceManifestPageResponse(
        manifest=_summary(page.manifest),
        entries=[
            DBIFlightSourceEntryResponse(
                asset_id=entry.asset_id,
                ordinal=entry.ordinal,
                role=entry.role,
                logical_name=entry.logical_name,
                content_type=entry.content_type,
                size_bytes=entry.size_bytes,
                sha256=entry.sha256,
                sensor_camera=entry.sensor_camera,
                captured_at=entry.captured_at,
            )
            for entry in page.entries
        ],
        offset=page.offset,
        limit=page.limit,
        has_more=page.has_more,
    )


def _handle_error(session: Session, error: Exception) -> None:
    session.rollback()
    if isinstance(error, (DBIAccessDenied, DBIFlightSourceManifestUnavailable)):
        raise HTTPException(
            status_code=404,
            detail="Manifiesto de vuelo DBI no disponible.",
        ) from error
    if isinstance(error, (DBIFlightSourceManifestError, IntegrityError)):
        raise HTTPException(
            status_code=409,
            detail=(
                "El manifiesto de vuelo entra en conflicto con la evidencia "
                "durable."
            ),
        ) from error
    raise error


@router.post(
    "/{master_asset_id}/flight-source-manifests",
    response_model=DBIFlightSourceManifestCreateResponse,
)
def create_flight_source_manifest(
    master_asset_id: UUID,
    payload: DBIFlightSourceManifestCreateRequest,
    response: Response,
    session: SessionDependency,
    context: AccessDependency,
    service: ServiceDependency,
) -> DBIFlightSourceManifestCreateResponse:
    """Registra de forma idempotente un conjunto completo sin recibir binarios."""

    try:
        result = service.create(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            plot_id=payload.plot_id,
            master_asset_id=master_asset_id,
            bundle_id=payload.bundle_id,
            flight_ref=payload.flight_ref,
            entries=tuple(
                DBIFlightSourceEntryIntent(
                    asset_id=entry.asset_id,
                    logical_name=entry.logical_name,
                    role=entry.role,
                    sensor_camera=entry.sensor_camera,
                    captured_at=entry.captured_at,
                )
                for entry in payload.entries
            ),
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
    except Exception as error:
        _handle_error(session, error)
        raise
    response.status_code = (
        status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    )
    return DBIFlightSourceManifestCreateResponse(
        created=result.created,
        manifest=_summary(result.manifest),
    )


@router.get(
    "/{master_asset_id}/flight-source-manifests/{bundle_id}",
    response_model=DBIFlightSourceManifestPageResponse,
)
def inspect_flight_source_manifest(
    master_asset_id: UUID,
    bundle_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
    service: ServiceDependency,
    organization_ref: Annotated[str, Query(min_length=1, max_length=128)],
    farm_id: UUID,
    plot_id: UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> DBIFlightSourceManifestPageResponse:
    """Lee todas las fuentes mediante páginas acotadas y orden estable."""

    try:
        page = service.inspect(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            master_asset_id=master_asset_id,
            bundle_id=bundle_id,
            offset=offset,
            limit=limit,
        )
    except Exception as error:
        _handle_error(session, error)
        raise
    return _page_response(page)
