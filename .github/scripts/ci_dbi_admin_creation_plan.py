"""Valida planes puros de altas administrativas DBI offline."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_creation_plan import (  # noqa: E402
    DBIAdminCreationAction,
    plan_membership_creation,
    plan_principal_registration,
)
from app.dbi.admin_policy import (  # noqa: E402
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminMembershipStatus,
)
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.models.admin_audit import (  # noqa: E402
    DBI_ADMIN_AUDIT_ACTION_VALUES,
)

TENANT = "tenant-a"
ORG_A = "organization-a"
ORG_B = "organization-b"
LOCAL_TIME = datetime(
    2026,
    8,
    1,
    10,
    0,
    tzinfo=timezone(timedelta(hours=-5)),
)
UTC_TIME = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)


def _requested(
    *,
    principal_active: bool = True,
    status: DBIAdminMembershipStatus = DBIAdminMembershipStatus.ACTIVE,
    organization_scopes: frozenset[str] = frozenset({ORG_A, ORG_B}),
) -> DBIAdminAuthoritySnapshot:
    return DBIAdminAuthoritySnapshot(
        principal_ref="principal-target",
        tenant_ref=TENANT,
        principal_active=principal_active,
        membership_status=status,
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=organization_scopes,
    )


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAdminConflict:
        return
    raise AssertionError("El plan de alta divergente debía producir conflicto.")


def validate_principal_registration_plan() -> None:
    principal_id = UUID("10000000-0000-0000-0000-000000000001")
    plan = plan_principal_registration(
        principal_id=principal_id,
        legacy_identity_ref="legacy-target",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_B, ORG_A}),
        occurred_at=LOCAL_TIME,
        correlation_ref="request-principal-001",
    )
    assert plan.principal_id == principal_id
    assert plan.legacy_identity_ref == "legacy-target"
    assert plan.tenant_ref == TENANT
    assert plan.organization_refs == frozenset({ORG_A, ORG_B})
    assert plan.occurred_at == UTC_TIME
    assert tuple(event.organization_ref for event in plan.audit_events) == (
        ORG_A,
        ORG_B,
    )
    assert all(
        event.action is DBIAdminCreationAction.PRINCIPAL_REGISTERED
        and event.resource_type == "principal"
        and event.resource_ref == str(principal_id)
        and event.correlation_ref == "request-principal-001"
        for event in plan.audit_events
    )


def validate_membership_creation_plan() -> None:
    principal_id = UUID("10000000-0000-0000-0000-000000000002")
    membership_id = UUID("20000000-0000-0000-0000-000000000001")
    requested = _requested()
    plan = plan_membership_creation(
        membership_id=membership_id,
        principal_id=principal_id,
        requested=requested,
        occurred_at=LOCAL_TIME,
        correlation_ref="request-membership-001",
    )
    assert plan.membership_id == membership_id
    assert plan.principal_id == principal_id
    assert plan.requested is requested
    assert plan.occurred_at == UTC_TIME
    assert tuple(event.organization_ref for event in plan.audit_events) == (
        ORG_A,
        ORG_B,
    )
    assert all(
        event.action is DBIAdminCreationAction.MEMBERSHIP_CREATED
        and event.resource_type == "membership"
        and event.resource_ref == str(membership_id)
        and event.correlation_ref == "request-membership-001"
        for event in plan.audit_events
    )


def validate_closed_rejections() -> None:
    _assert_conflict(
        lambda: plan_principal_registration(
            principal_id="not-a-uuid",  # type: ignore[arg-type]
            legacy_identity_ref="legacy-target",
            tenant_ref=TENANT,
            organization_refs=frozenset({ORG_A}),
            occurred_at=UTC_TIME,
            correlation_ref="request-001",
        )
    )
    for invalid_ref in ("", " any ", "*", "target*", " leading"):
        _assert_conflict(
            lambda invalid_ref=invalid_ref: plan_principal_registration(
                principal_id=uuid4(),
                legacy_identity_ref=invalid_ref,
                tenant_ref=TENANT,
                organization_refs=frozenset({ORG_A}),
                occurred_at=UTC_TIME,
                correlation_ref="request-001",
            )
        )
    _assert_conflict(
        lambda: plan_principal_registration(
            principal_id=uuid4(),
            legacy_identity_ref="legacy-target",
            tenant_ref=TENANT,
            organization_refs=frozenset(),
            occurred_at=UTC_TIME,
            correlation_ref="request-001",
        )
    )
    _assert_conflict(
        lambda: plan_principal_registration(
            principal_id=uuid4(),
            legacy_identity_ref="legacy-target",
            tenant_ref=TENANT,
            organization_refs=frozenset({ORG_A}),
            occurred_at=UTC_TIME.replace(tzinfo=None),
            correlation_ref="request-001",
        )
    )

    for requested in (
        _requested(principal_active=False),
        _requested(status=DBIAdminMembershipStatus.INACTIVE),
        _requested(status=DBIAdminMembershipStatus.REVOKED),
        _requested(organization_scopes=frozenset()),
    ):
        _assert_conflict(
            lambda requested=requested: plan_membership_creation(
                membership_id=uuid4(),
                principal_id=uuid4(),
                requested=requested,
                occurred_at=UTC_TIME,
                correlation_ref="request-membership-001",
            )
        )


def validate_action_contract_and_boundaries() -> None:
    assert {action.value for action in DBIAdminCreationAction} == {
        "principal_registered",
        "membership_created",
    }
    assert set(action.value for action in DBIAdminCreationAction).issubset(
        DBI_ADMIN_AUDIT_ACTION_VALUES
    )

    source = (
        BACKEND / "app" / "dbi" / "admin_creation_plan.py"
    ).read_text(encoding="utf-8").lower()
    for required in (
        "plan_principal_registration",
        "plan_membership_creation",
        "principal_registered",
        "membership_created",
        "membership_status is not dbiadminmembershipstatus.active",
    ):
        assert required in source
    for forbidden in (
        "sqlalchemy",
        "session",
        "create_engine",
        "sessionmaker",
        "fastapi",
        "database_url",
        ".execute(",
        ".add(",
        ".commit(",
        ".rollback(",
        "insert(",
        "update(",
        "delete(",
    ):
        assert forbidden not in source


def main() -> None:
    validate_principal_registration_plan()
    validate_membership_creation_plan()
    validate_closed_rejections()
    validate_action_contract_and_boundaries()
    print("Planes puros de altas administrativas DBI aprobados offline.")


if __name__ == "__main__":
    main()
