"""Frontera HTTP autorizada para cargas multipartes sin binarios."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.asset_multipart_api_schemas import (
    DBIMultipartAbortRequest,
    DBIMultipartAbortResponse,
    DBIMultipartCompleteRequest,
    DBIMultipartCompleteResponse,
    DBIMultipartGrantPartsRequest,
    DBIMultipartGrantPartsResponse,
    DBIMultipartInitiateRequest,
    DBIMultipartInitiateResponse,
    DBIMultipartInspectRequest,
    DBIMultipartInspectResponse,
    DBIMultipartPartAccessResponse,
    DBIMultipartRecordPartRequest,
    DBIMultipartRecordPartResponse,
    DBIMultipartSessionResponse,
)
from app.dbi.asset_multipart_application import DBIMultipartSessionSnapshot
from app.dbi.asset_multipart_contracts import DBIMultipartPartEvidence
from app.dbi.asset_multipart_lifecycle_service import (
    DBIMultipartLifecycleService,
)
from app.dbi.asset_multipart_policy import DBIMultipartPolicyError
from app.dbi.asset_multipart_provider import (
    DBIMultipartObjectStore,
    DBIMultipartProviderConflict,
    DBIMultipartProviderDenied,
    DBIMultipartProviderError,
    DBIMultipartProviderIntegrityError,
    DBIMultipartProviderNotFound,
    DBIMultipartProviderPartGrant,
)
from app.dbi.asset_multipart_repository import DBIMultipartRepository
from app.dbi.asset_multipart_upload_service import (
    DBIMultipartOperationUnavailable,
    DBIMultipartPartAuthorization,
    DBIMultipartUploadService,
)
from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session


router = APIRouter(
    prefix="/dbi/assets",
    tags=["dbi-assets-multipart"],
)

DBI_MULTIPART_NOT_FOUND_DETAIL = "Carga multipartes DBI no disponible."
DBI_MULTIPART_CONFLICT_DETAIL = (
    "La operación multipartes entra en conflicto con su estado actual."
)
DBI_MULTIPART_PROVIDER_DETAIL = (
    "El almacenamiento multipartes DBI no está disponible."
)

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


class DBIResolvedMultipartPartAccess(Protocol):
    grant: DBIMultipartProviderPartGrant
    method: str
    url: str
    headers: tuple[tuple[str, str], ...]


class DBIMultipartAPIObjectStore(DBIMultipartObjectStore, Protocol):
    def resolve_part_access(
        self,
        grant_ref: str,
        *,
        now: datetime | None = None,
    ) -> DBIResolvedMultipartPartAccess: ...


def get_dbi_multipart_object_store(
    request: Request,
) -> DBIMultipartAPIObjectStore:
    """Obtiene el proveedor configurado por despliegue, nunca por el cliente."""

    store = getattr(request.app.state, "dbi_multipart_store", None)
    required = (
        "initiate",
        "issue_part_access",
        "resolve_part_access",
        "complete",
        "inspect_completed",
        "abort",
    )
    if store is None or any(not hasattr(store, name) for name in required):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DBI_MULTIPART_PROVIDER_DETAIL,
        )
    return store


StoreDependency = Annotated[
    DBIMultipartAPIObjectStore,
    Depends(get_dbi_multipart_object_store),
]


def get_dbi_multipart_upload_service(
    session: SessionDependency,
    store: StoreDependency,
) -> DBIMultipartUploadService:
    return DBIMultipartUploadService(
        DBIMultipartRepository(session),
        store,
    )


def get_dbi_multipart_lifecycle_service(
    session: SessionDependency,
    store: StoreDependency,
) -> DBIMultipartLifecycleService:
    return DBIMultipartLifecycleService(
        DBIMultipartRepository(session),
        store,
    )


ServiceDependency = Annotated[
    DBIMultipartUploadService,
    Depends(get_dbi_multipart_upload_service),
]
LifecycleServiceDependency = Annotated[
    DBIMultipartLifecycleService,
    Depends(get_dbi_multipart_lifecycle_service),
]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=DBI_MULTIPART_NOT_FOUND_DETAIL,
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=DBI_MULTIPART_CONFLICT_DETAIL,
    )


def _provider_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=DBI_MULTIPART_PROVIDER_DETAIL,
    )


def _session_response(
    value: DBIMultipartSessionSnapshot,
) -> DBIMultipartSessionResponse:
    return DBIMultipartSessionResponse(
        session_id=value.session_id,
        asset_id=value.asset_id,
        state=value.state,
        reason_code=value.reason_code,
        size_bytes=value.size_bytes,
        part_size_bytes=value.part_size_bytes,
        part_count=value.part_count,
        max_grants_per_window=value.max_grants_per_window,
        max_client_concurrency=value.max_client_concurrency,
        checksum_algorithm=value.checksum_algorithm,
        checksum_type=value.checksum_type,
        version=value.version,
        expires_at=value.expires_at,
        last_activity_at=value.last_activity_at,
        completed_at=value.completed_at,
        aborted_at=value.aborted_at,
        expired_at=value.expired_at,
    )


def _rollback_and_raise(
    session: Session,
    error: Exception,
) -> None:
    session.rollback()
    if isinstance(error, (DBIAccessDenied, DBIMultipartOperationUnavailable)):
        raise _not_found() from error
    if isinstance(
        error,
        (
            DBIMultipartPolicyError,
            DBIMultipartProviderConflict,
            DBIMultipartProviderNotFound,
            DBIMultipartProviderIntegrityError,
            IntegrityError,
        ),
    ):
        raise _conflict() from error
    if isinstance(
        error,
        (DBIMultipartProviderDenied, DBIMultipartProviderError),
    ):
        raise _provider_unavailable() from error
    raise error


@router.post(
    "/{asset_id}/multipart/initiate",
    response_model=DBIMultipartInitiateResponse,
)
def initiate_multipart_upload(
    asset_id: UUID,
    payload: DBIMultipartInitiateRequest,
    response: Response,
    session: SessionDependency,
    context: AccessDependency,
    service: ServiceDependency,
) -> DBIMultipartInitiateResponse:
    """Prepara e inicia una sesión sin recibir el contenido del activo."""

    try:
        evidence = service.initiate(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            plot_id=payload.plot_id,
            asset_id=asset_id,
            idempotency_key=payload.idempotency_key,
            checksum_algorithm=payload.checksum_algorithm,
            checksum_type=payload.checksum_type,
        )
        session.commit()
    except Exception as error:
        _rollback_and_raise(session, error)
        raise
    response.status_code = (
        status.HTTP_201_CREATED
        if evidence.preparation.created
        else status.HTTP_200_OK
    )
    return DBIMultipartInitiateResponse(
        decision=evidence.preparation.plan.decision,
        created=evidence.preparation.created,
        provider_started=evidence.provider_started,
        session=(
            _session_response(evidence.session)
            if evidence.session is not None
            else None
        ),
    )


@router.post(
    "/{asset_id}/multipart/{session_id}/grants",
    response_model=DBIMultipartGrantPartsResponse,
)
def grant_multipart_parts(
    asset_id: UUID,
    session_id: UUID,
    payload: DBIMultipartGrantPartsRequest,
    session: SessionDependency,
    context: AccessDependency,
    store: StoreDependency,
    service: ServiceDependency,
) -> DBIMultipartGrantPartsResponse:
    """Emite URLs efímeras para partes exactas sin persistirlas."""

    try:
        evidence = service.grant_parts(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            plot_id=payload.plot_id,
            asset_id=asset_id,
            session_id=session_id,
            parts=tuple(
                DBIMultipartPartAuthorization(
                    part_number=part.part_number,
                    checksum=part.checksum,
                )
                for part in payload.parts
            ),
        )
        resolved_parts: list[DBIMultipartPartAccessResponse] = []
        for grant in evidence.grants:
            resolved = store.resolve_part_access(grant.grant_ref)
            if resolved.grant != grant or resolved.method != "PUT":
                raise DBIMultipartProviderIntegrityError(
                    "el grant multipartes resuelto es divergente."
                )
            resolved_parts.append(
                DBIMultipartPartAccessResponse(
                    part_number=grant.part_number,
                    size_bytes=grant.size_bytes,
                    method="PUT",
                    url=resolved.url,
                    headers=dict(resolved.headers),
                    expires_at=grant.expires_at,
                )
            )
        session.commit()
    except Exception as error:
        _rollback_and_raise(session, error)
        raise
    return DBIMultipartGrantPartsResponse(
        session_id=evidence.session.session_id,
        state=evidence.session.state,
        max_client_concurrency=(
            evidence.session.max_client_concurrency or 1
        ),
        grants=resolved_parts,
    )


@router.post(
    "/{asset_id}/multipart/{session_id}/parts",
    response_model=DBIMultipartRecordPartResponse,
)
def record_multipart_part(
    asset_id: UUID,
    session_id: UUID,
    payload: DBIMultipartRecordPartRequest,
    session: SessionDependency,
    context: AccessDependency,
    service: ServiceDependency,
) -> DBIMultipartRecordPartResponse:
    """Registra metadata de una parte ya cargada, nunca su contenido."""

    try:
        evidence = service.record_part(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            plot_id=payload.plot_id,
            asset_id=asset_id,
            session_id=session_id,
            evidence=DBIMultipartPartEvidence(
                session_id=session_id,
                part_number=payload.part_number,
                size_bytes=payload.size_bytes,
                checksum=payload.checksum,
                etag=payload.etag,
            ),
        )
        session.commit()
    except Exception as error:
        _rollback_and_raise(session, error)
        raise
    return DBIMultipartRecordPartResponse(
        session_id=evidence.snapshot.session_id,
        state=evidence.snapshot.state,
        part_number=evidence.evidence.part_number,
        created=evidence.created,
        recorded_part_count=evidence.recorded_part_count,
        expected_part_count=evidence.snapshot.part_count or 0,
    )


@router.post(
    "/{asset_id}/multipart/{session_id}/complete",
    response_model=DBIMultipartCompleteResponse,
)
def complete_multipart_upload(
    asset_id: UUID,
    session_id: UUID,
    payload: DBIMultipartCompleteRequest,
    session: SessionDependency,
    context: AccessDependency,
    service: ServiceDependency,
) -> DBIMultipartCompleteResponse:
    """Completa el transporte sin marcar el activo como verified."""

    try:
        evidence = service.complete(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            plot_id=payload.plot_id,
            asset_id=asset_id,
            session_id=session_id,
            full_object_checksum=payload.full_object_checksum,
        )
        session.commit()
    except Exception as error:
        _rollback_and_raise(session, error)
        raise
    return DBIMultipartCompleteResponse(
        session_id=evidence.session.session_id,
        state=evidence.session.state,
        changed=evidence.changed,
        transport_integrity="confirmed",
        content_verification="pending",
        completed_at=evidence.completion.completed_at,
    )


@router.post(
    "/{asset_id}/multipart/{session_id}/abort",
    response_model=DBIMultipartAbortResponse,
)
def abort_multipart_upload(
    asset_id: UUID,
    session_id: UUID,
    payload: DBIMultipartAbortRequest,
    session: SessionDependency,
    context: AccessDependency,
    service: LifecycleServiceDependency,
) -> DBIMultipartAbortResponse:
    """Aborta partes incompletas sin eliminar un original completado."""

    try:
        evidence = service.abort(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            plot_id=payload.plot_id,
            asset_id=asset_id,
            session_id=session_id,
        )
        if evidence.session.aborted_at is None:
            raise DBIMultipartPolicyError(
                "la sesión abortada no contiene fecha durable."
            )
        session.commit()
    except Exception as error:
        _rollback_and_raise(session, error)
        raise
    return DBIMultipartAbortResponse(
        session_id=evidence.session.session_id,
        state=evidence.session.state,
        changed=evidence.changed,
        cleanup_confirmed=True,
        aborted_at=evidence.session.aborted_at,
    )


@router.post(
    "/{asset_id}/multipart/{session_id}/inspect",
    response_model=DBIMultipartInspectResponse,
)
def inspect_multipart_upload(
    asset_id: UUID,
    session_id: UUID,
    payload: DBIMultipartInspectRequest,
    session: SessionDependency,
    context: AccessDependency,
    service: ServiceDependency,
) -> DBIMultipartInspectResponse:
    """Consulta progreso durable sin emitir acceso ni leer el objeto."""

    try:
        evidence = service.inspect(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            plot_id=payload.plot_id,
            asset_id=asset_id,
            session_id=session_id,
        )
        session.commit()
    except Exception as error:
        _rollback_and_raise(session, error)
        raise
    return DBIMultipartInspectResponse(
        session=_session_response(evidence.session),
        recorded_part_count=evidence.recorded_part_count,
    )
