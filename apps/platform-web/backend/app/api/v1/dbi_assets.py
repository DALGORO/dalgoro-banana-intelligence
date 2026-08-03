"""Frontera HTTP transaccional para activos privados DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.asset_api_schemas import (
    DBIAssetConfirmRequest,
    DBIAssetConfirmResponse,
    DBIAssetQuarantineCleanupRequest,
    DBIAssetQuarantineCleanupResponse,
    DBIAssetRetireRequest,
    DBIAssetRetireResponse,
    DBIAssetUploadAccessResponse,
    DBIAssetUploadRequest,
    DBIAssetUploadResponse,
)
from app.dbi.asset_quarantine_cleanup_service import (
    DBIAssetQuarantineCleanupService,
)
from app.dbi.asset_registration import DBIAssetRegistrationConflict
from app.dbi.asset_repository import DBIAssetRepository
from app.dbi.asset_retirement_service import DBIAssetRetirementService
from app.dbi.asset_service import DBIAssetService
from app.dbi.asset_upload_service import (
    DBIAssetSynchronousLimitExceeded,
    DBIAssetUploadGrantFailure,
    DBIAssetUploadService,
)
from app.dbi.asset_verification import DBIAssetVerificationDecision
from app.dbi.asset_verification_service import DBIAssetVerificationService
from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.storage_contracts import (
    DBIPrivateObjectStore,
    DBIStorageError,
    DBIStorageIntegrityError,
    DBIStorageNotFound,
    DBIStorageTemporaryGrant,
)

router = APIRouter(prefix="/dbi/assets", tags=["dbi-assets"])

DBI_ASSET_NOT_FOUND_DETAIL = "Activo DBI no disponible."
DBI_ASSET_CONFLICT_DETAIL = "La operación del activo entra en conflicto con su estado actual."
DBI_ASSET_STORAGE_DETAIL = "El almacenamiento privado DBI no está disponible."
DBI_ASSET_MULTIPART_REQUIRED_CODE = "asset_multipart_required"
DBI_ASSET_MULTIPART_REQUIRED_MESSAGE = (
    "El activo supera el límite síncrono y requiere carga multipartes."
)

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


class DBIResolvedUploadAccess(Protocol):
    grant: DBIStorageTemporaryGrant
    method: str
    url: str
    headers: tuple[tuple[str, str], ...]


class DBIAssetAPIObjectStore(DBIPrivateObjectStore, Protocol):
    def resolve_temporary_access(
        self,
        grant_ref: str,
        *,
        now: datetime | None = None,
    ) -> DBIResolvedUploadAccess: ...


def get_dbi_asset_object_store(request: Request) -> DBIAssetAPIObjectStore:
    """Obtiene el puerto privado configurado por el despliegue, nunca por el cliente."""

    store = getattr(request.app.state, "dbi_object_store", None)
    required = (
        "issue_temporary_access",
        "resolve_temporary_access",
        "stat",
        "open_read",
        "retire",
    )
    if store is None or any(not hasattr(store, name) for name in required):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DBI_ASSET_STORAGE_DETAIL,
        )
    return store


StoreDependency = Annotated[
    DBIAssetAPIObjectStore,
    Depends(get_dbi_asset_object_store),
]


def get_dbi_asset_upload_service(
    session: SessionDependency,
    store: StoreDependency,
) -> DBIAssetUploadService:
    repository = DBIAssetRepository(session)
    return DBIAssetUploadService(DBIAssetService(repository), store)


def get_dbi_asset_verification_service(
    session: SessionDependency,
    store: StoreDependency,
) -> DBIAssetVerificationService:
    return DBIAssetVerificationService(DBIAssetRepository(session), store)


def get_dbi_asset_quarantine_cleanup_service(
    session: SessionDependency,
    store: StoreDependency,
) -> DBIAssetQuarantineCleanupService:
    return DBIAssetQuarantineCleanupService(DBIAssetRepository(session), store)


def get_dbi_asset_retirement_service(
    session: SessionDependency,
    store: StoreDependency,
) -> DBIAssetRetirementService:
    return DBIAssetRetirementService(DBIAssetRepository(session), store)


UploadServiceDependency = Annotated[
    DBIAssetUploadService,
    Depends(get_dbi_asset_upload_service),
]
VerificationServiceDependency = Annotated[
    DBIAssetVerificationService,
    Depends(get_dbi_asset_verification_service),
]
QuarantineCleanupServiceDependency = Annotated[
    DBIAssetQuarantineCleanupService,
    Depends(get_dbi_asset_quarantine_cleanup_service),
]
RetirementServiceDependency = Annotated[
    DBIAssetRetirementService,
    Depends(get_dbi_asset_retirement_service),
]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=DBI_ASSET_NOT_FOUND_DETAIL)


def _conflict() -> HTTPException:
    return HTTPException(status_code=409, detail=DBI_ASSET_CONFLICT_DETAIL)


def _storage_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail=DBI_ASSET_STORAGE_DETAIL)


def _multipart_required(max_size_bytes: int) -> HTTPException:
    return HTTPException(
        status_code=413,
        detail={
            "code": DBI_ASSET_MULTIPART_REQUIRED_CODE,
            "message": DBI_ASSET_MULTIPART_REQUIRED_MESSAGE,
            "max_synchronous_size_bytes": max_size_bytes,
            "required_flow": "multipart_upload",
        },
    )


@router.post("", response_model=DBIAssetUploadResponse)
def register_asset_upload(
    payload: DBIAssetUploadRequest,
    response: Response,
    session: SessionDependency,
    context: AccessDependency,
    store: StoreDependency,
    service: UploadServiceDependency,
) -> DBIAssetUploadResponse:
    """Registra metadata y emite una carga temporal dentro de una sola UoW."""

    try:
        evidence = service.register_and_issue_upload(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            request=payload.asset,
            issued_at=datetime.now(timezone.utc),
        )
        resolved = store.resolve_temporary_access(evidence.grant.grant_ref)
        if resolved.grant != evidence.grant or resolved.method != "PUT":
            raise DBIAssetUploadGrantFailure("Grant temporal divergente.")
        session.commit()
    except DBIAccessDenied as error:
        session.rollback()
        raise _not_found() from error
    except DBIAssetSynchronousLimitExceeded as error:
        session.rollback()
        raise _multipart_required(error.max_size_bytes) from error
    except (DBIAssetRegistrationConflict, IntegrityError) as error:
        session.rollback()
        raise _conflict() from error
    except DBIAssetUploadGrantFailure as error:
        session.rollback()
        raise _storage_unavailable() from error
    except DBIStorageError as error:
        session.rollback()
        raise _storage_unavailable() from error

    response.status_code = (
        status.HTTP_201_CREATED
        if evidence.registration.created
        else status.HTTP_200_OK
    )
    return DBIAssetUploadResponse(
        asset_id=evidence.registration.plan.asset_id,
        status="registered",
        created=evidence.registration.created,
        upload=DBIAssetUploadAccessResponse(
            method="PUT",
            url=resolved.url,
            headers=dict(resolved.headers),
            expires_at=evidence.grant.expires_at,
        ),
    )


@router.post("/{asset_id}/confirm", response_model=DBIAssetConfirmResponse)
def confirm_asset_upload(
    asset_id: UUID,
    payload: DBIAssetConfirmRequest,
    session: SessionDependency,
    context: AccessDependency,
    service: VerificationServiceDependency,
) -> DBIAssetConfirmResponse:
    """Lee y verifica el objeto completo antes de persistir su estado final."""

    try:
        evidence = service.confirm(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            asset_id=asset_id,
            verified_at=datetime.now(timezone.utc),
        )
        session.commit()
    except (DBIAccessDenied, DBIAssetRegistrationConflict) as error:
        session.rollback()
        raise _not_found() from error
    except (DBIStorageNotFound, DBIStorageIntegrityError) as error:
        session.rollback()
        raise _conflict() from error
    except (DBIStorageError, IntegrityError) as error:
        session.rollback()
        raise _storage_unavailable() from error

    result = evidence.result
    return DBIAssetConfirmResponse(
        asset_id=asset_id,
        status=result.decision.value,
        changed=evidence.changed,
        reason=(
            "verified"
            if result.decision is DBIAssetVerificationDecision.VERIFIED
            else "integrity_mismatch"
        ),
    )


@router.post(
    "/{asset_id}/quarantine-cleanup",
    response_model=DBIAssetQuarantineCleanupResponse,
)
def cleanup_quarantined_asset(
    asset_id: UUID,
    payload: DBIAssetQuarantineCleanupRequest,
    session: SessionDependency,
    context: AccessDependency,
    service: QuarantineCleanupServiceDependency,
) -> DBIAssetQuarantineCleanupResponse:
    """Retira el objeto cuarentenado sin convertir el activo en retired."""

    try:
        evidence = service.cleanup(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            asset_id=asset_id,
            cleaned_at=datetime.now(timezone.utc),
        )
        session.commit()
    except (DBIAccessDenied, DBIAssetRegistrationConflict) as error:
        session.rollback()
        raise _not_found() from error
    except (DBIStorageError, IntegrityError) as error:
        session.rollback()
        raise _storage_unavailable() from error

    return DBIAssetQuarantineCleanupResponse(
        asset_id=asset_id,
        status="quarantined",
        changed=evidence.object_changed,
    )


@router.post(
    "/{asset_id}/retire",
    response_model=DBIAssetRetireResponse,
)
def retire_asset(
    asset_id: UUID,
    payload: DBIAssetRetireRequest,
    session: SessionDependency,
    context: AccessDependency,
    service: RetirementServiceDependency,
) -> DBIAssetRetireResponse:
    """Retira primero el objeto privado y después confirma el estado DBI."""

    try:
        evidence = service.retire(
            context,
            organization_ref=payload.organization_ref,
            farm_id=payload.farm_id,
            asset_id=asset_id,
            retired_at=datetime.now(timezone.utc),
        )
        session.commit()
    except (DBIAccessDenied, DBIAssetRegistrationConflict) as error:
        session.rollback()
        raise _not_found() from error
    except (DBIStorageNotFound, DBIStorageIntegrityError) as error:
        session.rollback()
        raise _conflict() from error
    except (DBIStorageError, IntegrityError) as error:
        session.rollback()
        raise _storage_unavailable() from error

    return DBIAssetRetireResponse(
        asset_id=asset_id,
        status="retired",
        changed=(
            evidence.object_changed
            or evidence.state_changed
        ),
    )
