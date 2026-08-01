"""Valida la resolución cerrada del actor administrativo DBI sin conexiones."""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_actor import DBIAdminActorResolver  # noqa: E402
from app.dbi.admin_dependencies import (  # noqa: E402
    DBI_ADMIN_ACCESS_DENIED_DETAIL,
)
from app.dbi.admin_policy import DBIAdminConflict  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.models.identity import (  # noqa: E402
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
    DBIMembershipStatus,
    DBIPrincipal,
    DBIPrincipalStatus,
)

TENANT = "tenant-a"
ORG_A = "organization-a"
ORG_B = "organization-b"
NOW = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)


@dataclass
class FakeActorRepository:
    principal: DBIPrincipal | None
    memberships: tuple[DBIMembership, ...]
    permissions: tuple[DBIMembershipPermission, ...]
    scopes: tuple[DBIMembershipScope, ...]

    def get_principal(self, *, principal_id: UUID) -> DBIPrincipal | None:
        if self.principal is None or self.principal.id != principal_id:
            return None
        return self.principal

    def list_memberships(
        self,
        *,
        principal_id: UUID,
        tenant_ref: str,
    ) -> tuple[DBIMembership, ...]:
        return tuple(
            membership
            for membership in self.memberships
            if membership.principal_id == principal_id
            and membership.tenant_ref == tenant_ref
        )

    def list_permissions(
        self,
        *,
        membership_id: UUID,
    ) -> tuple[DBIMembershipPermission, ...]:
        return tuple(
            permission
            for permission in self.permissions
            if permission.membership_id == membership_id
        )

    def list_scopes(
        self,
        *,
        membership_id: UUID,
    ) -> tuple[DBIMembershipScope, ...]:
        return tuple(
            scope
            for scope in self.scopes
            if scope.membership_id == membership_id
        )


def _fixture():
    principal = DBIPrincipal(
        id=uuid4(),
        legacy_identity_ref="legacy-user-a",
        status=DBIPrincipalStatus.ACTIVE.value,
        created_at=NOW,
        updated_at=NOW,
    )
    membership = DBIMembership(
        id=uuid4(),
        principal_id=principal.id,
        tenant_ref=TENANT,
        status=DBIMembershipStatus.ACTIVE.value,
        created_at=NOW,
        updated_at=NOW,
    )
    farm_a = uuid4()
    farm_b = uuid4()
    plot_b = uuid4()
    permissions = (
        DBIMembershipPermission(
            membership_id=membership.id,
            permission=DBIPermission.READ.value,
        ),
        DBIMembershipPermission(
            membership_id=membership.id,
            permission=DBIPermission.MANAGE.value,
        ),
    )
    scopes = (
        DBIMembershipScope(
            id=uuid4(),
            membership_id=membership.id,
            scope_type=DBIMembershipScopeType.ORGANIZATION.value,
            organization_ref=ORG_A,
            farm_id=None,
            plot_id=None,
        ),
        DBIMembershipScope(
            id=uuid4(),
            membership_id=membership.id,
            scope_type=DBIMembershipScopeType.FARM.value,
            organization_ref=ORG_A,
            farm_id=farm_a,
            plot_id=None,
        ),
        DBIMembershipScope(
            id=uuid4(),
            membership_id=membership.id,
            scope_type=DBIMembershipScopeType.PLOT.value,
            organization_ref=ORG_B,
            farm_id=farm_b,
            plot_id=plot_b,
        ),
    )
    context = DBIAccessContext(
        principal_ref=str(principal.id),
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_A, ORG_B}),
        farm_scopes=frozenset(
            {
                DBIFarmScope(organization_ref=ORG_A, farm_id=farm_a),
                DBIFarmScope(organization_ref=ORG_B, farm_id=farm_b),
            }
        ),
        plot_scopes=frozenset(
            {
                DBIPlotScope(
                    organization_ref=ORG_B,
                    farm_id=farm_b,
                    plot_id=plot_b,
                )
            }
        ),
        permissions=frozenset(
            {DBIPermission.READ, DBIPermission.MANAGE}
        ),
    )
    repository = FakeActorRepository(
        principal=principal,
        memberships=(membership,),
        permissions=permissions,
        scopes=scopes,
    )
    return principal, membership, context, repository


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAdminConflict:
        return
    raise AssertionError("La resolución administrativa divergente debía fallar.")


def validate_exact_actor_resolution() -> None:
    principal, membership, context, repository = _fixture()
    state = DBIAdminActorResolver(repository).resolve(context=context)

    assert state.principal_id == principal.id
    assert state.membership_id == membership.id
    assert state.authority.principal_ref == principal.legacy_identity_ref
    assert state.authority.tenant_ref == TENANT
    assert state.authority.permissions == context.permissions
    assert state.authority.all_organization_refs == context.organization_refs
    assert state.membership_updated_at == NOW


def validate_closed_failures() -> None:
    principal, membership, context, repository = _fixture()

    _assert_conflict(
        lambda: DBIAdminActorResolver(repository).resolve(
            context=replace(context, principal_ref=principal.legacy_identity_ref)
        )
    )
    _assert_conflict(
        lambda: DBIAdminActorResolver(
            replace(repository, memberships=(membership, membership))
        ).resolve(context=context)
    )
    _assert_conflict(
        lambda: DBIAdminActorResolver(repository).resolve(
            context=replace(
                context,
                permissions=frozenset({DBIPermission.READ}),
            )
        )
    )

    inactive_membership = DBIMembership(
        id=membership.id,
        principal_id=membership.principal_id,
        tenant_ref=membership.tenant_ref,
        status=DBIMembershipStatus.INACTIVE.value,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )
    _assert_conflict(
        lambda: DBIAdminActorResolver(
            replace(repository, memberships=(inactive_membership,))
        ).resolve(context=context)
    )

    inactive_principal = DBIPrincipal(
        id=principal.id,
        legacy_identity_ref=principal.legacy_identity_ref,
        status=DBIPrincipalStatus.INACTIVE.value,
        created_at=principal.created_at,
        updated_at=principal.updated_at,
    )
    _assert_conflict(
        lambda: DBIAdminActorResolver(
            replace(repository, principal=inactive_principal)
        ).resolve(context=context)
    )


def main() -> None:
    assert DBI_ADMIN_ACCESS_DENIED_DETAIL == "Acceso administrativo DBI denegado."
    validate_exact_actor_resolution()
    validate_closed_failures()
    print("Actor administrativo DBI: resolución cerrada aprobada.")


if __name__ == "__main__":
    main()
