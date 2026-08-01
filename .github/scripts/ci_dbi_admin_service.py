"""Valida guardas y mutaciones administrativas DBI sin API ni commit."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_mutation_plan import DBIAdminMembershipMutationPlan  # noqa: E402
from app.dbi.admin_policy import (  # noqa: E402
    ADMIN_CONFLICT_MESSAGE,
    ADMIN_DENIED_MESSAGE,
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminDenied,
    DBIAdminMembershipStatus,
)
from app.dbi.admin_service import DBIAdminService  # noqa: E402
from app.dbi.admin_state import (  # noqa: E402
    DBIAdminLockedMembershipStates,
    DBIAdminPersistedMembershipState,
)
from app.dbi.authorization import DBIPermission  # noqa: E402

TENANT = "tenant-a"
ORG_A = "organization-a"
ORG_B = "organization-b"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
NEXT = NOW + timedelta(microseconds=1)


def _snapshot(
    *,
    principal_ref: str = "principal-target",
    tenant_ref: str = TENANT,
    membership_status: DBIAdminMembershipStatus = DBIAdminMembershipStatus.ACTIVE,
    permissions: frozenset[DBIPermission] | None = None,
    organization_scopes: frozenset[str] | None = None,
) -> DBIAdminAuthoritySnapshot:
    return DBIAdminAuthoritySnapshot(
        principal_ref=principal_ref,
        tenant_ref=tenant_ref,
        principal_active=True,
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
    )


def _actor(**overrides) -> DBIAdminAuthoritySnapshot:
    return _snapshot(principal_ref="principal-actor", **overrides)


def _state(
    membership_id: UUID,
    authority: DBIAdminAuthoritySnapshot,
    *,
    principal_id: UUID | None = None,
    membership_updated_at: datetime = NOW,
) -> DBIAdminPersistedMembershipState:
    return DBIAdminPersistedMembershipState(
        principal_id=principal_id or uuid4(),
        membership_id=membership_id,
        principal_updated_at=NOW,
        membership_updated_at=membership_updated_at,
        authority=authority,
    )


class _FakeRepository:
    def __init__(
        self,
        states: dict[UUID, DBIAdminPersistedMembershipState],
        *,
        remaining_counts: dict[str, int] | None = None,
        invalid_bundle: bool = False,
        include_extra_states: bool = False,
        fail_apply: bool = False,
    ) -> None:
        self.states = states
        self.remaining_counts = remaining_counts or {}
        self.invalid_bundle = invalid_bundle
        self.include_extra_states = include_extra_states
        self.fail_apply = fail_apply
        self.events: list[tuple[object, ...]] = []

    def lock_and_load_membership_states(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        membership_ids: frozenset[UUID],
    ) -> DBIAdminLockedMembershipStates:
        organizations = tuple(sorted(organization_refs))
        ids = tuple(sorted(membership_ids, key=str))
        self.events.append(("lock_and_load", tenant_ref, organizations, ids))
        if self.invalid_bundle:
            return object()  # type: ignore[return-value]
        selected = (
            dict(self.states)
            if self.include_extra_states
            else {
                membership_id: self.states[membership_id]
                for membership_id in membership_ids
                if membership_id in self.states
            }
        )
        return DBIAdminLockedMembershipStates(
            lock_keys=tuple(range(101, 101 + len(organizations))),
            states=selected,
        )

    def count_remaining_administrators(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        excluded_membership_id: UUID,
    ) -> dict[str, int]:
        organizations = tuple(sorted(organization_refs))
        self.events.append(
            ("count", tenant_ref, organizations, excluded_membership_id)
        )
        return {
            organization_ref: self.remaining_counts.get(organization_ref, 0)
            for organization_ref in organizations
        }

    def apply_membership_mutation(
        self,
        *,
        actor_principal_id: UUID,
        actor_membership_id: UUID,
        target_membership_id: UUID,
        plan: DBIAdminMembershipMutationPlan,
    ) -> None:
        self.events.append(
            (
                "apply",
                actor_principal_id,
                actor_membership_id,
                target_membership_id,
                plan,
            )
        )
        if self.fail_apply:
            raise DBIAdminConflict()


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


def validate_principal_and_membership_guards() -> None:
    actor_id = uuid4()
    actor = _actor(organization_scopes=frozenset({ORG_A, ORG_B}))
    repository = _FakeRepository({actor_id: _state(actor_id, actor)})
    service = DBIAdminService(repository)

    principal_evidence = service.guard_principal_registration(
        actor,
        actor_membership_id=actor_id,
        target_principal_ref="principal-new",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_A}),
    )
    assert principal_evidence.tenant_ref == TENANT
    assert principal_evidence.organization_refs == frozenset({ORG_A})
    assert principal_evidence.lock_keys == (101,)

    requested = _snapshot(
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    membership_evidence = service.guard_membership_create(
        actor,
        requested,
        actor_membership_id=actor_id,
    )
    assert membership_evidence.organization_refs == frozenset({ORG_A, ORG_B})
    assert membership_evidence.lock_keys == (101, 102)
    assert [event[0] for event in repository.events] == [
        "lock_and_load",
        "lock_and_load",
    ]

    no_manage = _actor(permissions=frozenset({DBIPermission.READ}))
    denied_repository = _FakeRepository(
        {actor_id: _state(actor_id, no_manage)}
    )
    _assert_denied(
        lambda: DBIAdminService(
            denied_repository
        ).guard_principal_registration(
            no_manage,
            actor_membership_id=actor_id,
            target_principal_ref="principal-new",
            tenant_ref=TENANT,
            organization_refs=frozenset({ORG_A}),
        )
    )
    assert [event[0] for event in denied_repository.events] == [
        "lock_and_load"
    ]


def validate_membership_change_and_last_admin() -> None:
    actor_id = uuid4()
    target_id = uuid4()
    actor = _actor()
    before = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE})
    )
    after = _snapshot(permissions=frozenset({DBIPermission.READ}))
    states = {
        actor_id: _state(actor_id, actor),
        target_id: _state(target_id, before),
    }

    repository = _FakeRepository(states, remaining_counts={ORG_A: 1})
    evidence = DBIAdminService(repository).guard_membership_change(
        actor,
        before,
        after,
        actor_membership_id=actor_id,
        target_membership_id=target_id,
        expected_updated_at=NOW,
    )
    assert evidence.protected_organization_refs == frozenset({ORG_A})
    assert [event[0] for event in repository.events] == [
        "lock_and_load",
        "count",
    ]

    conflict_repository = _FakeRepository(
        states,
        remaining_counts={ORG_A: 0},
    )
    _assert_conflict(
        lambda: DBIAdminService(
            conflict_repository
        ).guard_membership_change(
            actor,
            before,
            after,
            actor_membership_id=actor_id,
            target_membership_id=target_id,
            expected_updated_at=NOW,
        )
    )
    assert [event[0] for event in conflict_repository.events] == [
        "lock_and_load",
        "count",
    ]

    no_protection_before = _snapshot(
        permissions=frozenset({DBIPermission.READ})
    )
    no_protection_after = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.WRITE})
    )
    no_protection_repository = _FakeRepository(
        {
            actor_id: _state(actor_id, actor),
            target_id: _state(target_id, no_protection_before),
        }
    )
    evidence = DBIAdminService(
        no_protection_repository
    ).guard_membership_change(
        actor,
        no_protection_before,
        no_protection_after,
        actor_membership_id=actor_id,
        target_membership_id=target_id,
        expected_updated_at=NOW,
    )
    assert evidence.protected_organization_refs == frozenset()
    assert [event[0] for event in no_protection_repository.events] == [
        "lock_and_load"
    ]


def validate_invalid_state_bundles_and_versions() -> None:
    actor_id = uuid4()
    target_id = uuid4()
    actor = _actor()
    before = _snapshot(permissions=frozenset({DBIPermission.READ}))
    after = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.WRITE})
    )

    stale_authority = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE})
    )
    stale_repository = _FakeRepository(
        {
            actor_id: _state(actor_id, actor),
            target_id: _state(target_id, stale_authority),
        }
    )
    _assert_conflict(
        lambda: DBIAdminService(stale_repository).guard_membership_change(
            actor,
            before,
            after,
            actor_membership_id=actor_id,
            target_membership_id=target_id,
            expected_updated_at=NOW,
        )
    )

    missing_repository = _FakeRepository(
        {actor_id: _state(actor_id, actor)}
    )
    _assert_conflict(
        lambda: DBIAdminService(missing_repository).guard_membership_change(
            actor,
            before,
            after,
            actor_membership_id=actor_id,
            target_membership_id=target_id,
            expected_updated_at=NOW,
        )
    )

    extra_id = uuid4()
    extra_repository = _FakeRepository(
        {
            actor_id: _state(actor_id, actor),
            target_id: _state(target_id, before),
            extra_id: _state(extra_id, _snapshot(principal_ref="extra")),
        },
        include_extra_states=True,
    )
    _assert_conflict(
        lambda: DBIAdminService(extra_repository).guard_membership_change(
            actor,
            before,
            after,
            actor_membership_id=actor_id,
            target_membership_id=target_id,
            expected_updated_at=NOW,
        )
    )

    invalid_repository = _FakeRepository(
        {
            actor_id: _state(actor_id, actor),
            target_id: _state(target_id, before),
        },
        invalid_bundle=True,
    )
    _assert_conflict(
        lambda: DBIAdminService(invalid_repository).guard_membership_change(
            actor,
            before,
            after,
            actor_membership_id=actor_id,
            target_membership_id=target_id,
            expected_updated_at=NOW,
        )
    )

    version_repository = _FakeRepository(
        {
            actor_id: _state(actor_id, actor),
            target_id: _state(
                target_id,
                before,
                membership_updated_at=NOW + timedelta(microseconds=1),
            ),
        }
    )
    _assert_conflict(
        lambda: DBIAdminService(version_repository).guard_membership_change(
            actor,
            before,
            after,
            actor_membership_id=actor_id,
            target_membership_id=target_id,
            expected_updated_at=NOW,
        )
    )
    assert [event[0] for event in version_repository.events] == [
        "lock_and_load"
    ]


def validate_self_change() -> None:
    actor_id = uuid4()
    actor = _actor()
    reduced = _actor(
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE})
    )
    repository = _FakeRepository({actor_id: _state(actor_id, actor)})
    evidence = DBIAdminService(repository).guard_membership_change(
        actor,
        actor,
        reduced,
        actor_membership_id=actor_id,
        target_membership_id=actor_id,
        expected_updated_at=NOW,
    )
    assert evidence.organization_refs == frozenset({ORG_A})
    assert repository.events[0][3] == (actor_id,)

    naive_repository = _FakeRepository({actor_id: _state(actor_id, actor)})
    _assert_conflict(
        lambda: DBIAdminService(naive_repository).guard_membership_change(
            actor,
            actor,
            reduced,
            actor_membership_id=actor_id,
            target_membership_id=actor_id,
            expected_updated_at=NOW.replace(tzinfo=None),
        )
    )


def validate_mutation_order_and_evidence() -> None:
    actor_id = uuid4()
    actor_principal_id = uuid4()
    target_id = uuid4()
    actor = _actor()
    before = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE})
    )
    after = _snapshot(permissions=frozenset({DBIPermission.READ}))
    repository = _FakeRepository(
        {
            actor_id: _state(
                actor_id,
                actor,
                principal_id=actor_principal_id,
            ),
            target_id: _state(target_id, before),
        },
        remaining_counts={ORG_A: 1},
    )

    evidence = DBIAdminService(repository).mutate_membership(
        actor,
        before,
        after,
        actor_membership_id=actor_id,
        target_membership_id=target_id,
        expected_updated_at=NOW,
        next_updated_at=NEXT,
        correlation_ref="request-001",
    )
    assert evidence.plan.applied is True
    assert evidence.plan.next_updated_at == NEXT
    assert evidence.guard.protected_organization_refs == frozenset({ORG_A})
    assert [event[0] for event in repository.events] == [
        "lock_and_load",
        "count",
        "apply",
    ]
    apply_event = repository.events[-1]
    assert apply_event[1] == actor_principal_id
    assert apply_event[2] == actor_id
    assert apply_event[3] == target_id
    assert apply_event[4] is evidence.plan

    no_op_repository = _FakeRepository(
        {
            actor_id: _state(
                actor_id,
                actor,
                principal_id=actor_principal_id,
            ),
            target_id: _state(target_id, before),
        }
    )
    no_op = DBIAdminService(no_op_repository).mutate_membership(
        actor,
        before,
        before,
        actor_membership_id=actor_id,
        target_membership_id=target_id,
        expected_updated_at=NOW,
        next_updated_at=NEXT,
        correlation_ref="request-noop",
    )
    assert no_op.plan.applied is False
    assert [event[0] for event in no_op_repository.events] == [
        "lock_and_load",
        "apply",
    ]


def validate_mutation_stops_before_apply() -> None:
    actor_id = uuid4()
    target_id = uuid4()
    actor = _actor()
    before = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE})
    )
    after = _snapshot(permissions=frozenset({DBIPermission.READ}))
    states = {
        actor_id: _state(actor_id, actor),
        target_id: _state(target_id, before),
    }

    last_admin_repository = _FakeRepository(
        states,
        remaining_counts={ORG_A: 0},
    )
    _assert_conflict(
        lambda: DBIAdminService(last_admin_repository).mutate_membership(
            actor,
            before,
            after,
            actor_membership_id=actor_id,
            target_membership_id=target_id,
            expected_updated_at=NOW,
            next_updated_at=NEXT,
            correlation_ref="request-last-admin",
        )
    )
    assert [event[0] for event in last_admin_repository.events] == [
        "lock_and_load",
        "count",
    ]

    invalid_time_repository = _FakeRepository(
        states,
        remaining_counts={ORG_A: 1},
    )
    _assert_conflict(
        lambda: DBIAdminService(invalid_time_repository).mutate_membership(
            actor,
            before,
            after,
            actor_membership_id=actor_id,
            target_membership_id=target_id,
            expected_updated_at=NOW,
            next_updated_at=NOW,
            correlation_ref="request-time",
        )
    )
    assert [event[0] for event in invalid_time_repository.events] == [
        "lock_and_load",
        "count",
    ]


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "admin_service.py"
    ).read_text(encoding="utf-8").lower()
    repository_source = (
        BACKEND / "app" / "dbi" / "admin_repository.py"
    ).read_text(encoding="utf-8").lower()

    for required in (
        "lock_and_load_membership_states",
        "frozenset(value.states.keys()) != membership_ids",
        "_require_authority_match",
        "require_membership_version",
        "dbiadminpolicy.require_membership_change",
        "count_remaining_administrators",
        "plan_membership_mutation",
        "apply_membership_mutation",
        "advisory locks",
    ):
        assert required in source

    authorization = source[
        source.index("def _authorize_membership_change") :
        source.index("def guard_membership_change")
    ]
    lock_position = authorization.index("locked = self._lock_and_load")
    match_position = authorization.index("_require_authority_match")
    version_position = authorization.index("require_membership_version")
    policy_position = authorization.index(
        "dbiadminpolicy.require_membership_change"
    )
    count_position = authorization.index("count_remaining_administrators")
    assert (
        lock_position
        < match_position
        < version_position
        < policy_position
        < count_position
    )

    mutation = source[source.index("def mutate_membership") :]
    authorize_position = mutation.index("self._authorize_membership_change")
    plan_position = mutation.index("plan = plan_membership_mutation")
    apply_position = mutation.index("self._repository.apply_membership_mutation")
    assert authorize_position < plan_position < apply_position

    assert "class dbiadminlockedmembershipstates" not in source
    assert "from app.dbi.admin_service" not in repository_source
    assert "from app.dbi.admin_state" in repository_source
    assert "lock_organization_authority" not in source
    assert "persisted_updated_at" not in source
    for forbidden in (
        "fastapi",
        "sqlalchemy",
        "sessionmaker",
        "create_engine",
        "sessionlocal",
        "app.models.user",
        "app.models.company",
        "database_url",
        ".commit(",
        ".rollback(",
        ".close(",
        "delete(",
        "drop table",
    ):
        assert forbidden not in source


def main() -> None:
    validate_principal_and_membership_guards()
    validate_membership_change_and_last_admin()
    validate_invalid_state_bundles_and_versions()
    validate_self_change()
    validate_mutation_order_and_evidence()
    validate_mutation_stops_before_apply()
    validate_static_boundaries()
    print("Guardas y mutaciones administrativas DBI aprobadas offline.")


if __name__ == "__main__":
    main()
