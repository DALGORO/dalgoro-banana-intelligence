"""Valida rutas administrativas DBI de altas sin conexiones."""

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

from app.api.v1.dbi_admin import (  # noqa: E402
    get_dbi_admin_service,
    router,
)
from app.dbi.admin_creation_plan import (  # noqa: E402
    plan_membership_creation,
    plan_principal_registration,
)
from app.dbi.admin_dependencies import get_dbi_admin_actor_state  # noqa: E402
from app.dbi.admin_policy import (  # noqa: E402
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminDenied,
    DBIAdminMembershipStatus,
)
from app.dbi.admin_service import (  # noqa: E402
    DBIAdminGuardEvidence,
    DBIAdminMembershipCreationEvidence,
    DBIAdminPrincipalRegistrationEvidence,
)
from app.dbi.admin_state import DBIAdminPersistedMembershipState  # noqa: E402
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.dependencies import get_dbi_session  # noqa: E402

NOW = datetime(2026, 8, 1, 18, 30, tzinfo=timezone.utc)
TENANT = "tenant-a"
ORG = "organization-a"


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeAdminService:
    def __init__(self) -> None:
        self.created = True
        self.failure: Exception | None = None
        self.last_tenant_ref: str | None = None
        self.last_actor_membership_id = None

    def _raise_if_needed(self) -> None:
        if self.failure is not None:
            raise self.failure

    def register_principal(
        self,
        actor,
        *,
        actor_membership_id,
        principal_id,
        target_principal_ref,
        tenant_ref,
        organization_refs,
        occurred_at,
        correlation_ref,
    ):
        self._raise_if_needed()
        self.last_tenant_ref = tenant_ref
        self.last_actor_membership_id = actor_membership_id
        plan = plan_principal_registration(
            principal_id=principal_id,
            legacy_identity_ref=target_principal_ref,
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
            occurred_at=occurred_at,
            correlation_ref=correlation_ref,
        )
        return DBIAdminPrincipalRegistrationEvidence(
            guard=DBIAdminGuardEvidence(
                tenant_ref=tenant_ref,
                organization_refs=organization_refs,
                lock_keys=(1,),
            ),
            plan=plan,
            created=self.created,
        )

    def create_membership(
        self,
        actor,
        requested,
        *,
        actor_membership_id,
        membership_id,
        principal_id,
        occurred_at,
        correlation_ref,
    ):
        self._raise_if_needed()
        self.last_tenant_ref = requested.tenant_ref
        self.last_actor_membership_id = actor_membership_id
        plan = plan_membership_creation(
            membership_id=membership_id,
            principal_id=principal_id,
            requested=requested,
            occurred_at=occurred_at,
            correlation_ref=correlation_ref,
        )
        return DBIAdminMembershipCreationEvidence(
            guard=DBIAdminGuardEvidence(
                tenant_ref=requested.tenant_ref,
                organization_refs=requested.all_organization_refs,
                lock_keys=(1,),
            ),
            plan=plan,
            created=self.created,
        )


def _actor_state() -> DBIAdminPersistedMembershipState:
    authority = DBIAdminAuthoritySnapshot(
        principal_ref="legacy-admin-a",
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE}),
        organization_scopes=frozenset({ORG}),
    )
    return DBIAdminPersistedMembershipState(
        principal_id=uuid4(),
        membership_id=uuid4(),
        principal_updated_at=NOW,
        membership_updated_at=NOW,
        authority=authority,
    )


def _client():
    session = FakeSession()
    service = FakeAdminService()
    actor = _actor_state()
    app = FastAPI()
    app.include_router(router)

    def session_override():
        yield session

    app.dependency_overrides[get_dbi_session] = session_override
    app.dependency_overrides[get_dbi_admin_actor_state] = lambda: actor
    app.dependency_overrides[get_dbi_admin_service] = lambda: service
    return TestClient(app), session, service, actor


def validate_principal_route() -> None:
    client, session, service, actor = _client()
    principal_id = uuid4()
    payload = {
        "principal_id": str(principal_id),
        "legacy_identity_ref": "legacy-user-a",
        "organization_refs": [ORG],
        "correlation_ref": "principal-create-a",
    }
    response = client.post("/dbi/admin/principals", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["principal_id"] == str(principal_id)
    assert body["created"] is True
    assert body["organization_refs"] == [ORG]
    assert service.last_tenant_ref == TENANT
    assert service.last_actor_membership_id == actor.membership_id
    assert session.commits == 1
    assert session.rollbacks == 0

    service.created = False
    response = client.post("/dbi/admin/principals", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["created"] is False
    assert session.commits == 2


def validate_membership_route() -> None:
    client, session, service, actor = _client()
    membership_id = uuid4()
    principal_id = uuid4()
    response = client.post(
        "/dbi/admin/memberships",
        json={
            "membership_id": str(membership_id),
            "principal_id": str(principal_id),
            "principal_ref": "legacy-user-b",
            "permissions": ["read"],
            "organization_scopes": [ORG],
            "farm_scopes": [],
            "plot_scopes": [],
            "correlation_ref": "membership-create-a",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["membership_id"] == str(membership_id)
    assert body["principal_id"] == str(principal_id)
    assert body["tenant_ref"] == TENANT
    assert body["status"] == "active"
    assert body["permissions"] == ["read"]
    assert service.last_tenant_ref == actor.authority.tenant_ref
    assert session.commits == 1


def validate_uniform_errors() -> None:
    client, session, service, _ = _client()
    payload = {
        "principal_id": str(uuid4()),
        "legacy_identity_ref": "legacy-user-c",
        "organization_refs": [ORG],
        "correlation_ref": "principal-create-error",
    }

    service.failure = DBIAdminDenied()
    response = client.post("/dbi/admin/principals", json=payload)
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "Acceso administrativo DBI denegado."}
    assert session.rollbacks == 1

    service.failure = DBIAdminConflict()
    response = client.post("/dbi/admin/principals", json=payload)
    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": (
            "La operación administrativa DBI entra en conflicto "
            "con el estado actual."
        )
    }
    assert session.rollbacks == 2


def main() -> None:
    validate_principal_route()
    validate_membership_route()
    validate_uniform_errors()
    print("Rutas administrativas DBI: altas autorizadas aprobadas.")


if __name__ == "__main__":
    main()
