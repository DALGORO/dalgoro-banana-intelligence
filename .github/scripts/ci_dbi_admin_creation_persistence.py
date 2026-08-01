"""Valida persistencia idempotente de altas administrativas DBI offline."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_creation_persistence import (  # noqa: E402
    DBIAdminCreationPersistenceRepository,
)
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
from app.dbi.authorization import (  # noqa: E402
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.models.admin_audit import DBIAdminAuditEvent  # noqa: E402
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
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


class _Scalars:
    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _Result:
    def __init__(
        self,
        *,
        scalar: object | None = None,
        scalar_values: tuple[object, ...] = (),
    ) -> None:
        self._scalar = scalar
        self._scalar_values = scalar_values

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._scalar_values)


class _Session:
    def __init__(self, results: tuple[_Result, ...]) -> None:
        self.results = list(results)
        self.statements: list[Any] = []
        self.added: list[object] = []

    def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        if not self.results:
            raise AssertionError("No había resultado preparado para la sentencia.")
        return self.results.pop(0)

    def add(self, entity: object) -> None:
        self.added.append(entity)


def _compiled(statement: Any) -> tuple[str, set[object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    values: set[object] = set()
    for value in compiled.params.values():
        if isinstance(value, (tuple, list, set, frozenset)):
            values.update(value)
        else:
            values.add(value)
    return " ".join(str(compiled).lower().split()), values


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAdminConflict:
        return
    raise AssertionError("El alta administrativa debía producir conflicto.")


def _principal_plan(
    *,
    principal_id: UUID | None = None,
    legacy_identity_ref: str = "principal-target",
):
    return plan_principal_registration(
        principal_id=principal_id or uuid4(),
        legacy_identity_ref=legacy_identity_ref,
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_A, ORG_B}),
        occurred_at=NOW,
        correlation_ref="principal-request-001",
    )


def _requested_authority(
    *,
    permissions: frozenset[DBIPermission] | None = None,
) -> tuple[DBIAdminAuthoritySnapshot, UUID, UUID, UUID]:
    farm_a = uuid4()
    farm_b = uuid4()
    plot_b = uuid4()
    requested = DBIAdminAuthoritySnapshot(
        principal_ref="principal-target",
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        permissions=(
            permissions
            if permissions is not None
            else frozenset({DBIPermission.READ, DBIPermission.WRITE})
        ),
        organization_scopes=frozenset({ORG_A}),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref=ORG_A, farm_id=farm_a)}
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
    )
    return requested, farm_a, farm_b, plot_b


def _membership_plan(
    *,
    membership_id: UUID | None = None,
    principal_id: UUID | None = None,
    requested: DBIAdminAuthoritySnapshot | None = None,
):
    if requested is None:
        requested, _, _, _ = _requested_authority()
    return plan_membership_creation(
        membership_id=membership_id or uuid4(),
        principal_id=principal_id or uuid4(),
        requested=requested,
        occurred_at=NOW,
        correlation_ref="membership-request-001",
    )


def _principal(plan, *, status: str = DBIPrincipalStatus.ACTIVE.value):
    return DBIPrincipal(
        id=plan.principal_id,
        legacy_identity_ref=(
            plan.legacy_identity_ref
            if hasattr(plan, "legacy_identity_ref")
            else plan.requested.principal_ref
        ),
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def validate_new_and_idempotent_principal() -> None:
    plan = _principal_plan()
    actor_principal_id = uuid4()
    actor_membership_id = uuid4()
    created_session = _Session((_Result(scalar=plan.principal_id),))
    created = DBIAdminCreationPersistenceRepository(  # type: ignore[arg-type]
        created_session
    ).register_principal(
        actor_principal_id=actor_principal_id,
        actor_membership_id=actor_membership_id,
        plan=plan,
    )
    assert created is True
    assert len(created_session.statements) == 1
    sql, values = _compiled(created_session.statements[0])
    assert sql.startswith("insert into dbi_principals")
    assert "on conflict do nothing" in sql
    assert "returning dbi_principals.id" in sql
    assert {
        plan.principal_id,
        plan.legacy_identity_ref,
        DBIPrincipalStatus.ACTIVE.value,
        NOW,
    }.issubset(values)

    events = [
        entity
        for entity in created_session.added
        if isinstance(entity, DBIAdminAuditEvent)
    ]
    assert len(events) == 2
    assert {event.organization_ref for event in events} == {ORG_A, ORG_B}
    assert all(
        event.action == DBIAdminCreationAction.PRINCIPAL_REGISTERED.value
        and event.actor_principal_id == actor_principal_id
        and event.actor_membership_id == actor_membership_id
        and event.resource_ref == str(plan.principal_id)
        and event.occurred_at == NOW
        for event in events
    )

    existing = _principal(plan)
    repeated_session = _Session(
        (
            _Result(scalar=None),
            _Result(scalar_values=(existing,)),
        )
    )
    repeated = DBIAdminCreationPersistenceRepository(  # type: ignore[arg-type]
        repeated_session
    ).register_principal(
        actor_principal_id=actor_principal_id,
        actor_membership_id=actor_membership_id,
        plan=plan,
    )
    assert repeated is False
    assert len(repeated_session.statements) == 2
    assert repeated_session.added == []


def validate_principal_conflicts_and_event_barrier() -> None:
    plan = _principal_plan()
    inactive = _principal(plan, status=DBIPrincipalStatus.INACTIVE.value)
    inactive_session = _Session(
        (
            _Result(scalar=None),
            _Result(scalar_values=(inactive,)),
        )
    )
    _assert_conflict(
        lambda: DBIAdminCreationPersistenceRepository(  # type: ignore[arg-type]
            inactive_session
        ).register_principal(
            actor_principal_id=uuid4(),
            actor_membership_id=uuid4(),
            plan=plan,
        )
    )
    assert inactive_session.added == []

    conflicting = DBIPrincipal(
        id=uuid4(),
        legacy_identity_ref=plan.legacy_identity_ref,
        status=DBIPrincipalStatus.ACTIVE.value,
        created_at=NOW,
        updated_at=NOW,
    )
    conflict_session = _Session(
        (
            _Result(scalar=None),
            _Result(scalar_values=(conflicting,)),
        )
    )
    _assert_conflict(
        lambda: DBIAdminCreationPersistenceRepository(  # type: ignore[arg-type]
            conflict_session
        ).register_principal(
            actor_principal_id=uuid4(),
            actor_membership_id=uuid4(),
            plan=plan,
        )
    )

    forged_event = replace(
        plan.audit_events[0],
        action=DBIAdminCreationAction.MEMBERSHIP_CREATED,
    )
    forged_plan = replace(
        plan,
        audit_events=(forged_event, *plan.audit_events[1:]),
    )
    forged_session = _Session(())
    _assert_conflict(
        lambda: DBIAdminCreationPersistenceRepository(  # type: ignore[arg-type]
            forged_session
        ).register_principal(
            actor_principal_id=uuid4(),
            actor_membership_id=uuid4(),
            plan=forged_plan,
        )
    )
    assert forged_session.statements == []
    assert forged_session.added == []


def validate_new_membership_authority() -> None:
    requested, farm_a, farm_b, plot_b = _requested_authority()
    plan = _membership_plan(requested=requested)
    principal = _principal(plan)
    session = _Session(
        (
            _Result(scalar_values=(principal,)),
            _Result(scalar=plan.membership_id),
        )
    )
    repository = DBIAdminCreationPersistenceRepository(  # type: ignore[arg-type]
        session
    )
    assert repository.create_membership(
        actor_principal_id=uuid4(),
        actor_membership_id=uuid4(),
        plan=plan,
    ) is True
    assert len(session.statements) == 2
    sql, values = _compiled(session.statements[1])
    assert sql.startswith("insert into dbi_memberships")
    assert "on conflict do nothing" in sql
    assert "returning dbi_memberships.id" in sql
    assert {
        plan.membership_id,
        plan.principal_id,
        TENANT,
        DBIMembershipStatus.ACTIVE.value,
        NOW,
    }.issubset(values)

    permissions = [
        entity
        for entity in session.added
        if isinstance(entity, DBIMembershipPermission)
    ]
    scopes = [
        entity for entity in session.added if isinstance(entity, DBIMembershipScope)
    ]
    events = [
        entity for entity in session.added if isinstance(entity, DBIAdminAuditEvent)
    ]
    assert {row.permission for row in permissions} == {"read", "write"}
    assert {
        (row.scope_type, row.organization_ref, row.farm_id, row.plot_id)
        for row in scopes
    } == {
        (DBIMembershipScopeType.ORGANIZATION.value, ORG_A, None, None),
        (DBIMembershipScopeType.FARM.value, ORG_A, farm_a, None),
        (DBIMembershipScopeType.PLOT.value, ORG_B, farm_b, plot_b),
    }
    assert len(events) == 2
    assert all(
        event.action == DBIAdminCreationAction.MEMBERSHIP_CREATED.value
        and event.resource_ref == str(plan.membership_id)
        for event in events
    )


def validate_idempotent_and_divergent_membership() -> None:
    requested, farm_a, farm_b, plot_b = _requested_authority()
    plan = _membership_plan(requested=requested)
    principal = _principal(plan)
    membership = DBIMembership(
        id=plan.membership_id,
        principal_id=plan.principal_id,
        tenant_ref=TENANT,
        status=DBIMembershipStatus.ACTIVE.value,
        created_at=NOW,
        updated_at=NOW,
    )
    permissions = tuple(
        DBIMembershipPermission(
            membership_id=plan.membership_id,
            permission=permission.value,
        )
        for permission in sorted(requested.permissions, key=lambda value: value.value)
    )
    scopes = (
        DBIMembershipScope(
            id=uuid4(),
            membership_id=plan.membership_id,
            scope_type=DBIMembershipScopeType.ORGANIZATION.value,
            organization_ref=ORG_A,
            farm_id=None,
            plot_id=None,
        ),
        DBIMembershipScope(
            id=uuid4(),
            membership_id=plan.membership_id,
            scope_type=DBIMembershipScopeType.FARM.value,
            organization_ref=ORG_A,
            farm_id=farm_a,
            plot_id=None,
        ),
        DBIMembershipScope(
            id=uuid4(),
            membership_id=plan.membership_id,
            scope_type=DBIMembershipScopeType.PLOT.value,
            organization_ref=ORG_B,
            farm_id=farm_b,
            plot_id=plot_b,
        ),
    )

    exact_session = _Session(
        (
            _Result(scalar_values=(principal,)),
            _Result(scalar=None),
            _Result(scalar_values=(membership,)),
            _Result(scalar_values=permissions),
            _Result(scalar_values=scopes),
        )
    )
    exact = DBIAdminCreationPersistenceRepository(  # type: ignore[arg-type]
        exact_session
    ).create_membership(
        actor_principal_id=uuid4(),
        actor_membership_id=uuid4(),
        plan=plan,
    )
    assert exact is False
    assert len(exact_session.statements) == 5
    assert exact_session.added == []

    divergent_session = _Session(
        (
            _Result(scalar_values=(principal,)),
            _Result(scalar=None),
            _Result(scalar_values=(membership,)),
            _Result(scalar_values=(permissions[0],)),
            _Result(scalar_values=scopes),
        )
    )
    _assert_conflict(
        lambda: DBIAdminCreationPersistenceRepository(  # type: ignore[arg-type]
            divergent_session
        ).create_membership(
            actor_principal_id=uuid4(),
            actor_membership_id=uuid4(),
            plan=plan,
        )
    )
    assert divergent_session.added == []

    inactive_principal = _principal(
        plan,
        status=DBIPrincipalStatus.INACTIVE.value,
    )
    inactive_session = _Session(
        (_Result(scalar_values=(inactive_principal,)),)
    )
    _assert_conflict(
        lambda: DBIAdminCreationPersistenceRepository(  # type: ignore[arg-type]
            inactive_session
        ).create_membership(
            actor_principal_id=uuid4(),
            actor_membership_id=uuid4(),
            plan=plan,
        )
    )
    assert len(inactive_session.statements) == 1
    assert inactive_session.added == []


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "admin_creation_persistence.py"
    ).read_text(encoding="utf-8").lower()
    for required in (
        "postgresql_insert(dbiprincipal)",
        "postgresql_insert(dbimembership)",
        ".on_conflict_do_nothing()",
        ".returning(dbiprincipal.id)",
        ".returning(dbimembership.id)",
        "build_admin_membership_state",
        "expected_action=dbiadmincreationaction.principal_registered",
        "expected_action=dbiadmincreationaction.membership_created",
    ):
        assert required in source
    for forbidden in (
        "delete(dbiprincipal)",
        "delete(dbimembership)",
        "update(dbiprincipal)",
        "create_engine",
        "sessionmaker",
        "sessionlocal",
        ".commit(",
        ".rollback(",
        ".flush(",
        "database_url",
        "app.models.user",
        "app.models.company",
    ):
        assert forbidden not in source


def main() -> None:
    validate_new_and_idempotent_principal()
    validate_principal_conflicts_and_event_barrier()
    validate_new_membership_authority()
    validate_idempotent_and_divergent_membership()
    validate_static_boundaries()
    print("Persistencia idempotente de altas DBI aprobada offline.")


if __name__ == "__main__":
    main()
