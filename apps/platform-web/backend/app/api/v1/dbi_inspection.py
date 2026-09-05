"""API autorizada para captura y versionado de verdad-terreno INSPECT."""

from __future__ import annotations

from typing import Annotated, Callable, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.inspection.api_schemas import (
    DBIFieldObservationCorrectionRequest,
    DBIFieldObservationCreateRequest,
)
from app.dbi.inspection.contracts import DBIFieldObservationVersion
from app.dbi.inspection.repository import DBIInspectionConflict
from app.dbi.inspection.service import (
    DBIFieldObservationService,
    DBIInspectionUnavailable,
)

router = APIRouter(prefix="/dbi", tags=["dbi-inspection"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]

DBI_INSPECTION_NOT_FOUND_DETAIL = "Observación DBI no disponible."
DBI_INSPECTION_CONFLICT_DETAIL = (
    "La observación DBI no supera las verificaciones de integridad."
)

T = TypeVar("T")


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DBI_INSPECTION_NOT_FOUND_DETAIL,
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=DBI_INSPECTION_CONFLICT_DETAIL,
    )


def _require_plot(
    context: DBIAccessContext,
    *,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    permission: DBIPermission,
) -> None:
    try:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=permission,
        )
    except DBIAccessDenied as error:
        raise _not_found() from error


def _read(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except (DBIAccessDenied, DBIInspectionUnavailable) as error:
        raise _not_found() from error
    except DBIInspectionConflict as error:
        raise _conflict() from error


def _write(session: Session, operation: Callable[[], T]) -> T:
    try:
        result = operation()
        session.commit()
        return result
    except (DBIAccessDenied, DBIInspectionUnavailable) as error:
        session.rollback()
        raise _not_found() from error
    except (DBIInspectionConflict, IntegrityError) as error:
        session.rollback()
        raise _conflict() from error


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/field-observations",
    response_model=DBIFieldObservationVersion,
    status_code=status.HTTP_201_CREATED,
)
def create_field_observation(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    payload: DBIFieldObservationCreateRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBIFieldObservationVersion:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )
    return _write(
        session,
        lambda: DBIFieldObservationService(session).create(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            request=payload,
        ),
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/field-observations/{observation_id}",
    response_model=DBIFieldObservationVersion,
)
def get_field_observation(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    observation_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> DBIFieldObservationVersion:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.READ,
    )
    return _read(
        lambda: DBIFieldObservationService(session).get_latest(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            observation_id=observation_id,
        )
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/field-observations/{observation_id}/versions",
    response_model=list[DBIFieldObservationVersion],
)
def list_field_observation_versions(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    observation_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> list[DBIFieldObservationVersion]:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.READ,
    )
    values = _read(
        lambda: DBIFieldObservationService(session).list_versions(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            observation_id=observation_id,
        )
    )
    return list(values)


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/field-observations/{observation_id}/corrections",
    response_model=DBIFieldObservationVersion,
)
def correct_field_observation(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    observation_id: UUID,
    payload: DBIFieldObservationCorrectionRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBIFieldObservationVersion:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )
    return _write(
        session,
        lambda: DBIFieldObservationService(session).correct(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            observation_id=observation_id,
            request=payload,
        ),
    )
