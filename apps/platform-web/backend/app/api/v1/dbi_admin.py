"""Frontera HTTP administrativa DBI cerrada por defecto."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.admin_dependencies import get_dbi_admin_actor_state
from app.dbi.admin_persistence import DBIAdminPersistenceRepository
from app.dbi.admin_policy import (
    DBIAdminConflict,
    DBIAdminDenied,
    DBIAdminMembershipStatus,
)
from app.dbi.admin_schemas import (
    DBIAdminFarmScopeInput,
    DBIAdminMembershipCreationRequest,
    DBIAdminMembershipCreationResponse,
    DBIAdminPlotScopeInput,
    DBIAdminPrincipalRegistrationRequest,
    DBIAdminPrincipalRegistrationResponse,
)
from app.dbi.admin_service import (
    DBIAdminMembershipCreationEvidence,
    DBIAdminPrincipalRegistrationEvidence,
    DBIAdminService,
)
from app.dbi.admin_state import DBIAdminPersistedMembershipState
from app.dbi.dependencies import get_dbi_session

router = APIRouter(prefix="/dbi/admin", tags=["dbi-admin"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AdminActorDependency = Annotated[
    DBIAdminPersistedMembershipState,
    Depends(get_dbi_admin_actor_state),
]

ResultT = TypeVar("ResultT")


DBI_ADMIN_DENIED_DETAIL = "Acceso administrativo DBI denegado."
DBI_ADMIN_CONFLICT_DETAIL = (
    "La operación administrativa DBI entra en conflicto con el estado actual."
)


def get_dbi_admin_service(session: SessionDependency) -> DBIAdminService:
    """Construye el servicio sobre la misma sesión DBI de la solicitud."""

    return DBIAdminService(DBIAdminPersistenceRepository(session))


ServiceDependency = Annotated[DBIAdminService, Depends(get_dbi_admin_service)]


def _denied() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=DBI_ADMIN_DENIED_DETAIL,
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=DBI_ADMIN_CONFLICT_DETAIL,
    )


def _execute_transaction(
    session: Session,
    operation: Callable[[], ResultT],
) -> ResultT:
    try:
        result = operation()
        session.commit()
        return result
    except DBIAdminDenied as error:
        session.rollback()
        raise _denied() from error
    except (DBIAdminConflict, IntegrityError) as error:
        session.rollback()
        raise _conflict() from error


def _farm_inputs(evidence: DBIAdminMembershipCreationEvidence) -> tuple[DBIAdminFarmScopeInput, ...]:
    return tuple(
        DBIAdminFarmScopeInput(
            organization_ref=scope.organization_ref,
            farm_id=scope.farm_id,
        )
        for scope in sorted(
            evidence.plan.requested.farm_scopes,
            key=lambda value: (value.organization_ref, str(value.farm_id)),
        )
    )


def _plot_inputs(evidence: DBIAdminMembershipCreationEvidence) -> tuple[DBIAdminPlotScopeInput, ...]:
    return tuple(
        DBIAdminPlotScopeInput(
            organization_ref=scope.organization_ref,
            farm_id=scope.farm_id,
            plot_id=scope.plot_id,
        )
        for scope in sorted(
            evidence.plan.requested.plot_scopes,
            key=lambda value: (
                value.organization_ref,
                str(value.farm_id),
                str(value.plot_id),
            ),
        )
    )


def _principal_response(
    evidence: DBIAdminPrincipalRegistrationEvidence,
) -> DBIAdminPrincipalRegistrationResponse:
    return DBIAdminPrincipalRegistrationResponse(
        principal_id=evidence.plan.principal_id,
        created=evidence.created,
        occurred_at=evidence.plan.occurred_at,
        correlation_ref=evidence.plan.correlation_ref,
        organization_refs=tuple(sorted(evidence.plan.organization_refs)),
    )


def _membership_response(
    evidence: DBIAdminMembershipCreationEvidence,
) -> DBIAdminMembershipCreationResponse:
    requested = evidence.plan.requested
    return DBIAdminMembershipCreationResponse(
        membership_id=evidence.plan.membership_id,
        principal_id=evidence.plan.principal_id,
        created=evidence.created,
        tenant_ref=requested.tenant_ref,
        status=DBIAdminMembershipStatus.ACTIVE,
        permissions=tuple(
            sorted(requested.permissions, key=lambda value: value.value)
        ),
        organization_scopes=tuple(sorted(requested.organization_scopes)),
        farm_scopes=_farm_inputs(evidence),
        plot_scopes=_plot_inputs(evidence),
        occurred_at=evidence.plan.occurred_at,
        correlation_ref=evidence.plan.correlation_ref,
    )


@router.post(
    "/principals",
    response_model=DBIAdminPrincipalRegistrationResponse,
)
def register_principal(
    payload: DBIAdminPrincipalRegistrationRequest,
    response: Response,
    session: SessionDependency,
    actor: AdminActorDependency,
    service: ServiceDependency,
) -> DBIAdminPrincipalRegistrationResponse:
    """Registra un principal activo sin permitir mutar su estado global."""

    occurred_at = datetime.now(timezone.utc)
    evidence = _execute_transaction(
        session,
        lambda: service.register_principal(
            actor.authority,
            actor_membership_id=actor.membership_id,
            principal_id=payload.principal_id,
            target_principal_ref=payload.legacy_identity_ref,
            tenant_ref=actor.authority.tenant_ref,
            organization_refs=payload.organization_set,
            occurred_at=occurred_at,
            correlation_ref=payload.correlation_ref,
        ),
    )
    response.status_code = (
        status.HTTP_201_CREATED if evidence.created else status.HTTP_200_OK
    )
    return _principal_response(evidence)


@router.post(
    "/memberships",
    response_model=DBIAdminMembershipCreationResponse,
)
def create_membership(
    payload: DBIAdminMembershipCreationRequest,
    response: Response,
    session: SessionDependency,
    actor: AdminActorDependency,
    service: ServiceDependency,
) -> DBIAdminMembershipCreationResponse:
    """Crea una membresía activa con autoridad completa e idempotente."""

    occurred_at = datetime.now(timezone.utc)
    requested = payload.to_authority_snapshot(
        tenant_ref=actor.authority.tenant_ref,
    )
    evidence = _execute_transaction(
        session,
        lambda: service.create_membership(
            actor.authority,
            requested,
            actor_membership_id=actor.membership_id,
            membership_id=payload.membership_id,
            principal_id=payload.principal_id,
            occurred_at=occurred_at,
            correlation_ref=payload.correlation_ref,
        ),
    )
    response.status_code = (
        status.HTTP_201_CREATED if evidence.created else status.HTTP_200_OK
    )
    return _membership_response(evidence)
