"""Dependencias FastAPI aisladas para sesiones y autorización DBI."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.identity import DBIAccessContextResolver, DBIIdentityRepository
from app.dbi.runtime import DBIRuntime, DBIRuntimeUnavailable

DBI_ACCESS_DENIED_DETAIL = "Acceso DBI denegado."
DBI_UNAVAILABLE_DETAIL = "El servicio DBI no está disponible."


def _get_runtime(request: Request) -> DBIRuntime:
    runtime = getattr(request.app.state, "dbi_runtime", None)
    if not isinstance(runtime, DBIRuntime):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DBI_UNAVAILABLE_DETAIL,
        )
    return runtime


def get_dbi_session(request: Request) -> Generator[Session, None, None]:
    """Entrega una sesión DBI diferida con rollback y cierre garantizados."""

    try:
        session_factory = _get_runtime(request).require_session_factory()
    except DBIRuntimeUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DBI_UNAVAILABLE_DETAIL,
        ) from error

    session = session_factory()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _legacy_identity_ref(authenticated_user: object) -> str:
    """Convierte la identidad heredada en referencia opaca para DBI."""

    user_id = getattr(authenticated_user, "id", None)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DBI_ACCESS_DENIED_DETAIL,
        )
    return str(user_id)


def get_dbi_access_context(
    authenticated_user: Annotated[object, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_dbi_session)],
    tenant_ref: Annotated[str, Header(alias="X-DBI-Tenant")],
) -> DBIAccessContext:
    """Resuelve el contexto DBI usando exclusivamente autoridad DBI."""

    repository = DBIIdentityRepository(session)
    resolver = DBIAccessContextResolver(repository)
    try:
        return resolver.resolve(
            legacy_identity_ref=_legacy_identity_ref(authenticated_user),
            tenant_ref=tenant_ref,
        )
    except DBIAccessDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DBI_ACCESS_DENIED_DETAIL,
        ) from error
