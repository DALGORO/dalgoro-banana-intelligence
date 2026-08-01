"""Valida planes administrativos DBI sin SQL ni efectos laterales."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_mutation_plan import (  # noqa: E402
    DBIAdminMutationAction,
    plan_membership_mutation,
)
from app.dbi.admin_policy import (  # noqa: E402
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminMembershipStatus,
)
from app.dbi.admin_state import DBIAdminPersistedMembershipState  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIFarmScope,
    DBIPermission,
)
from app.dbi.models.admin_audit import DBIAdminAuditAction  # noqa: E402

TENANT = "tenant-a"
ORG_A = "organization-a"
ORG_B = "organization-b"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _authority(
    *,
    principal_ref: str = "principal-target",
    tenant_ref: str = TENANT,
    membership_status: DBIAdminMembershipStatus = DBIAdminMembershipStatus.ACTIVE,
    permissions: frozenset[DBIPermission] | None = None,
    organization_scopes: frozenset[str] | None = None,
    farm_scopes: frozenset[DBIFarmScope] | None = None,
) -> DBIAdminAuthoritySnapshot:
    return DBIAdminAuthoritySnapshot(
        principal_ref=principal_ref,
        tenant_ref=tenant_ref,
        principal_active=True,
        membership_status=membership_status,
        permissions=(
            permissions
            if permissions is not None
            else frozenset({DBIPermission.READ, DBIPermission.MANAGE})
        ),
        organization_scopes=(
            organization_scopes
            if organization_scopes is not None
            else frozenset({ORG_A})
        ),
        farm_scopes=farm_scopes or frozenset(),
    )


def _persisted(
    authority: DBIAdminAuthoritySnapshot | None = None,
) -> DBIAdminPersistedMembershipState:
    return DBIAdminPersistedMembershipState(
        principal_id=uuid4(),
        membership_id=uuid4(),
        principal_updated_at=NOW,
        membership_updated_at=NOW,
        authority=authority or _authority(),
    )


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAdminConflict:
        return
    raise AssertionError("El plan administrativo debía producir conflicto.")


def validate_no_op_is_idempotent() -> None:
    persisted = _persisted()
    plan = plan_membership_mutation(
        persisted,
        persisted.authority,
        next_updated_at=NOW + timedelta(seconds=10),
        correlation_ref="request-001",
    )
    assert plan.applied is False
    assert plan.changed_status is False
    assert plan.changed_permissions is False
    assert plan.changed_scopes is False
    assert plan.next_updated_at == NOW
    assert plan.audit_events == ()


def validate_combined_change_and_event_order() -> None:
    before = _authority(
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    persisted = _persisted(before)
    farm_scope = DBIFarmScope(
        organization_ref=ORG_A,
        farm_id=uuid4(),
    )
    after = _authority(
        membership_status=DBIAdminMembershipStatus.INACTIVE,
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A}),
        farm_scopes=frozenset({farm_scope}),
    )

    plan = plan_membership_mutation(
        persisted,
        after,
        next_updated_at=NOW + timedelta(microseconds=1),
        correlation_ref="request-002",
    )
    assert plan.applied is True
    assert plan.changed_status is True
    assert plan.changed_permissions is True
    assert plan.changed_scopes is True
    assert plan.affected_organization_refs == frozenset({ORG_A, ORG_B})
    assert plan.next_updated_at == NOW + timedelta(microseconds=1)

    expected_actions = (
        DBIAdminMutationAction.MEMBERSHIP_INACTIVATED,
        DBIAdminMutationAction.MEMBERSHIP_PERMISSIONS_REPLACED,
        DBIAdminMutationAction.MEMBERSHIP_SCOPES_REPLACED,
    )
    assert tuple(event.organization_ref for event in plan.audit_events) == (
        ORG_A,
        ORG_A,
        ORG_A,
        ORG_B,
        ORG_B,
        ORG_B,
    )
    assert tuple(event.action for event in plan.audit_events) == (
        expected_actions + expected_actions
    )
    assert all(
        event.resource_ref == str(persisted.membership_id)
        and event.resource_type == "membership"
        and event.correlation_ref == "request-002"
        for event in plan.audit_events
    )


def validate_status_actions() -> None:
    inactive = _authority(
        membership_status=DBIAdminMembershipStatus.INACTIVE,
    )
    activated = plan_membership_mutation(
        _persisted(inactive),
        _authority(membership_status=DBIAdminMembershipStatus.ACTIVE),
        next_updated_at=NOW + timedelta(seconds=1),
        correlation_ref="activate-001",
    )
    assert tuple(event.action for event in activated.audit_events) == (
        DBIAdminMutationAction.MEMBERSHIP_ACTIVATED,
    )

    revoked = plan_membership_mutation(
        _persisted(),
        _authority(membership_status=DBIAdminMembershipStatus.REVOKED),
        next_updated_at=NOW + timedelta(seconds=1),
        correlation_ref="revoke-001",
    )
    assert tuple(event.action for event in revoked.audit_events) == (
        DBIAdminMutationAction.MEMBERSHIP_REVOKED,
    )


def validate_identity_and_version_barriers() -> None:
    persisted = _persisted()
    next_version = NOW + timedelta(seconds=1)

    _assert_conflict(
        lambda: plan_membership_mutation(
            persisted,
            _authority(principal_ref="other-principal"),
            next_updated_at=next_version,
            correlation_ref="request-003",
        )
    )
    _assert_conflict(
        lambda: plan_membership_mutation(
            persisted,
            _authority(tenant_ref="tenant-b"),
            next_updated_at=next_version,
            correlation_ref="request-003",
        )
    )

    changed = _authority(permissions=frozenset({DBIPermission.READ}))
    _assert_conflict(
        lambda: plan_membership_mutation(
            persisted,
            changed,
            next_updated_at=NOW,
            correlation_ref="request-004",
        )
    )
    _assert_conflict(
        lambda: plan_membership_mutation(
            persisted,
            changed,
            next_updated_at=NOW - timedelta(microseconds=1),
            correlation_ref="request-004",
        )
    )
    _assert_conflict(
        lambda: plan_membership_mutation(
            persisted,
            changed,
            next_updated_at=next_version.replace(tzinfo=None),
            correlation_ref="request-004",
        )
    )

    for invalid_ref in ("", " request-005", "*", "all"):
        _assert_conflict(
            lambda invalid_ref=invalid_ref: plan_membership_mutation(
                persisted,
                persisted.authority,
                next_updated_at=next_version,
                correlation_ref=invalid_ref,
            )
        )


def validate_audit_action_alignment() -> None:
    persisted_actions = {action.value for action in DBIAdminAuditAction}
    planned_actions = {action.value for action in DBIAdminMutationAction}
    assert planned_actions <= persisted_actions
    assert planned_actions == {
        "membership_activated",
        "membership_inactivated",
        "membership_revoked",
        "membership_permissions_replaced",
        "membership_scopes_replaced",
    }


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "admin_mutation_plan.py"
    ).read_text(encoding="utf-8").lower()
    for required in (
        "class dbiadminmembershipmutationplan",
        "class dbiadminplannedauditevent",
        "requested_version <= persisted_version",
        "for organization_ref in sorted(organizations)",
    ):
        assert required in source

    for forbidden in (
        "sqlalchemy",
        "fastapi",
        "session",
        "create_engine",
        "sessionmaker",
        ".execute(",
        ".add(",
        ".delete(",
        ".commit(",
        ".rollback(",
        "database_url",
        "app.models.user",
        "app.models.company",
    ):
        assert forbidden not in source


def main() -> None:
    validate_no_op_is_idempotent()
    validate_combined_change_and_event_order()
    validate_status_actions()
    validate_identity_and_version_barriers()
    validate_audit_action_alignment()
    validate_static_boundaries()
    print("Plan puro de mutación administrativa DBI aprobado offline.")


if __name__ == "__main__":
    main()
