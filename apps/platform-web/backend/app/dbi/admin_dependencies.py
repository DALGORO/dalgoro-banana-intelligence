"""Dependencias FastAPI cerradas para la administración DBI."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dbi.admin_actor import DBIAdminActorRepository, DBIAdminActorResolver
from app.dbi.admin_membership_reader import (
    DBIAdminMembershipNotFound,
    DBIAdminMembershipReader,
)
from app.dbi.admin_policy import DBIAdminConflict
from app.dbi.admin_state import DBIAdminPersistedMembershipState
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session

DBI_ADMIN_ACCESS_DENIED_DETAIL = "Acceso administrativo DBI denegado."
DBI_ADMIN_RESOURCE_NOT_FOUND_DETAIL = "Recurso administrativo DBI no encontrado."

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[
    DBIAccessContext,
    Depends(get_dbi_access_context),
]
ActorDependency = Annotated[
    DBIAdminPersistedMembershipState,
    Depends(lambda: None),
]


def _admin_access_denied() -> HTTPException:
    """Construye una denegación uniforme sin revelar recursos internos."""

    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=DBI_ADMIN_ACCESS_DENIED_DETAIL,
    )


def _admin_resource_not_found() -> HTTPException:
    """Oculta ausencia y pertenencia a otro tenant tras un mismo 404."""

    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DBI_ADMIN_RESOURCE_NOT_FOUND_DETAIL,
    )


def get_dbi_admin_actor_state(
    session: SessionDependency,
    context: AccessDependency,
) -> DBIAdminPersistedMembershipState:
    """Resuelve al actor exclusivamente desde sesión y autoridad DBI.

    No acepta principal, membresía, permisos ni ámbitos desde cabeceras o
    payloads administrativos. El resolvedor vuelve a leer el agregado y exige
    coincidencia exacta con el contexto autenticado antes de entregar sus IDs y
    versiones internas a la frontera ``/dbi/admin``.
    """

    try:
        return DBIAdminActorResolver(
            DBIAdminActorRepository(session)
        ).resolve(context=context)
    except (DBIAdminConflict, TypeError, ValueError) as error:
        raise _admin_access_denied() from error


AdminActorDependency = Annotated[
    DBIAdminPersistedMembershipState,
    Depends(get_dbi_admin_actor_state),
]


def get_dbi_admin_membership_state(
    membership_id: UUID,
    session: SessionDependency,
    actor: AdminActorDependency,
) -> DBIAdminPersistedMembershipState:
    """Carga un objetivo solo dentro del tenant persistido del actor."""

    try:
        return DBIAdminMembershipReader(session).resolve(
            membership_id=membership_id,
            tenant_ref=actor.authority.tenant_ref,
        )
    except DBIAdminMembershipNotFound as error:
        raise _admin_resource_not_found() from error
    except (DBIAdminConflict, TypeError, ValueError) as error:
        raise _admin_access_denied() from error
