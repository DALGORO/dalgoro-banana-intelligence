"""Valida coordinación de altas administrativas DBI sin SQL ni API."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_creation_plan import (  # noqa: E402
    DBIAdminMembershipCreationPlan,
    DBIAdminPrincipalRegistrationPlan,
)
from app.dbi.admin_policy import (  # noqa: E402
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


def _snapshot(
    *,
    principal_ref: str,
    permissions: frozenset[DBIPermission] | None = None,
    organization_scopes: frozenset[str] | None = None,
) -> DBIAdminAuthoritySnapshot:
    return DBIAdminAuthoritySnapshot(
        principal_ref=principal_ref,
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        permissions=(
            permissions
            if permissions is not None
            else frozenset(
                {DBIPermission.READ, DBIPermission.WRITE, DBIPermission.MANAGE}
            )
        ),
        organization_scopes=(
            organization_scopes
            if organization_scopes is not None
            else frozenset({ORG_A, ORG_B})
        ),
    )


def _state(
    membership_id: UUID,
    authority: DBIAdminAuthoritySnapshot,
    *,
    principal_id: UUID,
) -> DBIAdminPersistedMembershipState:
    return DBIAdminPersistedMembershipState(
        principal_id=principal_id,
        membership_id=membership_id,
        principal_updated_at=NOW,
        membership_updated_at=NOW,
        authority=authority,
    )


class _Repository:
    def __init__(
        self,
        *,
        actor_membership_id: UUID,
        actor_state: DBIAdminPersistedMembershipState,
        principal_created: bool = True,
        membership_created: bool = True,
        hierarchy_matches: bool = True,
    ) -> None:
        self.actor_membership_id = actor_membership_id
        self.actor_state = actor_state
        self.principal_created = principal_created
        self.membership_created = membership_created
        self.hierarchy_matches = hierarchy_matches
        self.events: list[tuple[object, ...]] = []

    def lock_and_load_membership_states(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        membership_ids: frozenset[UUID],
    ) -> DBIAdminLockedMembershipStates:
        self.events.append(
            (
                "lock",
                tenant_ref,
                tuple(sorted(organization_refs)),
                tuple(sorted(membership_ids, key=str)),
            )
        )
        states = (
            {self.actor_membership_id: self.actor_state}
            if membership_ids == frozenset({self.actor_membership_id})
            else {}
        )
        return DBIAdminLockedMembershipStates(
            lock_keys=tuple(range(101, 101 + len(organization_refs))),
            states=states,
        )

    def scope_hierarchy_matches(self, *, farm_scopes, plot_scopes) -> bool:
        self.events.append(("hierarchy", farm_scopes, plot_scopes))
        return self.hierarchy_matches

    def register_principal(
        self,
        *,
        actor_principal_id: UUID,
        actor_membership_id: UUID,
        plan: DBIAdminPrincipalRegistrationPlan,
    ) -> bool:
        self.events.append(
            (
                "register_principal",
                actor_principal_id,
                actor_membership_id,
                plan,
            )
        )
        return self.principal_created

    def create_membership(
        self,
        *,
        actor_principal_id: UUID,
        actor_membership_id: UUID,
        plan: DBIAdminMembershipCreationPlan,
    ) -> bool:
        self.events.append(
            (
                "create_membership",
                actor_principal_id,
                actor_membership_id,
                plan,
            )
        )
        return self.membership_created


def _assert_denied(factory) -> None:
    try:
        factory()
    except DBIAdminDenied:
        return
    raise AssertionError("La alta administrativa debía ser denegada.")


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAdminConflict:
        return
    raise AssertionError("La alta administrativa debía producir conflicto.")


def _fixture(**overrides):
    actor_membership_id = uuid4()
    actor_principal_id = uuid4()
    actor = _snapshot(principal_ref="principal-actor")
    repository = _Repository(
        actor_membership_id=actor_membership_id,
        actor_state=_state(
            actor_membership_id,
            actor,
            principal_id=actor_principal_id,
        ),
        **overrides,
    )
    return actor, actor_principal_id, actor_membership_id, repository


def validate_principal_registration_created_and_no_op() -> None:
    actor, actor_principal_id, actor_membership_id, repository = _fixture()
    target_id = uuid4()
    evidence = DBIAdminService(repository).register_principal(
        actor,
        actor_membership_id=actor_membership_id,
        principal_id=target_id,
        target_principal_ref="principal-target",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_A}),
        occurred_at=NOW,
        correlation_ref="principal-create-001",
    )
    assert evidence.created is True
    assert evidence.plan.principal_id == target_id
    assert evidence.plan.legacy_identity_ref == "principal-target"
    assert evidence.guard.lock_keys == (101,)
    assert [event[0] for event in repository.events] == [
        "lock",
        "register_principal",
    ]
    persisted = repository.events[-1]
    assert persisted[1] == actor_principal_id
    assert persisted[2] == actor_membership_id
    assert persisted[3] is evidence.plan

    actor, _, actor_membership_id, no_op_repository = _fixture(
        principal_created=False
    )
    no_op = DBIAdminService(no_op_repository).register_principal(
        actor,
        actor_membership_id=actor_membership_id,
        principal_id=target_id,
        target_principal_ref="principal-target",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_A}),
        occurred_at=NOW,
        correlation_ref="principal-create-002",
    )
    assert no_op.created is False
    assert [event[0] for event in no_op_repository.events] == [
        "lock",
        "register_principal",
    ]


def validate_membership_creation_created_and_no_op() -> None:
    actor, actor_principal_id, actor_membership_id, repository = _fixture()
    requested = _snapshot(
        principal_ref="principal-target",
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A}),
    )
    membership_id = uuid4()
    principal_id = uuid4()
    evidence = DBIAdminService(repository).create_membership(
        actor,
        requested,
        actor_membership_id=actor_membership_id,
        membership_id=membership_id,
        principal_id=principal_id,
        occurred_at=NOW,
        correlation_ref="membership-create-001",
    )
    assert evidence.created is True
    assert evidence.plan.membership_id == membership_id
    assert evidence.plan.principal_id == principal_id
    assert evidence.plan.requested is requested
    assert [event[0] for event in repository.events] == [
        "lock",
        "hierarchy",
        "create_membership",
    ]
    persisted = repository.events[-1]
    assert persisted[1] == actor_principal_id
    assert persisted[2] == actor_membership_id
    assert persisted[3] is evidence.plan

    actor, _, actor_membership_id, no_op_repository = _fixture(
        membership_created=False
    )
    no_op = DBIAdminService(no_op_repository).create_membership(
        actor,
        requested,
        actor_membership_id=actor_membership_id,
        membership_id=membership_id,
        principal_id=principal_id,
        occurred_at=NOW,
        correlation_ref="membership-create-002",
    )
    assert no_op.created is False
    assert [event[0] for event in no_op_repository.events] == [
        "lock",
        "hierarchy",
        "create_membership",
    ]


def validate_denial_and_hierarchy_stop_persistence() -> None:
    actor, _, actor_membership_id, repository = _fixture()
    _assert_denied(
        lambda: DBIAdminService(repository).register_principal(
            actor,
            actor_membership_id=actor_membership_id,
            principal_id=uuid4(),
            target_principal_ref="principal-actor",
            tenant_ref=TENANT,
            organization_refs=frozenset({ORG_A}),
            occurred_at=NOW,
            correlation_ref="principal-self-001",
        )
    )
    assert [event[0] for event in repository.events] == ["lock"]

    actor, _, actor_membership_id, hierarchy_repository = _fixture(
        hierarchy_matches=False
    )
    requested = _snapshot(
        principal_ref="principal-target",
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A}),
    )
    _assert_conflict(
        lambda: DBIAdminService(hierarchy_repository).create_membership(
            actor,
            requested,
            actor_membership_id=actor_membership_id,
            membership_id=uuid4(),
            principal_id=uuid4(),
            occurred_at=NOW,
            correlation_ref="membership-hierarchy-001",
        )
    )
    assert [event[0] for event in hierarchy_repository.events] == [
        "lock",
        "hierarchy",
    ]


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "admin_service.py"
    ).read_text(encoding="utf-8").lower()
    for required in (
        "class dbiadminprincipalregistrationevidence",
        "class dbiadminmembershipcreationevidence",
        "def register_principal(",
        "def create_membership(",
        "plan_principal_registration(",
        "plan_membership_creation(",
        "created=self._repository.register_principal".replace("created=", "created = "),
        "created=self._repository.create_membership".replace("created=", "created = "),
    ):
        assert required in source
    for forbidden in (
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
    validate_principal_registration_created_and_no_op()
    validate_membership_creation_created_and_no_op()
    validate_denial_and_hierarchy_stop_persistence()
    validate_static_boundaries()
    print("Servicio de altas administrativas DBI aprobado offline.")


if __name__ == "__main__":
    main()
