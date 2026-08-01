"""Consulta HTTP autorizada de principales administrativos DBI."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.dbi.admin_dependencies import AdminActorDependency
from app.dbi.admin_policy import DBIAdminConflict, DBIAdminDenied, DBIAdminPolicy
from app.dbi.admin_principal_reader import (
    DBIAdminPrincipalNotFound,
    DBIAdminPrincipalReader,
)
from app.dbi.admin_principal_schemas import (
    DBIAdminPrincipalLookupQuery,
    DBIAdminPrincipalReadResponse,
)
from app.dbi.dependencies import get_dbi_session
from app.dbi.models.identity import DBIPrincipalStatus

router = APIRouter(prefix="/dbi/admin", tags=["dbi-admin"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
OrganizationQuery = Annotated[
    list[str],
    Query(alias="organization_ref", min_length=1),
]

DBI_ADMIN_NOT_FOUND_DETAIL = "Recurso administrativo DBI no encontrado."
DBI_ADMIN_CONFLICT_DETAIL = (
    "La operación administrativa DBI entra en conflicto con el estado actual."
)
DBI_ADMIN_QUERY_INVALID_DETAIL = "Parámetros administrativos DBI inválidos."


def get_dbi_admin_principal_reader(
    session: SessionDependency,
) -> DBIAdminPrincipalReader:
    """Construye el lector sobre la sesión DBI de la solicitud."""

    return DBIAdminPrincipalReader(session)


PrincipalReaderDependency = Annotated[
    DBIAdminPrincipalReader,
    Depends(get_dbi_admin_principal_reader),
]


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


def _lookup_query(organization_refs: list[str]) -> DBIAdminPrincipalLookupQuery:
    try:
        return DBIAdminPrincipalLookupQuery(
            organization_refs=tuple(organization_refs)
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DBI_ADMIN_QUERY_INVALID_DETAIL,
        ) from error


@router.get(
    "/principals/{legacy_identity_ref}",
    response_model=DBIAdminPrincipalReadResponse,
)
def get_principal(
    legacy_identity_ref: str,
    organization_ref: OrganizationQuery,
    actor: AdminActorDependency,
    reader: PrincipalReaderDependency,
) -> DBIAdminPrincipalReadResponse:
    """Consulta un principal global bajo cobertura organizacional explícita."""

    query = _lookup_query(organization_ref)
    try:
        DBIAdminPolicy.require_organization_control(
            actor.authority,
            tenant_ref=actor.authority.tenant_ref,
            organization_refs=query.organization_set,
        )
        principal = reader.resolve(
            legacy_identity_ref=legacy_identity_ref,
        )
    except (DBIAdminDenied, DBIAdminPrincipalNotFound) as error:
        raise _not_found() from error
    except (DBIAdminConflict, TypeError, ValueError) as error:
        raise _conflict() from error

    return DBIAdminPrincipalReadResponse(
        principal_id=principal.id,
        legacy_identity_ref=principal.legacy_identity_ref,
        active=principal.status == DBIPrincipalStatus.ACTIVE.value,
        created_at=principal.created_at,
        updated_at=principal.updated_at,
    )
