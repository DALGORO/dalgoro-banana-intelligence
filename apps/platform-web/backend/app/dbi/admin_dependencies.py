"""Dependencias FastAPI cerradas para la administración DBI."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dbi.admin_actor import DBIAdminActorRepository, DBIAdminActorResolver
from app.dbi.admin_policy import DBIAdminConflict
from app.dbi.admin_state import DBIAdminPersistedMembershipState
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session

DBI_ADMIN_ACCESS_DENIED_DETAIL = "Acceso administrativo DBI denegado."

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[
    DBIAccessContext,
    Depends(get_dbi_access_context),
]


def _admin_access_denied() -> HTTPException:
    """Construye una denegación uniforme sin revelar recursos internos."""

    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=DBI_ADMIN_ACCESS_DENIED_DETAIL,
    )


def get_dbi_admin_actor_state(
    session: SessionDependency,
    context: AccessDependency,
) -> DBIAdminPersistedMembershipState:
    """Resuelve al actor exclusivamente desde sesión y autoridad DBI.

    No acepta principal, membresía, permisos ni ámbitos desde cabeceras o
    payloads administrativos. El resolvedor vuelve a leer el agregado y exige
    coincidencia exacta con el contexto autenticado antes de entregar sus IDs y
    versiones internas a la futura frontera ``/dbi/admin``.
    """

    try:
        return DBIAdminActorResolver(
            DBIAdminActorRepository(session)
        ).resolve(context=context)
    except (DBIAdminConflict, TypeError, ValueError) as error:
        raise _admin_access_denied() from error
