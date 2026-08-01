"""Valida el estado administrativo DBI versionado sin conexiones."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_policy import (  # noqa: E402
    DBIAdminConflict,
    DBIAdminMembershipStatus,
)
from app.dbi.admin_state import build_admin_membership_state  # noqa: E402
from app.dbi.authorization import DBIFarmScope, DBIPermission, DBIPlotScope  # noqa: E402
from app.dbi.models.identity import (  # noqa: E402
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
    DBIMembershipStatus,
    DBIPrincipal,
    DBIPrincipalStatus,
)

ORG_A = "organization-a"
ORG_B = "organization-b"
TENANT = "tenant-a"
UTC_TIME = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _principal(*, status: str = DBIPrincipalStatus.ACTIVE.value) -> DBIPrincipal:
    return DBIPrincipal(
        id=uuid4(),
        legacy_identity_ref="legacy-identity-a",
        status=status,
        created_at=UTC_TIME,
        updated_at=UTC_TIME,
    )


def _membership(
    principal: DBIPrincipal,
    *,
    status: str = DBIMembershipStatus.ACTIVE.value,
) -> DBIMembership:
    return DBIMembership(
        id=uuid4(),
        principal_id=principal.id,
        tenant_ref=TENANT,
        status=status,
        created_at=UTC_TIME,
        updated_at=UTC_TIME,
    )


def _permission(
    membership: DBIMembership,
    permission: DBIPermission,
) -> DBIMembershipPermission:
    return DBIMembershipPermission(
        membership_id=membership.id,
        permission=permission.value,
    )


def _organization_scope(
    membership: DBIMembership,
    organization_ref: str = ORG_A,
) -> DBIMembershipScope:
    return DBIMembershipScope(
        id=uuid4(),
        membership_id=membership.id,
        scope_type=DBIMembershipScopeType.ORGANIZATION.value,
        organization_ref=organization_ref,
        farm_id=None,
        plot_id=None,
    )


def _farm_scope(
    membership: DBIMembership,
    *,
    organization_ref: str,
    farm_id,
) -> DBIMembershipScope:
    return DBIMembershipScope(
        id=uuid4(),
        membership_id=membership.id,
        scope_type=DBIMembershipScopeType.FARM.value,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=None,
    )


def _plot_scope(
    membership: DBIMembership,
    *,
    organization_ref: str,
    farm_id,
    plot_id,
) -> DBIMembershipScope:
    return DBIMembershipScope(
        id=uuid4(),
        membership_id=membership.id,
        scope_type=DBIMembershipScopeType.PLOT.value,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAdminConflict:
        return
    raise AssertionError("El estado administrativo divergente debía rechazarse.")


def validate_complete_state_and_hierarchy() -> None:
    principal = _principal()
    membership = _membership(principal)
    farm_a = uuid4()
    farm_b = uuid4()
    plot_b = uuid4()

    state = build_admin_membership_state(
        principal=principal,
        membership=membership,
        permissions=(
            _permission(membership, DBIPermission.READ),
            _permission(membership, DBIPermission.MANAGE),
        ),
        scopes=(
            _organization_scope(membership, ORG_A),
            _farm_scope(
                membership,
                organization_ref=ORG_A,
                farm_id=farm_a,
            ),
            _plot_scope(
                membership,
                organization_ref=ORG_B,
                farm_id=farm_b,
                plot_id=plot_b,
            ),
        ),
    )

    authority = state.authority
    assert state.principal_id == principal.id
    assert state.membership_id == membership.id
    assert authority.membership_status is DBIAdminMembershipStatus.ACTIVE
    assert authority.permissions == frozenset(
        {DBIPermission.READ, DBIPermission.MANAGE}
    )
    assert authority.organization_scopes == frozenset({ORG_A})
    assert authority.effective_admin_organizations == frozenset({ORG_A})
    assert authority.all_organization_refs == frozenset({ORG_A, ORG_B})
    assert DBIFarmScope(organization_ref=ORG_A, farm_id=farm_a) in authority.farm_scopes
    assert DBIFarmScope(organization_ref=ORG_B, farm_id=farm_b) in authority.farm_scopes
    assert DBIPlotScope(
        organization_ref=ORG_B,
        farm_id=farm_b,
        plot_id=plot_b,
    ) in authority.plot_scopes


def validate_statuses_and_versions() -> None:
    principal = _principal(status=DBIPrincipalStatus.INACTIVE.value)
    membership = _membership(
        principal,
        status=DBIMembershipStatus.REVOKED.value,
    )
    source_timezone = timezone(timedelta(hours=-5))
    principal.updated_at = datetime(2026, 8, 1, 7, 0, tzinfo=source_timezone)
    membership.updated_at = datetime(2026, 8, 1, 7, 30, tzinfo=source_timezone)

    state = build_admin_membership_state(
        principal=principal,
        membership=membership,
        permissions=(),
        scopes=(_organization_scope(membership),),
    )
    assert state.authority.principal_active is False
    assert state.authority.membership_status is DBIAdminMembershipStatus.REVOKED
    assert state.authority.effective_admin_organizations == frozenset()
    assert state.principal_updated_at == datetime(
        2026, 8, 1, 12, 0, tzinfo=timezone.utc
    )
    assert state.membership_updated_at == datetime(
        2026, 8, 1, 12, 30, tzinfo=timezone.utc
    )

    state.require_principal_version(
        datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    )
    state.require_membership_version(
        datetime(2026, 8, 1, 12, 30, tzinfo=timezone.utc)
    )
    _assert_conflict(
        lambda: state.require_membership_version(
            datetime(2026, 8, 1, 12, 31, tzinfo=timezone.utc)
        )
    )
    _assert_conflict(
        lambda: state.require_principal_version(datetime(2026, 8, 1, 12, 0))
    )


def validate_corrupt_rows_are_rejected() -> None:
    principal = _principal()
    membership = _membership(principal)

    wrong_principal = _principal()
    mismatched_membership = _membership(wrong_principal)
    _assert_conflict(
        lambda: build_admin_membership_state(
            principal=principal,
            membership=mismatched_membership,
            permissions=(),
            scopes=(),
        )
    )

    wrong_permission = DBIMembershipPermission(
        membership_id=uuid4(),
        permission=DBIPermission.READ.value,
    )
    _assert_conflict(
        lambda: build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=(wrong_permission,),
            scopes=(),
        )
    )

    unknown_permission = DBIMembershipPermission(
        membership_id=membership.id,
        permission="admin-all",
    )
    _assert_conflict(
        lambda: build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=(unknown_permission,),
            scopes=(),
        )
    )

    permission = _permission(membership, DBIPermission.READ)
    _assert_conflict(
        lambda: build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=(permission, permission),
            scopes=(),
        )
    )

    malformed_organization = _organization_scope(membership)
    malformed_organization.farm_id = uuid4()
    _assert_conflict(
        lambda: build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=(),
            scopes=(malformed_organization,),
        )
    )

    malformed_plot = DBIMembershipScope(
        id=uuid4(),
        membership_id=membership.id,
        scope_type=DBIMembershipScopeType.PLOT.value,
        organization_ref=ORG_A,
        farm_id=None,
        plot_id=uuid4(),
    )
    _assert_conflict(
        lambda: build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=(),
            scopes=(malformed_plot,),
        )
    )

    unknown_scope = _organization_scope(membership)
    unknown_scope.scope_type = "global"
    _assert_conflict(
        lambda: build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=(),
            scopes=(unknown_scope,),
        )
    )

    duplicate_scope = _organization_scope(membership)
    _assert_conflict(
        lambda: build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=(),
            scopes=(duplicate_scope, duplicate_scope),
        )
    )

    bad_principal = _principal(status="blocked")
    bad_membership = _membership(bad_principal)
    _assert_conflict(
        lambda: build_admin_membership_state(
            principal=bad_principal,
            membership=bad_membership,
            permissions=(),
            scopes=(),
        )
    )

    principal.updated_at = datetime(2026, 8, 1, 12, 0)
    _assert_conflict(
        lambda: build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=(),
            scopes=(),
        )
    )


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "admin_state.py"
    ).read_text(encoding="utf-8").lower()

    for required in (
        "dbiadminpersistedmembershipstate",
        "require_principal_version",
        "require_membership_version",
        "dbiadminmembershipstatus",
        "farm_scopes.add(farm_scope)",
    ):
        assert required in source

    for forbidden in (
        "session",
        "create_engine",
        "sessionmaker",
        "fastapi",
        "database_url",
        "app.models.user",
        "app.models.company",
        ".commit(",
        ".rollback(",
        ".delete(",
    ):
        assert forbidden not in source


def main() -> None:
    validate_complete_state_and_hierarchy()
    validate_statuses_and_versions()
    validate_corrupt_rows_are_rejected()
    validate_static_boundaries()
    print("Estado administrativo DBI versionado aprobado offline.")


if __name__ == "__main__":
    main()
