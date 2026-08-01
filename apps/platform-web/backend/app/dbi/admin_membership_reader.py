"""Lectura cerrada de membresías objetivo para la frontera administrativa DBI."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.dbi.admin_policy import DBIAdminConflict
from app.dbi.admin_repository import DBIAdminRepository
from app.dbi.admin_state import (
    DBIAdminPersistedMembershipState,
    build_admin_membership_state,
)
from app.dbi.models.identity import DBIMembership, DBIPrincipal


class DBIAdminMembershipNotFound(LookupError):
    """Ausencia uniforme que no revela si el recurso existe en otro tenant."""


class DBIAdminMembershipReader:
    """Reconstruye una membresía por ID dentro de un tenant exacto."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session debe ser una sesión SQLAlchemy DBI.")
        self._session = session
        self._repository = DBIAdminRepository(session)

    def resolve(
        self,
        *,
        membership_id: UUID,
        tenant_ref: str,
    ) -> DBIAdminPersistedMembershipState:
        if not isinstance(membership_id, UUID):
            raise TypeError("membership_id debe ser UUID.")
        if not isinstance(tenant_ref, str) or not tenant_ref.strip():
            raise TypeError("tenant_ref debe ser una referencia no vacía.")

        membership = self._session.get(DBIMembership, membership_id)
        if (
            not isinstance(membership, DBIMembership)
            or membership.id != membership_id
            or membership.tenant_ref != tenant_ref
        ):
            raise DBIAdminMembershipNotFound()

        principal = self._session.get(DBIPrincipal, membership.principal_id)
        if (
            not isinstance(principal, DBIPrincipal)
            or principal.id != membership.principal_id
        ):
            raise DBIAdminConflict()

        return build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=self._repository.list_permissions(
                membership_id=membership.id,
            ),
            scopes=self._repository.list_scopes(
                membership_id=membership.id,
            ),
        )
