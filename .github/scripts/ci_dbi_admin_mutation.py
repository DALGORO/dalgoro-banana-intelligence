"""Valida planes administrativos DBI sin persistencia ni API."""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_mutation import (  # noqa: E402
    DBIAdminMembershipMutationPlan,
    DBIAdminMutationKind,
    plan_membership_mutation,
)
from app.dbi.admin_policy import (  # noqa: E402
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminMembershipStatus,
)
from app.dbi.authorization import (  # noqa: E402
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)

TENANT = "tenant-a"
ORG_A = "organization-a"
ORG_B = "organization-b"


def _snapshot(
    *,
    principal_ref: str = "principal-a",
    tenant_ref: str = TENANT,
    principal_active: bool = True,
    status: DBIAdminMembershipStatus = DBIAdminMembershipStatus.ACTIVE,
    permissions: frozenset[DBIPermission] | None = None,
    organization_scopes: frozenset[str] | None = None,
    farm_scopes: frozenset[DBIFarmScope] | None = None,
    plot_scopes: frozenset[DBIPlotScope] | None = None,
) -> DBIAdminAuthoritySnapshot:
    return DBIAdminAuthoritySnapshot(
        principal_ref=principal_ref,
        tenant_ref=tenant_ref,
        principal_active=principal_active,
        membership_status=status,
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
        plot_scopes=plot_scopes or frozenset(),
    )


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAdminConflict:
        return
    raise AssertionError("La mutación administrativa divergente debía rechazarse.")


def validate_noop_and_immutability() -> None:
    before = _snapshot()
    plan = plan_membership_mutation(before, before)
    assert isinstance(plan, DBIAdminMembershipMutationPlan)
    assert plan.kind is DBIAdminMutationKind.NOOP
    assert plan.has_changes is False
    assert plan.changes_authority is False
    assert plan.permissions_to_add == frozenset()
    assert plan.permissions_to_remove == frozenset()
    assert plan.admin_organizations_gained == frozenset()
    assert plan.admin_organizations_lost == frozenset()

    try:
        plan.kind = DBIAdminMutationKind.REVOKE  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("El plan administrativo debía ser inmutable.")


def validate_authority_delta() -> None:
    farm_a = DBIFarmScope(organization_ref=ORG_A, farm_id=uuid4())
    farm_b = DBIFarmScope(organization_ref=ORG_B, farm_id=uuid4())
    plot_a = DBIPlotScope(
        organization_ref=ORG_A,
        farm_id=farm_a.farm_id,
        plot_id=uuid4(),
    )
    plot_b = DBIPlotScope(
        organization_ref=ORG_B,
        farm_id=farm_b.farm_id,
        plot_id=uuid4(),
    )
    before = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE}),
        organization_scopes=frozenset({ORG_A}),
        farm_scopes=frozenset({farm_a}),
        plot_scopes=frozenset({plot_a}),
    )
    after = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.WRITE}),
        organization_scopes=frozenset({ORG_B}),
        farm_scopes=frozenset({farm_b}),
        plot_scopes=frozenset({plot_b}),
    )

    plan = plan_membership_mutation(before, after)
    assert plan.kind is DBIAdminMutationKind.UPDATE_AUTHORITY
    assert plan.has_changes is True
    assert plan.changes_authority is True
    assert plan.permissions_to_add == frozenset({DBIPermission.WRITE})
    assert plan.permissions_to_remove == frozenset({DBIPermission.MANAGE})
    assert plan.organization_scopes_to_add == frozenset({ORG_B})
    assert plan.organization_scopes_to_remove == frozenset({ORG_A})
    assert plan.farm_scopes_to_add == frozenset({farm_b})
    assert plan.farm_scopes_to_remove == frozenset({farm_a})
    assert plan.plot_scopes_to_add == frozenset({plot_b})
    assert plan.plot_scopes_to_remove == frozenset({plot_a})
    assert plan.affected_organization_refs == frozenset({ORG_A, ORG_B})
    assert plan.admin_organizations_gained == frozenset()
    assert plan.admin_organizations_lost == frozenset({ORG_A})


