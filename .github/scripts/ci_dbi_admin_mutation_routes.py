"""Valida lectura y mutaciones HTTP de membresías administrativas DBI."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
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

from app.api.v1.dbi_admin import get_dbi_admin_service, router  # noqa: E402
from app.dbi.admin_dependencies import (  # noqa: E402
    get_dbi_admin_actor_state,
    get_dbi_admin_membership_state,
)
from app.dbi.admin_mutation_plan import plan_membership_mutation  # noqa: E402
from app.dbi.admin_policy import (  # noqa: E402
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminDenied,
    DBIAdminMembershipStatus,
    DBIAdminPolicy,
)
from app.dbi.admin_service import (  # noqa: E402
    DBIAdminGuardEvidence,
    DBIAdminMembershipMutationEvidence,
)
from app.dbi.admin_state import DBIAdminPersistedMembershipState  # noqa: E402
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.dependencies import get_dbi_session  # noqa: E402

TENANT = "tenant-a"
ORG = "organization-a"
NOW = datetime(2026, 8, 1, 19, 0, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeMutationService:
    def __init__(self, target: DBIAdminPersistedMembershipState) -> None:
        self.target = target
        self.failure: Exception | None = None
        self.last_expected_updated_at = None
        self.last_target_membership_id = None

    def mutate_membership(
        self,
        actor,
        before,
        after,
        *,
        actor_membership_id,
        target_membership_id,
        expected_updated_at,
        next_updated_at,
        correlation_ref,
    ) -> DBIAdminMembershipMutationEvidence:
        if self.failure is not None:
            raise self.failure
        assert before == self.target.authority
        assert expected_updated_at == self.target.membership_updated_at
        DBIAdminPolicy.require_membership_change(actor, before, after)
        self.last_expected_updated_at = expected_updated_at
        self.last_target_membership_id = target_membership_id
        plan = plan_membership_mutation(
            self.target,
            after,
            next_updated_at=next_updated_at,
            correlation_ref=correlation_ref,
        )
        return DBIAdminMembershipMutationEvidence(
            guard=DBIAdminGuardEvidence(
                tenant_ref=before.tenant_ref,
                organization_refs=frozenset(
                    set(before.all_organization_refs)
                    | set(after.all_organization_refs)
                ),
                lock_keys=(1,),
            ),
            plan=plan,
        )


def _state(
    *,
    principal_ref: str,
    membership_status: DBIAdminMembershipStatus,
    organization_ref: str = ORG,
) -> DBIAdminPersistedMembershipState:
    authority = DBIAdminAuthoritySnapshot(
        principal_ref=principal_ref,
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=membership_status,
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE}),
        organization_scopes=frozenset({organization_ref}),
    )
    return DBIAdminPersistedMembershipState(
        principal_id=uuid4(),
        membership_id=uuid4(),
        principal_updated_at=NOW,
        membership_updated_at=NOW,
        authority=authority,
    )


def _client(
    *,
    target_status: DBIAdminMembershipStatus = DBIAdminMembershipStatus.ACTIVE,
    actor_organization: str = ORG,
):
    actor = _state(
        principal_ref="legacy-admin-a",
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        organization_ref=actor_organization,
    )
    target = _state(
        principal_ref="legacy-user-a",
        membership_status=target_status,
    )
    session = FakeSession()
    service = FakeMutationService(target)
    app = FastAPI()
    app.include_router(router)

    def session_override():
        yield session

    app.dependency_overrides[get_dbi_session] = session_override
    app.dependency_overrides[get_dbi_admin_actor_state] = lambda: actor
    app.dependency_overrides[get_dbi_admin_membership_state] = lambda: target
    app.dependency_overrides[get_dbi_admin_service] = lambda: service
    return TestClient(app), session, service, actor, target


def _status_payload(correlation_ref: str) -> dict[str, str]:
    return {
        "expected_updated_at": NOW.isoformat(),
        "correlation_ref": correlation_ref,
    }


def validate_membership_read() -> None:
    client, _, _, _, target = _client()
    response = client.get(f"/dbi/admin/memberships/{target.membership_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["membership_id"] == str(target.membership_id)
    assert body["principal_id"] == str(target.principal_id)
    assert body["principal_ref"] == target.authority.principal_ref
    assert body["tenant_ref"] == TENANT
    assert body["status"] == "active"
    assert body["permissions"] == ["manage", "read"]

    denied_client, _, _, _, denied_target = _client(
        actor_organization="organization-b"
    )
    response = denied_client.get(
        f"/dbi/admin/memberships/{denied_target.membership_id}"
    )
    assert response.status_code == 404, response.text
    assert response.json() == {
        "detail": "Recurso administrativo DBI no encontrado."
    }


def validate_complete_update() -> None:
    client, session, service, _, target = _client()
    response = client.patch(
        f"/dbi/admin/memberships/{target.membership_id}",
        json={
            "expected_updated_at": NOW.isoformat(),
            "status": "inactive",
            "permissions": ["read"],
            "organization_scopes": [ORG],
            "farm_scopes": [],
            "plot_scopes": [],
            "correlation_ref": "membership-update-a",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["membership_id"] == str(target.membership_id)
    assert body["applied"] is True
    assert body["status"] == "inactive"
    assert body["permissions"] == ["read"]
    assert body["affected_organization_refs"] == [ORG]
    assert service.last_target_membership_id == target.membership_id
    assert service.last_expected_updated_at == NOW
    assert session.commits == 1
    assert session.rollbacks == 0


def validate_status_routes() -> None:
    for suffix, expected_status in (
        ("deactivate", "inactive"),
        ("revoke", "revoked"),
    ):
        client, session, _, _, target = _client()
        response = client.post(
            f"/dbi/admin/memberships/{target.membership_id}/{suffix}",
            json=_status_payload(f"membership-{suffix}-a"),
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == expected_status
        assert response.json()["applied"] is True
        assert session.commits == 1

    client, session, _, _, target = _client(
        target_status=DBIAdminMembershipStatus.INACTIVE
    )
    response = client.post(
        f"/dbi/admin/memberships/{target.membership_id}/reactivate",
        json=_status_payload("membership-reactivate-a"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    assert response.json()["applied"] is True
    assert session.commits == 1


def validate_uniform_mutation_errors() -> None:
    client, session, service, _, target = _client()
    service.failure = DBIAdminDenied()
    response = client.post(
        f"/dbi/admin/memberships/{target.membership_id}/deactivate",
        json=_status_payload("membership-denied-a"),
    )
    assert response.status_code == 404, response.text
    assert response.json() == {
        "detail": "Recurso administrativo DBI no encontrado."
    }
    assert session.rollbacks == 1

    service.failure = DBIAdminConflict()
    response = client.post(
        f"/dbi/admin/memberships/{target.membership_id}/deactivate",
        json=_status_payload("membership-conflict-a"),
    )
    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": (
            "La operación administrativa DBI entra en conflicto "
            "con el estado actual."
        )
    }
    assert session.rollbacks == 2


def validate_revoked_is_immutable() -> None:
    client, session, service, _, target = _client(
        target_status=DBIAdminMembershipStatus.REVOKED
    )
    service.target = replace(
        target,
        authority=replace(
            target.authority,
            membership_status=DBIAdminMembershipStatus.REVOKED,
        ),
    )
    response = client.post(
        f"/dbi/admin/memberships/{target.membership_id}/reactivate",
        json=_status_payload("membership-revoked-reactivate-a"),
    )
    assert response.status_code == 409, response.text
    assert session.rollbacks == 1


def main() -> None:
    validate_membership_read()
    validate_complete_update()
    validate_status_routes()
    validate_uniform_mutation_errors()
    validate_revoked_is_immutable()
    print("Rutas administrativas DBI: lectura y mutaciones aprobadas.")


if __name__ == "__main__":
    main()
