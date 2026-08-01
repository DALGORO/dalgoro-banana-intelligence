"""Valida la política administrativa DBI sin sesiones ni servicios externos."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_policy import (  # noqa: E402
    ADMIN_CONFLICT_MESSAGE,
    ADMIN_DENIED_MESSAGE,
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminDenied,
    DBIAdminMembershipStatus,
    DBIAdminPolicy,
)
from app.dbi.authorization import (  # noqa: E402
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)

ORG_A = "organization-a"
ORG_B = "organization-b"
TENANT = "tenant-a"


def _snapshot(
    *,
    principal_ref: str = "principal-target",
    tenant_ref: str = TENANT,
    principal_active: bool = True,
    membership_active: bool = True,
    membership_revoked: bool = False,
    permissions: frozenset[DBIPermission] | None = None,
    organization_scopes: frozenset[str] | None = None,
    farm_scopes: frozenset[DBIFarmScope] | None = None,
    plot_scopes: frozenset[DBIPlotScope] | None = None,
) -> DBIAdminAuthoritySnapshot:
    if membership_active and membership_revoked:
        raise ValueError("Una membresía no puede estar activa y revocada.")
    membership_status = (
        DBIAdminMembershipStatus.REVOKED
        if membership_revoked
        else (
            DBIAdminMembershipStatus.ACTIVE
            if membership_active
            else DBIAdminMembershipStatus.INACTIVE
        )
    )
    return DBIAdminAuthoritySnapshot(
        principal_ref=principal_ref,
        tenant_ref=tenant_ref,
        principal_active=principal_active,
        membership_status=membership_status,
        permissions=(
            permissions
            if permissions is not None
            else frozenset(
                {
                    DBIPermission.READ,
                    DBIPermission.WRITE,
                    DBIPermission.MANAGE,
                }
            )
        ),
        organization_scopes=(
            organization_scopes
            if organization_scopes is not None
            else frozenset({ORG_A})
        ),
        farm_scopes=farm_scopes or frozenset(),
        plot_scopes=plot_scopes or frozenset(),
    )


def _actor(**overrides) -> DBIAdminAuthoritySnapshot:
    return _snapshot(principal_ref="principal-actor", **overrides)


def _assert_denied(factory) -> None:
    try:
        factory()
    except DBIAdminDenied as error:
        assert str(error) == ADMIN_DENIED_MESSAGE
        return
    raise AssertionError("La operación administrativa debía ser denegada.")


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAdminConflict as error:
        assert str(error) == ADMIN_CONFLICT_MESSAGE
        return
    raise AssertionError("La operación administrativa debía producir conflicto.")


def validate_snapshot_contract() -> None:
    farm_id = uuid4()
    plot_id = uuid4()
    farm_scope = DBIFarmScope(organization_ref=ORG_A, farm_id=farm_id)
    plot_scope = DBIPlotScope(
        organization_ref=ORG_A,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    snapshot = _snapshot(
        farm_scopes=frozenset({farm_scope}),
        plot_scopes=frozenset({plot_scope}),
    )
    assert snapshot.membership_status is DBIAdminMembershipStatus.ACTIVE
    assert snapshot.membership_active is True
    assert snapshot.all_organization_refs == frozenset({ORG_A})
    assert snapshot.effective_admin_organizations == frozenset({ORG_A})

    inactive = _snapshot(principal_active=False)
    assert inactive.effective_admin_organizations == frozenset()

    revoked = _snapshot(membership_active=False, membership_revoked=True)
    assert revoked.membership_status is DBIAdminMembershipStatus.REVOKED
    assert revoked.membership_active is False
    assert revoked.effective_admin_organizations == frozenset()

    no_manage = _snapshot(permissions=frozenset({DBIPermission.READ}))
    assert no_manage.effective_admin_organizations == frozenset()

    try:
        _snapshot(plot_scopes=frozenset({plot_scope}))
    except ValueError:
        pass
    else:
        raise AssertionError("Un lote sin finca padre debía rechazarse.")


def validate_organization_control() -> None:
    actor = _actor(organization_scopes=frozenset({ORG_A, ORG_B}))
    DBIAdminPolicy.require_organization_control(
        actor,
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_A, ORG_B}),
    )

    _assert_denied(
        lambda: DBIAdminPolicy.require_organization_control(
            _actor(permissions=frozenset({DBIPermission.READ})),
            tenant_ref=TENANT,
            organization_refs=frozenset({ORG_A}),
        )
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_organization_control(
            actor,
            tenant_ref="tenant-b",
            organization_refs=frozenset({ORG_A}),
        )
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_organization_control(
            actor,
            tenant_ref=TENANT,
            organization_refs=frozenset(),
        )
    )

    farm_only_actor = _actor(
        organization_scopes=frozenset(),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref=ORG_A, farm_id=uuid4())}
        ),
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_organization_control(
            farm_only_actor,
            tenant_ref=TENANT,
            organization_refs=frozenset({ORG_A}),
        )
    )


def validate_principal_registration() -> None:
    actor = _actor(organization_scopes=frozenset({ORG_A}))
    DBIAdminPolicy.require_principal_registration(
        actor,
        target_principal_ref="principal-target",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_A}),
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_principal_registration(
            actor,
            target_principal_ref="principal-actor",
            tenant_ref=TENANT,
            organization_refs=frozenset({ORG_A}),
        )
    )


def validate_membership_create_and_change() -> None:
    actor = _actor(organization_scopes=frozenset({ORG_A, ORG_B}))
    requested = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.WRITE}),
        organization_scopes=frozenset({ORG_A}),
    )
    DBIAdminPolicy.require_membership_create(actor, requested)

    excessive_permission = _snapshot(
        permissions=frozenset(
            {DBIPermission.READ, DBIPermission.APPROVE_AGRONOMIC}
        ),
        organization_scopes=frozenset({ORG_A}),
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_membership_create(
            actor,
            excessive_permission,
        )
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_membership_create(
            actor,
            _snapshot(
                membership_active=False,
                organization_scopes=frozenset({ORG_A}),
            ),
        )
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_membership_create(
            actor,
            _snapshot(
                membership_active=False,
                membership_revoked=True,
                organization_scopes=frozenset({ORG_A}),
            ),
        )
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_membership_create(
            actor,
            _snapshot(
                principal_active=False,
                organization_scopes=frozenset({ORG_A}),
            ),
        )
    )

    actor_org_a = _actor(organization_scopes=frozenset({ORG_A}))
    multiorganization = _snapshot(
        organization_scopes=frozenset({ORG_A, ORG_B})
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_membership_change(
            actor_org_a,
            multiorganization,
            multiorganization,
        )
    )

    before = _snapshot(organization_scopes=frozenset({ORG_A, ORG_B}))
    after = _snapshot(
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    DBIAdminPolicy.require_membership_change(actor, before, after)

    changed_identity = _snapshot(
        principal_ref="another-principal",
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    _assert_conflict(
        lambda: DBIAdminPolicy.require_membership_change(
            actor,
            before,
            changed_identity,
        )
    )

    changed_principal_status = _snapshot(
        principal_active=False,
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    _assert_conflict(
        lambda: DBIAdminPolicy.require_membership_change(
            actor,
            before,
            changed_principal_status,
        )
    )

    revoked_before = _snapshot(
        membership_active=False,
        membership_revoked=True,
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    _assert_conflict(
        lambda: DBIAdminPolicy.require_membership_change(
            actor,
            revoked_before,
            before,
        )
    )
    revoked_changed = _snapshot(
        membership_active=False,
        membership_revoked=True,
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    _assert_conflict(
        lambda: DBIAdminPolicy.require_membership_change(
            actor,
            revoked_before,
            revoked_changed,
        )
    )
    DBIAdminPolicy.require_membership_change(
        actor,
        revoked_before,
        revoked_before,
    )


def validate_self_change_rules() -> None:
    before = _snapshot(
        principal_ref="principal-actor",
        permissions=frozenset(
            {DBIPermission.READ, DBIPermission.WRITE, DBIPermission.MANAGE}
        ),
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    actor = before

    reduced = _snapshot(
        principal_ref="principal-actor",
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE}),
        organization_scopes=frozenset({ORG_A}),
    )
    DBIAdminPolicy.require_membership_change(actor, before, reduced)

    mismatched_actor = _actor(
        organization_scopes=frozenset({ORG_A, ORG_B}),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref=ORG_A, farm_id=uuid4())}
        ),
    )
    _assert_conflict(
        lambda: DBIAdminPolicy.require_membership_change(
            mismatched_actor,
            before,
            reduced,
        )
    )

    expanded = _snapshot(
        principal_ref="principal-actor",
        permissions=before.permissions,
        organization_scopes=frozenset({ORG_A, ORG_B, "organization-c"}),
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_membership_change(
            actor,
            before,
            expanded,
        )
    )

    inactive_before = _snapshot(
        principal_ref="principal-actor",
        membership_active=False,
        organization_scopes=frozenset({ORG_A}),
    )
    reactivated = _snapshot(
        principal_ref="principal-actor",
        organization_scopes=frozenset({ORG_A}),
    )
    _assert_conflict(
        lambda: DBIAdminPolicy.require_membership_change(
            actor,
            inactive_before,
            reactivated,
        )
    )
    _assert_denied(
        lambda: DBIAdminPolicy.require_membership_change(
            inactive_before,
            inactive_before,
            reactivated,
        )
    )

    _assert_denied(
        lambda: DBIAdminPolicy.require_membership_create(
            actor,
            before,
        )
    )


def validate_last_admin_protection() -> None:
    before = _snapshot(
        organization_scopes=frozenset({ORG_A, ORG_B})
    )
    after = _snapshot(
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    affected = DBIAdminPolicy.organizations_losing_last_admin_protection(
        before,
        after,
    )
    assert affected == frozenset({ORG_A, ORG_B})

    DBIAdminPolicy.require_remaining_administrators(
        affected,
        {ORG_A: 1, ORG_B: 2},
    )
    _assert_conflict(
        lambda: DBIAdminPolicy.require_remaining_administrators(
            affected,
            {ORG_A: 1, ORG_B: 0},
        )
    )
    _assert_conflict(
        lambda: DBIAdminPolicy.require_remaining_administrators(
            affected,
            {ORG_A: 1},
        )
    )

    inactive = _snapshot(
        membership_active=False,
        organization_scopes=frozenset({ORG_A}),
    )
    assert inactive.effective_admin_organizations == frozenset()


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "admin_policy.py"
    ).read_text(encoding="utf-8").lower()
    assert "dbipermission.manage" in source
    assert "effective_admin_organizations" in source
    assert "require_principal_registration" in source
    assert "before.principal_active != after.principal_active" in source
    assert "dbiadminmembershipstatus.revoked" in source
    assert "actor != before" in source
    assert "and after != before" in source
    assert "require_remaining_administrators" in source
    assert "require_principal_change" not in source
    assert "activates_principal" not in source

    for forbidden in (
        "fastapi",
        "sqlalchemy",
        "session",
        "create_engine",
        "sessionmaker",
        "app.models.user",
        "app.models.company",
        "database_url",
        ".delete(",
        "drop table",
    ):
        assert forbidden not in source


def main() -> None:
    validate_snapshot_contract()
    validate_organization_control()
    validate_principal_registration()
    validate_membership_create_and_change()
    validate_self_change_rules()
    validate_last_admin_protection()
    validate_static_boundaries()
    print("Política administrativa DBI aprobada offline.")


if __name__ == "__main__":
    main()