def validate_status_kinds() -> None:
    active = _snapshot()
    inactive = _snapshot(status=DBIAdminMembershipStatus.INACTIVE)
    revoked = _snapshot(status=DBIAdminMembershipStatus.REVOKED)

    deactivation = plan_membership_mutation(active, inactive)
    assert deactivation.kind is DBIAdminMutationKind.DEACTIVATE
    assert deactivation.changes_authority is False
    assert deactivation.admin_organizations_lost == frozenset({ORG_A})

    reactivation = plan_membership_mutation(inactive, active)
    assert reactivation.kind is DBIAdminMutationKind.REACTIVATE
    assert reactivation.admin_organizations_gained == frozenset({ORG_A})

    revocation = plan_membership_mutation(active, revoked)
    assert revocation.kind is DBIAdminMutationKind.REVOKE
    assert revocation.admin_organizations_lost == frozenset({ORG_A})

    _assert_conflict(lambda: plan_membership_mutation(revoked, active))
    _assert_conflict(
        lambda: plan_membership_mutation(
            revoked,
            _snapshot(
                status=DBIAdminMembershipStatus.REVOKED,
                permissions=frozenset({DBIPermission.READ}),
            ),
        )
    )


def validate_combined_status_and_authority_change() -> None:
    active = _snapshot()
    inactive_reduced = _snapshot(
        status=DBIAdminMembershipStatus.INACTIVE,
        permissions=frozenset({DBIPermission.READ}),
    )
    plan = plan_membership_mutation(active, inactive_reduced)
    assert plan.kind is DBIAdminMutationKind.DEACTIVATE
    assert plan.changes_authority is True
    assert plan.permissions_to_remove == frozenset({DBIPermission.MANAGE})
    assert plan.admin_organizations_lost == frozenset({ORG_A})

    inactive = _snapshot(status=DBIAdminMembershipStatus.INACTIVE)
    active_reduced = _snapshot(
        permissions=frozenset({DBIPermission.READ}),
    )
    reactivation = plan_membership_mutation(inactive, active_reduced)
    assert reactivation.kind is DBIAdminMutationKind.REACTIVATE
    assert reactivation.changes_authority is True
    assert reactivation.admin_organizations_gained == frozenset()


def validate_identity_barriers() -> None:
    before = _snapshot()
    _assert_conflict(
        lambda: plan_membership_mutation(
            before,
            _snapshot(principal_ref="principal-b"),
        )
    )
    _assert_conflict(
        lambda: plan_membership_mutation(
            before,
            _snapshot(tenant_ref="tenant-b"),
        )
    )
    _assert_conflict(
        lambda: plan_membership_mutation(
            before,
            _snapshot(principal_active=False),
        )
    )
    _assert_conflict(lambda: plan_membership_mutation(object(), before))


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "admin_mutation.py"
    ).read_text(encoding="utf-8").lower()

    for required in (
        "dbiadminmutationkind",
        "dbiadminmembershipmutationplan",
        "permissions_to_add",
        "organization_scopes_to_remove",
        "admin_organizations_gained",
        "admin_organizations_lost",
        "plan_membership_mutation",
    ):
        assert required in source

    for forbidden in (
        "sqlalchemy",
        "fastapi",
        "create_engine",
        "sessionmaker",
        "database_url",
        ".execute(",
        ".commit(",
        ".rollback(",
        "delete(",
        "drop table",
        "app.models.user",
        "app.models.company",
    ):
        assert forbidden not in source


def main() -> None:
    validate_noop_and_immutability()
    validate_authority_delta()
    validate_status_kinds()
    validate_combined_status_and_authority_change()
    validate_identity_barriers()
    validate_static_boundaries()
    print("Plan puro de mutación administrativa DBI aprobado offline.")


if __name__ == "__main__":
    main()
