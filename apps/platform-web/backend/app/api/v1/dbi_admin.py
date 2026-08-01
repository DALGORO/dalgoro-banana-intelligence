"""Frontera HTTP administrativa DBI cerrada por defecto."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.admin_dependencies import (
    AdminActorDependency,
    get_dbi_admin_membership_state,
)
from app.dbi.admin_membership_schemas import (
    DBIAdminMembershipReadResponse,
    DBIAdminMembershipStatusRequest,
)
from app.dbi.admin_persistence import DBIAdminPersistenceRepository
from app.dbi.admin_policy import (
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminDenied,
    DBIAdminMembershipStatus,
    DBIAdminPolicy,
)
from app.dbi.admin_schemas import (
    DBIAdminFarmScopeInput,
    DBIAdminMembershipCreationRequest,
    DBIAdminMembershipCreationResponse,
    DBIAdminMembershipMutationRequest,
    DBIAdminMembershipMutationResponse,
    DBIAdminPlotScopeInput,
    DBIAdminPrincipalRegistrationRequest,
    DBIAdminPrincipalRegistrationResponse,
)
from app.dbi.admin_service import (
    DBIAdminMembershipCreationEvidence,
    DBIAdminMembershipMutationEvidence,
    DBIAdminPrincipalRegistrationEvidence,
    DBIAdminService,
)
from app.dbi.admin_state import DBIAdminPersistedMembershipState
from app.dbi.dependencies import get_dbi_session

router = APIRouter(prefix="/dbi/admin", tags=["dbi-admin"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
TargetMembershipDependency = Annotated[
    DBIAdminPersistedMembershipState,
    Depends(get_dbi_admin_membership_state),
]

ResultT = TypeVar("ResultT")


DBI_ADMIN_DENIED_DETAIL = "Acceso administrativo DBI denegado."
DBI_ADMIN_NOT_FOUND_DETAIL = "Recurso administrativo DBI no encontrado."
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


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DBI_ADMIN_NOT_FOUND_DETAIL,
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=DBI_ADMIN_CONFLICT_DETAIL,
    )


def _execute_transaction(
    session: Session,
    operation: Callable[[], ResultT],
    *,
    hide_denied: bool = False,
) -> ResultT:
    try:
        result = operation()
        session.commit()
        return result
    except DBIAdminDenied as error:
        session.rollback()
        if hide_denied:
            raise _not_found() from error
        raise _denied() from error
    except (DBIAdminConflict, IntegrityError) as error:
        session.rollback()
        raise _conflict() from error


def _farm_inputs(
    authority: DBIAdminAuthoritySnapshot,
) -> tuple[DBIAdminFarmScopeInput, ...]:
    return tuple(
        DBIAdminFarmScopeInput(
            organization_ref=scope.organization_ref,
            farm_id=scope.farm_id,
        )
        for scope in sorted(
            authority.farm_scopes,
            key=lambda value: (value.organization_ref, str(value.farm_id)),
        )
    )


def _plot_inputs(
    authority: DBIAdminAuthoritySnapshot,
) -> tuple[DBIAdminPlotScopeInput, ...]:
    return tuple(
        DBIAdminPlotScopeInput(
            organization_ref=scope.organization_ref,
            farm_id=scope.farm_id,
            plot_id=scope.plot_id,
        )
        for scope in sorted(
            authority.plot_scopes,
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


def _membership_creation_response(
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
        farm_scopes=_farm_inputs(requested),
        plot_scopes=_plot_inputs(requested),
        occurred_at=evidence.plan.occurred_at,
        correlation_ref=evidence.plan.correlation_ref,
    )


def _membership_read_response(
    target: DBIAdminPersistedMembershipState,
) -> DBIAdminMembershipReadResponse:
    authority = target.authority
    return DBIAdminMembershipReadResponse(
        membership_id=target.membership_id,
        principal_id=target.principal_id,
        principal_ref=authority.principal_ref,
        tenant_ref=authority.tenant_ref,
        principal_active=authority.principal_active,
        status=authority.membership_status,
        permissions=tuple(
            sorted(authority.permissions, key=lambda value: value.value)
        ),
        organization_scopes=tuple(sorted(authority.organization_scopes)),
        farm_scopes=_farm_inputs(authority),
        plot_scopes=_plot_inputs(authority),
        principal_updated_at=target.principal_updated_at,
        membership_updated_at=target.membership_updated_at,
    )


def _membership_mutation_response(
    *,
    membership_id: UUID,
    evidence: DBIAdminMembershipMutationEvidence,
    correlation_ref: str,
) -> DBIAdminMembershipMutationResponse:
    after = evidence.plan.after
    return DBIAdminMembershipMutationResponse(
        membership_id=membership_id,
        applied=evidence.plan.applied,
        updated_at=evidence.plan.next_updated_at,
        status=after.membership_status,
        permissions=tuple(
            sorted(after.permissions, key=lambda value: value.value)
        ),
        organization_scopes=tuple(sorted(after.organization_scopes)),
        farm_scopes=_farm_inputs(after),
        plot_scopes=_plot_inputs(after),
        affected_organization_refs=tuple(
            sorted(evidence.plan.affected_organization_refs)
        ),
        correlation_ref=correlation_ref,
    )


def _next_updated_at(expected_updated_at: datetime) -> datetime:
    candidate = datetime.now(timezone.utc)
    minimum = expected_updated_at.astimezone(timezone.utc) + timedelta(
        microseconds=1
    )
    return candidate if candidate >= minimum else minimum


def _require_membership_read(
    actor: DBIAdminPersistedMembershipState,
    target: DBIAdminPersistedMembershipState,
) -> None:
    try:
        DBIAdminPolicy.require_organization_control(
            actor.authority,
            tenant_ref=target.authority.tenant_ref,
            organization_refs=target.authority.all_organization_refs,
        )
    except DBIAdminDenied as error:
        raise _not_found() from error


def _mutate_membership(
    *,
    membership_id: UUID,
    actor: DBIAdminPersistedMembershipState,
    target: DBIAdminPersistedMembershipState,
    after: DBIAdminAuthoritySnapshot,
    expected_updated_at: datetime,
    correlation_ref: str,
    session: Session,
    service: DBIAdminService,
) -> DBIAdminMembershipMutationResponse:
    evidence = _execute_transaction(
        session,
        lambda: service.mutate_membership(
            actor.authority,
            target.authority,
            after,
            actor_membership_id=actor.membership_id,
            target_membership_id=membership_id,
            expected_updated_at=expected_updated_at,
            next_updated_at=_next_updated_at(expected_updated_at),
            correlation_ref=correlation_ref,
        ),
        hide_denied=True,
    )
    return _membership_mutation_response(
        membership_id=membership_id,
        evidence=evidence,
        correlation_ref=correlation_ref,
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
    return _membership_creation_response(evidence)


@router.get(
    "/memberships/{membership_id}",
    response_model=DBIAdminMembershipReadResponse,
)
def get_membership(
    actor: AdminActorDependency,
    target: TargetMembershipDependency,
) -> DBIAdminMembershipReadResponse:
    """Consulta una membresía solo con cobertura de todas sus organizaciones."""

    _require_membership_read(actor, target)
    return _membership_read_response(target)


@router.patch(
    "/memberships/{membership_id}",
    response_model=DBIAdminMembershipMutationResponse,
)
def update_membership(
    membership_id: UUID,
    payload: DBIAdminMembershipMutationRequest,
    session: SessionDependency,
    actor: AdminActorDependency,
    target: TargetMembershipDependency,
    service: ServiceDependency,
) -> DBIAdminMembershipMutationResponse:
    """Sustituye estado, permisos y ámbitos con concurrencia optimista."""

    after = payload.to_authority_snapshot(before=target.authority)
    return _mutate_membership(
        membership_id=membership_id,
        actor=actor,
        target=target,
        after=after,
        expected_updated_at=payload.expected_updated_at,
        correlation_ref=payload.correlation_ref,
        session=session,
        service=service,
    )


def _change_membership_status(
    *,
    membership_id: UUID,
    requested_status: DBIAdminMembershipStatus,
    payload: DBIAdminMembershipStatusRequest,
    session: Session,
    actor: DBIAdminPersistedMembershipState,
    target: DBIAdminPersistedMembershipState,
    service: DBIAdminService,
) -> DBIAdminMembershipMutationResponse:
    after = replace(
        target.authority,
        membership_status=requested_status,
    )
    return _mutate_membership(
        membership_id=membership_id,
        actor=actor,
        target=target,
        after=after,
        expected_updated_at=payload.expected_updated_at,
        correlation_ref=payload.correlation_ref,
        session=session,
        service=service,
    )


@router.post(
    "/memberships/{membership_id}/deactivate",
    response_model=DBIAdminMembershipMutationResponse,
)
def deactivate_membership(
    membership_id: UUID,
    payload: DBIAdminMembershipStatusRequest,
    session: SessionDependency,
    actor: AdminActorDependency,
    target: TargetMembershipDependency,
    service: ServiceDependency,
) -> DBIAdminMembershipMutationResponse:
    return _change_membership_status(
        membership_id=membership_id,
        requested_status=DBIAdminMembershipStatus.INACTIVE,
        payload=payload,
        session=session,
        actor=actor,
        target=target,
        service=service,
    )


@router.post(
    "/memberships/{membership_id}/reactivate",
    response_model=DBIAdminMembershipMutationResponse,
)
def reactivate_membership(
    membership_id: UUID,
    payload: DBIAdminMembershipStatusRequest,
    session: SessionDependency,
    actor: AdminActorDependency,
    target: TargetMembershipDependency,
    service: ServiceDependency,
) -> DBIAdminMembershipMutationResponse:
    return _change_membership_status(
        membership_id=membership_id,
        requested_status=DBIAdminMembershipStatus.ACTIVE,
        payload=payload,
        session=session,
        actor=actor,
        target=target,
        service=service,
    )


@router.post(
    "/memberships/{membership_id}/revoke",
    response_model=DBIAdminMembershipMutationResponse,
)
def revoke_membership(
    membership_id: UUID,
    payload: DBIAdminMembershipStatusRequest,
    session: SessionDependency,
    actor: AdminActorDependency,
    target: TargetMembershipDependency,
    service: ServiceDependency,
) -> DBIAdminMembershipMutationResponse:
    return _change_membership_status(
        membership_id=membership_id,
        requested_status=DBIAdminMembershipStatus.REVOKED,
        payload=payload,
        session=session,
        actor=actor,
        target=target,
        service=service,
    )
