"""Valida persistencia administrativa DBI sin conexión ni transacción propia."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_mutation_plan import plan_membership_mutation  # noqa: E402
from app.dbi.admin_persistence import (  # noqa: E402
    DBIAdminPersistenceRepository,
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
    DBIPlotScope,
)
from app.dbi.models.admin_audit import (  # noqa: E402
    DBIAdminAuditEvent,
    DBIAdminAuditOutcome,
)
from app.dbi.models.identity import (  # noqa: E402
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
)

TENANT = "tenant-a"
ORG_A = "organization-a"
ORG_B = "organization-b"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
NEXT = NOW + timedelta(microseconds=1)


class _Result:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _Session:
    def __init__(self, rowcounts: tuple[int, ...] = ()) -> None:
        self.statements: list[Any] = []
        self.added: list[object] = []
        self._rowcounts = list(rowcounts)

    def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        rowcount = self._rowcounts.pop(0) if self._rowcounts else 0
        return _Result(rowcount)

    def add(self, entity: object) -> None:
        self.added.append(entity)


def _authority(
    *,
    membership_status: DBIAdminMembershipStatus = DBIAdminMembershipStatus.ACTIVE,
    permissions: frozenset[DBIPermission],
    organization_scopes: frozenset[str],
    farm_scopes: frozenset[DBIFarmScope] = frozenset(),
    plot_scopes: frozenset[DBIPlotScope] = frozenset(),
) -> DBIAdminAuthoritySnapshot:
    return DBIAdminAuthoritySnapshot(
        principal_ref="principal-target",
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=membership_status,
        permissions=permissions,
        organization_scopes=organization_scopes,
        farm_scopes=farm_scopes,
        plot_scopes=plot_scopes,
    )


def _plan():
    target_membership_id = uuid4()
    farm_a = uuid4()
    farm_b = uuid4()
    plot_b = uuid4()
    before = _authority(
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE}),
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    after = _authority(
        membership_status=DBIAdminMembershipStatus.INACTIVE,
        permissions=frozenset({DBIPermission.READ}),
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
    persisted = DBIAdminPersistedMembershipState(
        principal_id=uuid4(),
        membership_id=target_membership_id,
        principal_updated_at=NOW,
        membership_updated_at=NOW,
        authority=before,
    )
    plan = plan_membership_mutation(
        persisted,
        after,
        next_updated_at=NEXT,
        correlation_ref="request-001",
    )
    return plan, persisted, farm_a, farm_b, plot_b


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
    raise AssertionError("La persistencia administrativa debía producir conflicto.")


def validate_exact_persistence_order() -> None:
    plan, persisted, farm_a, farm_b, plot_b = _plan()
    actor_principal_id = uuid4()
    actor_membership_id = uuid4()
    session = _Session((1, 0, 0))
    repository = DBIAdminPersistenceRepository(session)  # type: ignore[arg-type]

    repository.apply_membership_mutation(
        actor_principal_id=actor_principal_id,
        actor_membership_id=actor_membership_id,
        target_membership_id=persisted.membership_id,
        plan=plan,
    )

    assert len(session.statements) == 3
    update_sql, update_values = _compiled(session.statements[0])
    permission_delete_sql, permission_delete_values = _compiled(
        session.statements[1]
    )
    scope_delete_sql, scope_delete_values = _compiled(session.statements[2])

    assert update_sql.startswith("update dbi_memberships set")
    assert "dbi_memberships.id =" in update_sql
    assert "dbi_memberships.tenant_ref =" in update_sql
    assert "dbi_memberships.updated_at =" in update_sql
    assert {
        persisted.membership_id,
        TENANT,
        NOW,
        NEXT,
        DBIAdminMembershipStatus.INACTIVE.value,
    }.issubset(update_values)

    assert permission_delete_sql.startswith(
        "delete from dbi_membership_permissions"
    )
    assert scope_delete_sql.startswith("delete from dbi_membership_scopes")
    assert permission_delete_values == {persisted.membership_id}
    assert scope_delete_values == {persisted.membership_id}

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

    assert len(permissions) == 1
    assert permissions[0].membership_id == persisted.membership_id
    assert permissions[0].permission == DBIPermission.READ.value

    assert len(scopes) == 3
    organization_rows = [
        row
        for row in scopes
        if row.scope_type == DBIMembershipScopeType.ORGANIZATION.value
    ]
    farm_rows = [
        row
        for row in scopes
        if row.scope_type == DBIMembershipScopeType.FARM.value
    ]
    plot_rows = [
        row
        for row in scopes
        if row.scope_type == DBIMembershipScopeType.PLOT.value
    ]
    assert len(organization_rows) == len(farm_rows) == len(plot_rows) == 1
    assert organization_rows[0].organization_ref == ORG_A
    assert organization_rows[0].farm_id is None
    assert organization_rows[0].plot_id is None
    assert farm_rows[0].organization_ref == ORG_A
    assert farm_rows[0].farm_id == farm_a
    assert farm_rows[0].plot_id is None
    assert plot_rows[0].organization_ref == ORG_B
    assert plot_rows[0].farm_id == farm_b
    assert plot_rows[0].plot_id == plot_b
    assert not any(
        row.scope_type == DBIMembershipScopeType.FARM.value
        and row.organization_ref == ORG_B
        and row.farm_id == farm_b
        for row in scopes
    )

    assert len(events) == len(plan.audit_events) == 6
    assert tuple(event.organization_ref for event in events) == tuple(
        event.organization_ref for event in plan.audit_events
    )
    assert tuple(event.action for event in events) == tuple(
        event.action.value for event in plan.audit_events
    )
    assert all(
        event.actor_principal_id == actor_principal_id
        and event.actor_membership_id == actor_membership_id
        and event.tenant_ref == TENANT
        and event.resource_type == "membership"
        and event.resource_ref == str(persisted.membership_id)
        and event.outcome == DBIAdminAuditOutcome.SUCCEEDED.value
        and event.correlation_ref == "request-001"
        and event.occurred_at == NEXT
        for event in events
    )


def validate_no_op_has_no_side_effects() -> None:
    authority = _authority(
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A}),
    )
    persisted = DBIAdminPersistedMembershipState(
        principal_id=uuid4(),
        membership_id=uuid4(),
        principal_updated_at=NOW,
        membership_updated_at=NOW,
        authority=authority,
    )
    plan = plan_membership_mutation(
        persisted,
        authority,
        next_updated_at=NEXT,
        correlation_ref="request-noop",
    )
    session = _Session()
    DBIAdminPersistenceRepository(session).apply_membership_mutation(  # type: ignore[arg-type]
        actor_principal_id=uuid4(),
        actor_membership_id=uuid4(),
        target_membership_id=persisted.membership_id,
        plan=plan,
    )
    assert session.statements == []
    assert session.added == []


def validate_conflicts_prevent_pending_entities() -> None:
    plan, persisted, _, _, _ = _plan()

    stale_session = _Session((0,))
    _assert_conflict(
        lambda: DBIAdminPersistenceRepository(  # type: ignore[arg-type]
            stale_session
        ).apply_membership_mutation(
            actor_principal_id=uuid4(),
            actor_membership_id=uuid4(),
            target_membership_id=persisted.membership_id,
            plan=plan,
        )
    )
    assert len(stale_session.statements) == 1
    assert stale_session.added == []

    wrong_target_session = _Session()
    _assert_conflict(
        lambda: DBIAdminPersistenceRepository(  # type: ignore[arg-type]
            wrong_target_session
        ).apply_membership_mutation(
            actor_principal_id=uuid4(),
            actor_membership_id=uuid4(),
            target_membership_id=uuid4(),
            plan=plan,
        )
    )
    assert wrong_target_session.statements == []
    assert wrong_target_session.added == []

    duplicate_event_plan = replace(
        plan,
        audit_events=(plan.audit_events[0], plan.audit_events[0]),
    )
    duplicate_session = _Session()
    _assert_conflict(
        lambda: DBIAdminPersistenceRepository(  # type: ignore[arg-type]
            duplicate_session
        ).apply_membership_mutation(
            actor_principal_id=uuid4(),
            actor_membership_id=uuid4(),
            target_membership_id=persisted.membership_id,
            plan=duplicate_event_plan,
        )
    )
    assert duplicate_session.statements == []
    assert duplicate_session.added == []


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "admin_persistence.py"
    ).read_text(encoding="utf-8").lower()

    for required in (
        "class dbiadminpersistencerepository",
        "update(dbimembership)",
        "delete(dbimembershippermission)",
        "delete(dbimembershipscope)",
        "dbiadminauditevent(",
        "getattr(result, \"rowcount\", none) != 1",
        "events = _validated_events",
    ):
        assert required in source

    for forbidden in (
        "delete(dbimembership)",
        "delete(dbiprincipal)",
        "delete(dbiadminauditevent)",
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
    validate_exact_persistence_order()
    validate_no_op_has_no_side_effects()
    validate_conflicts_prevent_pending_entities()
    validate_static_boundaries()
    print("Persistencia administrativa DBI aprobada offline.")


if __name__ == "__main__":
    main()
