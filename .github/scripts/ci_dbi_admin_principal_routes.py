"""Valida consulta HTTP autorizada de principales DBI sin conexiones."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "dbi-ci-placeholder")
os.environ.setdefault("ENABLE_DOCS", "0")

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.v1.dbi_admin_principals import (  # noqa: E402
    get_dbi_admin_principal_reader,
    router,
)
from app.dbi.admin_dependencies import get_dbi_admin_actor_state  # noqa: E402
from app.dbi.admin_policy import (  # noqa: E402
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminMembershipStatus,
)
from app.dbi.admin_principal_reader import DBIAdminPrincipalNotFound  # noqa: E402
from app.dbi.admin_state import DBIAdminPersistedMembershipState  # noqa: E402
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.models.identity import (  # noqa: E402
    DBIPrincipal,
    DBIPrincipalStatus,
)

TENANT = "tenant-a"
ORG = "organization-a"
NOW = datetime(2026, 8, 1, 20, 0, tzinfo=timezone.utc)


class FakePrincipalReader:
    def __init__(self, principal: DBIPrincipal) -> None:
        self.principal = principal
        self.failure: Exception | None = None
        self.calls = 0

    def resolve(self, *, legacy_identity_ref: str) -> DBIPrincipal:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        if legacy_identity_ref != self.principal.legacy_identity_ref:
            raise DBIAdminPrincipalNotFound()
        return self.principal


def _actor(organization_ref: str = ORG) -> DBIAdminPersistedMembershipState:
    return DBIAdminPersistedMembershipState(
        principal_id=uuid4(),
        membership_id=uuid4(),
        principal_updated_at=NOW,
        membership_updated_at=NOW,
        authority=DBIAdminAuthoritySnapshot(
            principal_ref="legacy-admin-a",
            tenant_ref=TENANT,
            principal_active=True,
            membership_status=DBIAdminMembershipStatus.ACTIVE,
            permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE}),
            organization_scopes=frozenset({organization_ref}),
        ),
    )


def _principal(
    status_value: str = DBIPrincipalStatus.ACTIVE.value,
) -> DBIPrincipal:
    return DBIPrincipal(
        id=uuid4(),
        legacy_identity_ref="legacy-user-a",
        status=status_value,
        created_at=NOW,
        updated_at=NOW,
    )


def _client(
    *,
    actor_organization: str = ORG,
    principal_status: str = DBIPrincipalStatus.ACTIVE.value,
):
    actor = _actor(actor_organization)
    reader = FakePrincipalReader(_principal(principal_status))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_dbi_admin_actor_state] = lambda: actor
    app.dependency_overrides[get_dbi_admin_principal_reader] = lambda: reader
    return TestClient(app), reader


def validate_authorized_lookup() -> None:
    client, reader = _client()
    response = client.get(
        "/dbi/admin/principals/legacy-user-a",
        params=[("organization_ref", ORG)],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["principal_id"] == str(reader.principal.id)
    assert body["legacy_identity_ref"] == "legacy-user-a"
    assert body["active"] is True
    assert reader.calls == 1

    inactive_client, inactive_reader = _client(
        principal_status=DBIPrincipalStatus.INACTIVE.value
    )
    response = inactive_client.get(
        "/dbi/admin/principals/legacy-user-a",
        params=[("organization_ref", ORG)],
    )
    assert response.status_code == 200, response.text
    assert response.json()["active"] is False
    assert inactive_reader.calls == 1


def validate_authorization_precedes_lookup() -> None:
    client, reader = _client(actor_organization="organization-b")
    response = client.get(
        "/dbi/admin/principals/legacy-user-a",
        params=[("organization_ref", ORG)],
    )
    assert response.status_code == 404, response.text
    assert response.json() == {
        "detail": "Recurso administrativo DBI no encontrado."
    }
    assert reader.calls == 0


def validate_query_contract() -> None:
    client, reader = _client()
    response = client.get("/dbi/admin/principals/legacy-user-a")
    assert response.status_code == 422, response.text
    assert reader.calls == 0

    response = client.get(
        "/dbi/admin/principals/legacy-user-a",
        params=[("organization_ref", ORG), ("organization_ref", ORG)],
    )
    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "Parámetros administrativos DBI inválidos."
    }
    assert reader.calls == 0

    response = client.get(
        "/dbi/admin/principals/legacy-user-a",
        params=[("organization_ref", "all")],
    )
    assert response.status_code == 422, response.text
    assert reader.calls == 0


def validate_uniform_lookup_errors() -> None:
    client, reader = _client()
    reader.failure = DBIAdminPrincipalNotFound()
    response = client.get(
        "/dbi/admin/principals/legacy-user-a",
        params=[("organization_ref", ORG)],
    )
    assert response.status_code == 404, response.text

    reader.failure = DBIAdminConflict()
    response = client.get(
        "/dbi/admin/principals/legacy-user-a",
        params=[("organization_ref", ORG)],
    )
    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": (
            "La operación administrativa DBI entra en conflicto "
            "con el estado actual."
        )
    }


def main() -> None:
    validate_authorized_lookup()
    validate_authorization_precedes_lookup()
    validate_query_contract()
    validate_uniform_lookup_errors()
    print("Rutas administrativas DBI: consulta de principales aprobada.")


if __name__ == "__main__":
    main()
