"""Flujo operativo local para la primera prueba real DBI.

Este módulo une la empresa heredada con la autoridad DBI exclusivamente en
ambiente local/desarrollo. Mantiene tenant, organización, finca y lote con
ámbitos explícitos y permite cargar una ortofoto real al object store privado.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import current_user, db as get_db
from app.dbi.asset_registration import DBIAssetRegistrationConflict
from app.dbi.asset_repository import DBIAssetRepository
from app.dbi.asset_schemas import AnalysisInputAssetRegister
from app.dbi.asset_service import DBIAssetService
from app.dbi.asset_verification_service import DBIAssetVerificationService
from app.dbi.authorization import DBIAccessDenied, DBIPermission
from app.dbi.dependencies import get_dbi_session
from app.dbi.identity import DBIAccessContextResolver, DBIIdentityRepository
from app.dbi.models.agriculture import Farm, Plot
from app.dbi.models.identity import (
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
    DBIMembershipStatus,
    DBIPrincipal,
    DBIPrincipalStatus,
)
from app.dbi.storage_contracts import (
    DBIStorageError,
    DBIStorageWriteRequest,
)
from app.dbi.storage_local import DBILocalObjectStore
from app.models.company import Company
from app.models.user import User


router = APIRouter(prefix="/dbi/pilot", tags=["dbi-pilot"])

LegacySession = Annotated[Session, Depends(get_db)]
DBISession = Annotated[Session, Depends(get_dbi_session)]
CurrentUser = Annotated[User, Depends(current_user)]


class PilotBootstrapResponse(BaseModel):
    company_id: int
    tenant_ref: str
    organization_ref: str
    principal_ref: str
    farms_authorized: int
    plots_authorized: int


class PilotRuntimeResponse(BaseModel):
    local_mode: bool
    storage_ready: bool
    public_url: str | None


class PilotOrthophotoResponse(BaseModel):
    asset_id: UUID
    farm_id: UUID
    plot_id: UUID
    status: str
    content_type: str
    size_bytes: int
    sha256: str
    crs: str


def _require_local_pilot() -> None:
    environment = os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
    explicitly_enabled = os.environ.get("DBI_ENABLE_LOCAL_PILOT", "").strip() == "1"
    if environment not in {"development", "local"} and not explicitly_enabled:
        raise HTTPException(status_code=404, detail="Recurso no disponible.")


def _tenant_ref() -> str:
    return os.environ.get("DBI_LOCAL_TENANT_REF", "dalgoro-local").strip()


def _organization_ref(company_id: int) -> str:
    return f"legacy-company-{company_id}"


def _require_company(
    legacy_session: Session,
    user: User,
    company_id: int,
) -> Company:
    company = legacy_session.get(Company, company_id)
    if company is None or getattr(company, "is_deleted", False):
        raise HTTPException(status_code=404, detail="Empresa no encontrada.")
    role = str(getattr(user, "role", "")).upper()
    if role != "ADMIN" and company.owner_id != user.id:
        raise HTTPException(status_code=403, detail="No autorizado.")
    return company


def _ensure_scope(
    session: Session,
    *,
    membership_id: UUID,
    scope_type: DBIMembershipScopeType,
    organization_ref: str,
    farm_id: UUID | None = None,
    plot_id: UUID | None = None,
) -> bool:
    statement = select(DBIMembershipScope.id).where(
        DBIMembershipScope.membership_id == membership_id,
        DBIMembershipScope.scope_type == scope_type.value,
        DBIMembershipScope.organization_ref == organization_ref,
    )
    if scope_type is DBIMembershipScopeType.ORGANIZATION:
        statement = statement.where(
            DBIMembershipScope.farm_id.is_(None),
            DBIMembershipScope.plot_id.is_(None),
        )
    elif scope_type is DBIMembershipScopeType.FARM:
        statement = statement.where(
            DBIMembershipScope.farm_id == farm_id,
            DBIMembershipScope.plot_id.is_(None),
        )
    else:
        statement = statement.where(
            DBIMembershipScope.farm_id == farm_id,
            DBIMembershipScope.plot_id == plot_id,
        )

    if session.execute(statement).scalar_one_or_none() is not None:
        return False

    session.add(
        DBIMembershipScope(
            membership_id=membership_id,
            scope_type=scope_type.value,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
    )
    return True


def _ensure_local_authority(
    session: Session,
    *,
    user: User,
    organization_ref: str,
) -> tuple[DBIPrincipal, DBIMembership, int, int]:
    legacy_ref = str(user.id)
    tenant_ref = _tenant_ref()

    principal = session.execute(
        select(DBIPrincipal).where(
            DBIPrincipal.legacy_identity_ref == legacy_ref
        )
    ).scalar_one_or_none()
    if principal is None:
        principal = DBIPrincipal(
            legacy_identity_ref=legacy_ref,
            status=DBIPrincipalStatus.ACTIVE.value,
        )
        session.add(principal)
        session.flush()
    else:
        principal.status = DBIPrincipalStatus.ACTIVE.value

    membership = session.execute(
        select(DBIMembership).where(
            DBIMembership.principal_id == principal.id,
            DBIMembership.tenant_ref == tenant_ref,
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = DBIMembership(
            principal_id=principal.id,
            tenant_ref=tenant_ref,
            status=DBIMembershipStatus.ACTIVE.value,
        )
        session.add(membership)
        session.flush()
    else:
        membership.status = DBIMembershipStatus.ACTIVE.value

    existing_permissions = set(
        session.execute(
            select(DBIMembershipPermission.permission).where(
                DBIMembershipPermission.membership_id == membership.id
            )
        ).scalars()
    )
    for permission in DBIPermission:
        if permission.value not in existing_permissions:
            session.add(
                DBIMembershipPermission(
                    membership_id=membership.id,
                    permission=permission.value,
                )
            )

    _ensure_scope(
        session,
        membership_id=membership.id,
        scope_type=DBIMembershipScopeType.ORGANIZATION,
        organization_ref=organization_ref,
    )

    farms = tuple(
        session.execute(
            select(Farm).where(Farm.organization_ref == organization_ref)
        ).scalars()
    )
    for farm in farms:
        _ensure_scope(
            session,
            membership_id=membership.id,
            scope_type=DBIMembershipScopeType.FARM,
            organization_ref=organization_ref,
            farm_id=farm.id,
        )

    farm_ids = tuple(farm.id for farm in farms)
    plots: tuple[Plot, ...]
    if farm_ids:
        plots = tuple(
            session.execute(
                select(Plot).where(Plot.farm_id.in_(farm_ids))
            ).scalars()
        )
    else:
        plots = ()

    farm_by_id = {farm.id: farm for farm in farms}
    for plot in plots:
        parent = farm_by_id.get(plot.farm_id)
        if parent is None:
            continue
        _ensure_scope(
            session,
            membership_id=membership.id,
            scope_type=DBIMembershipScopeType.PLOT,
            organization_ref=organization_ref,
            farm_id=parent.id,
            plot_id=plot.id,
        )

    session.flush()
    return principal, membership, len(farms), len(plots)


def _context_for(
    session: Session,
    *,
    user: User,
    organization_ref: str,
):
    _ensure_local_authority(
        session,
        user=user,
        organization_ref=organization_ref,
    )
    return DBIAccessContextResolver(DBIIdentityRepository(session)).resolve(
        legacy_identity_ref=str(user.id),
        tenant_ref=_tenant_ref(),
    )


def _local_store(request: Request) -> DBILocalObjectStore:
    store = getattr(request.app.state, "dbi_object_store", None)
    if not isinstance(store, DBILocalObjectStore):
        raise HTTPException(
            status_code=503,
            detail="El almacenamiento privado local DBI no está disponible.",
        )
    return store


@router.post(
    "/companies/{company_id}/bootstrap",
    response_model=PilotBootstrapResponse,
)
def bootstrap_company(
    company_id: int,
    legacy_session: LegacySession,
    dbi_session: DBISession,
    user: CurrentUser,
) -> PilotBootstrapResponse:
    """Provisiona/reconcilia la autoridad DBI local para una empresa existente."""

    _require_local_pilot()
    _require_company(legacy_session, user, company_id)
    organization_ref = _organization_ref(company_id)

    try:
        principal, _, farm_count, plot_count = _ensure_local_authority(
            dbi_session,
            user=user,
            organization_ref=organization_ref,
        )
        dbi_session.commit()
    except IntegrityError as error:
        dbi_session.rollback()
        raise HTTPException(
            status_code=409,
            detail="No se pudo reconciliar la autoridad DBI local.",
        ) from error

    return PilotBootstrapResponse(
        company_id=company_id,
        tenant_ref=_tenant_ref(),
        organization_ref=organization_ref,
        principal_ref=str(principal.id),
        farms_authorized=farm_count,
        plots_authorized=plot_count,
    )


@router.get("/runtime", response_model=PilotRuntimeResponse)
def pilot_runtime(
    request: Request,
    user: CurrentUser,
) -> PilotRuntimeResponse:
    """Expone solo el URL operativo del túnel y disponibilidad de storage."""

    _require_local_pilot()
    if str(getattr(user, "role", "")).upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="No autorizado.")

    state_path_raw = os.environ.get("DBI_RUNTIME_STATE_PATH", "").strip()
    if state_path_raw:
        state_path = Path(state_path_raw)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        state_path = (
            Path(local_app_data) / "DALGORO" / "DBI" / "runtime-state.json"
            if local_app_data
            else Path()
        )

    public_url: str | None = None
    if state_path and state_path.is_file():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8-sig"))
            candidate = str(data.get("public_url") or "").strip()
            if candidate.startswith("https://"):
                public_url = candidate.rstrip("/")
        except (OSError, ValueError, TypeError):
            public_url = None

    return PilotRuntimeResponse(
        local_mode=True,
        storage_ready=isinstance(
            getattr(request.app.state, "dbi_object_store", None),
            DBILocalObjectStore,
        ),
        public_url=public_url,
    )


@router.post(
    "/companies/{company_id}/orthophoto",
    response_model=PilotOrthophotoResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_pilot_orthophoto(
    company_id: int,
    request: Request,
    legacy_session: LegacySession,
    dbi_session: DBISession,
    user: CurrentUser,
    farm_id: Annotated[UUID, Form()],
    plot_id: Annotated[UUID, Form()],
    crs: Annotated[str, Form(min_length=1, max_length=80)],
    file: Annotated[UploadFile, File()],
) -> PilotOrthophotoResponse:
    """Registra, almacena y verifica una ortofoto TIFF por streaming local."""

    _require_local_pilot()
    _require_company(legacy_session, user, company_id)
    organization_ref = _organization_ref(company_id)
    store = _local_store(request)

    farm = dbi_session.get(Farm, farm_id)
    if farm is None or farm.organization_ref != organization_ref:
        raise HTTPException(status_code=404, detail="Finca DBI no encontrada.")
    plot = dbi_session.get(Plot, plot_id)
    if plot is None or plot.farm_id != farm_id:
        raise HTTPException(status_code=404, detail="Lote DBI no encontrado.")

    filename = (file.filename or "").lower()
    if not filename.endswith((".tif", ".tiff")):
        raise HTTPException(
            status_code=422,
            detail="La primera prueba requiere una ortofoto GeoTIFF (.tif o .tiff).",
        )

    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type in {"", "application/octet-stream"}:
        content_type = "image/tiff"
    if content_type != "image/tiff":
        raise HTTPException(
            status_code=422,
            detail="La ortofoto debe declararse como image/tiff.",
        )

    max_bytes = int(
        os.environ.get(
            "DBI_PILOT_MAX_UPLOAD_BYTES",
            str(12 * 1024 * 1024 * 1024),
        )
    )
    digest = sha256()
    total = 0
    while True:
        chunk = file.file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="La ortofoto supera el límite local configurado para el piloto.",
            )
        digest.update(chunk)

    if total <= 0:
        raise HTTPException(status_code=422, detail="La ortofoto está vacía.")
    file.file.seek(0)

    asset_id = uuid4()
    repository = DBIAssetRepository(dbi_session)
    stored_created = False
    address = None
    try:
        context = _context_for(
            dbi_session,
            user=user,
            organization_ref=organization_ref,
        )
        register = AnalysisInputAssetRegister(
            asset_id=asset_id,
            plot_id=plot_id,
            asset_kind="orthophoto",
            content_type=content_type,
            size_bytes=total,
            sha256=digest.hexdigest(),
            crs=crs.strip(),
        )
        evidence = DBIAssetService(repository).register(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            request=register,
        )
        address = evidence.plan.metadata.address
        stored = store.put(
            DBIStorageWriteRequest(metadata=evidence.plan.metadata),
            file.file,
        )
        stored_created = stored.created

        verification = DBIAssetVerificationService(repository, store).confirm(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            asset_id=asset_id,
            verified_at=datetime.now(timezone.utc),
        )
        if verification.result.decision.value != "verified":
            raise HTTPException(
                status_code=409,
                detail="La ortofoto no superó la verificación de integridad.",
            )
        dbi_session.commit()
    except HTTPException:
        dbi_session.rollback()
        if stored_created and address is not None:
            try:
                store.retire(address, retired_at=datetime.now(timezone.utc))
            except DBIStorageError:
                pass
        raise
    except (DBIAccessDenied, DBIAssetRegistrationConflict, DBIStorageError) as error:
        dbi_session.rollback()
        if stored_created and address is not None:
            try:
                store.retire(address, retired_at=datetime.now(timezone.utc))
            except DBIStorageError:
                pass
        raise HTTPException(
            status_code=409,
            detail="No se pudo registrar y verificar la ortofoto DBI.",
        ) from error
    except IntegrityError as error:
        dbi_session.rollback()
        if stored_created and address is not None:
            try:
                store.retire(address, retired_at=datetime.now(timezone.utc))
            except DBIStorageError:
                pass
        raise HTTPException(
            status_code=409,
            detail="La ortofoto entra en conflicto con datos DBI existentes.",
        ) from error

    return PilotOrthophotoResponse(
        asset_id=asset_id,
        farm_id=farm_id,
        plot_id=plot_id,
        status="verified",
        content_type=content_type,
        size_bytes=total,
        sha256=digest.hexdigest(),
        crs=crs.strip(),
    )
