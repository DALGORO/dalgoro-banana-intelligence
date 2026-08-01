"""Lectura cerrada de principales para la frontera administrativa DBI."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.dbi.admin_policy import DBIAdminConflict
from app.dbi.admin_repository import DBIAdminRepository
from app.dbi.models.identity import DBIPrincipal, DBIPrincipalStatus


class DBIAdminPrincipalNotFound(LookupError):
    """Ausencia uniforme de una identidad principal DBI."""


class DBIAdminPrincipalReader:
    """Resuelve exactamente un principal global mediante referencia opaca."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session debe ser una sesión SQLAlchemy DBI.")
        self._repository = DBIAdminRepository(session)

    def resolve(self, *, legacy_identity_ref: str) -> DBIPrincipal:
        if not isinstance(legacy_identity_ref, str):
            raise TypeError("legacy_identity_ref debe ser texto.")
        normalized = legacy_identity_ref.strip()
        if not normalized or normalized != legacy_identity_ref:
            raise DBIAdminPrincipalNotFound()

        rows = self._repository.list_principals_by_legacy_ref(
            legacy_identity_ref=normalized,
        )
        if not rows:
            raise DBIAdminPrincipalNotFound()
        if len(rows) != 1:
            raise DBIAdminConflict()

        principal = rows[0]
        if (
            not isinstance(principal, DBIPrincipal)
            or principal.legacy_identity_ref != normalized
            or principal.status
            not in {
                DBIPrincipalStatus.ACTIVE.value,
                DBIPrincipalStatus.INACTIVE.value,
            }
        ):
            raise DBIAdminConflict()
        return principal
