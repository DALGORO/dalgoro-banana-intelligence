"""Catálogo de fincas del cliente, sin solicitar tenant al navegador."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.dbi.dependencies import get_dbi_session
from app.dbi.portal import PortalAccount, read_portal_accounts

router = APIRouter(prefix="/dbi/portal", tags=["dbi-portal"])


@router.get("/accounts", response_model=list[PortalAccount])
def list_client_accounts(
    user: Annotated[object, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_dbi_session)],
) -> list[PortalAccount]:
    """El usuario sólo descubre recursos asociados a su membresía DBI."""
    return read_portal_accounts(
        session, authenticated_user_id=user.id,
    )
