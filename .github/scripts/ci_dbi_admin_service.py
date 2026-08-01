"""Valida las guardas administrativas DBI sin persistencia ni API."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

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
)
from app.dbi.admin_service import DBIAdminService  # noqa: E402
from app.dbi.authorization import DBIPermission  # noqa: E402

TENANT = "tenant-a"
ORG_A = "organization-a"
ORG_B = "organization-b"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


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


class _FakeRepository:
    def __init__(self, *, remaining_counts: dict[str, int] | None = None) -> None:
        self.events: list[tuple[object, ...]] = []
        self.remaining_counts = remaining_counts or {}

    def lock_organization_authority(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
    ) -> tuple[int, ...]:
        organizations = tuple(sorted(organization_refs))
        self.events.append(("lock", tenant_ref, organizations))
        return tuple(range(101, 101 + len(organizations)))

    def count_remaining_administrators(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        excluded_membership_id: UUID,
    ) -> dict[str, int]:
        organizations = tuple(sorted(organization_refs))
        self.events.append(
            (
                "count",
                tenant_ref,
                organizations,
                excluded_membership_id,
            )
        )
        return {
            organization_ref: self.remaining_counts.get(organization_ref, 0)
            for organization_ref in organizations
        }


def _assert_denied(factory) -> None:
    try:
        factory()
    except DBIAdminDenied as error:
        assert str(error) == ADMIN_DENIED_MESSAGE
        return
    raise AssertionError("La guarda administrativa debía denegar la operación.")


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAdminConflict as error:
        assert str(error) == ADMIN_CONFLICT_MESSAGE
        return
    raise AssertionError("La guarda administrativa debía producir conflicto.")


def validate_principal_registration_guard() -> None:
    repository = _FakeRepository()
    evidence = DBIAdminService(repository).guard_principal_registration(
        _actor(),
        target_principal_ref="principal-new",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_A}),
    )
    assert evidence.tenant_ref == TENANT
    assert evidence.organization_refs == frozenset({ORG_A})
    assert evidence.lock_keys == (101,)
    assert repository.events == [("lock", TENANT, (ORG_A,))]

    denied_repository = _FakeRepository()
    _assert_denied(
        lambda: DBIAdminService(
            denied_repository
        ).guard_principal_registration(
            _actor(permissions=frozenset({DBIPermission.READ})),
            target_principal_ref="principal-new",
            tenant_ref=TENANT,
            organization_refs=frozenset({ORG_A}),
        )
    )
    assert denied_repository.events == []


def validate_membership_create_guard() -> None:
    repository = _FakeRepository()
    requested = _snapshot(
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_B, ORG_A}),
    )
    evidence = DBIAdminService(repository).guard_membership_create(
        _actor(organization_scopes=frozenset({ORG_A, ORG_B})),
        requested,
    )
    assert evidence.organization_refs == frozenset({ORG_A, ORG_B})
    assert evidence.lock_keys == (101, 102)
    assert repository.events == [("lock", TENANT, (ORG_A, ORG_B))]


def validate_membership_change_without_protection() -> None:
    repository = _FakeRepository()
    before = _snapshot(permissions=frozenset({DBIPermission.READ}))
    after = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.WRITE})
    )
    evidence = DBIAdminService(repository).guard_membership_change(
        _actor(),
        before,
        after,
        target_membership_id=uuid4(),
        expected_updated_at=NOW,
        persisted_updated_at=NOW,
    )
    assert evidence.protected_organization_refs == frozenset()
    assert repository.events == [("lock", TENANT, (ORG_A,))]


def validate_last_admin_order_and_result() -> None:
    target_membership_id = uuid4()
    before = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE})
    )
    after = _snapshot(permissions=frozenset({DBIPermission.READ}))

    repository = _FakeRepository(remaining_counts={ORG_A: 1})
    evidence = DBIAdminService(repository).guard_membership_change(
        _actor(),
        before,
        after,
        target_membership_id=target_membership_id,
        expected_updated_at=NOW,
        persisted_updated_at=NOW,
    )
    assert evidence.protected_organization_refs == frozenset({ORG_A})
    assert repository.events == [
        ("lock", TENANT, (ORG_A,)),
        ("count", TENANT, (ORG_A,), target_membership_id),
    ]

    conflict_repository = _FakeRepository(remaining_counts={ORG_A: 0})
    _assert_conflict(
        lambda: DBIAdminService(
            conflict_repository
        ).guard_membership_change(
            _actor(),
            before,
            after,
            target_membership_id=target_membership_id,
            expected_updated_at=NOW,
            persisted_updated_at=NOW,
        )
    )
    assert conflict_repository.events == [
        ("lock", TENANT, (ORG_A,)),
        ("count", TENANT, (ORG_A,), target_membership_id),
    ]


def validate_denial_precedes_version_check() -> None:
    repository = _FakeRepository()
    _assert_denied(
        lambda: DBIAdminService(repository).guard_membership_change(
            _actor(permissions=frozenset({DBIPermission.READ})),
            _snapshot(),
            _snapshot(permissions=frozenset({DBIPermission.READ})),
            target_membership_id=uuid4(),
            expected_updated_at=NOW,
            persisted_updated_at=NOW + timedelta(seconds=1),
        )
    )
    assert repository.events == []


def validate_version_barriers() -> None:
    before = _snapshot(permissions=frozenset({DBIPermission.READ}))
    after = _snapshot(
        permissions=frozenset({DBIPermission.READ, DBIPermission.WRITE})
    )

    repository = _FakeRepository()
    _assert_conflict(
        lambda: DBIAdminService(repository).guard_membership_change(
            _actor(),
            before,
            after,
            target_membership_id=uuid4(),
            expected_updated_at=NOW,
            persisted_updated_at=NOW + timedelta(microseconds=1),
        )
    )
    assert repository.events == []

    naive_repository = _FakeRepository()
    _assert_conflict(
        lambda: DBIAdminService(naive_repository).guard_membership_change(
            _actor(),
            before,
            after,
            target_membership_id=uuid4(),
            expected_updated_at=NOW.replace(tzinfo=None),
            persisted_updated_at=NOW,
        )
    )
    assert naive_repository.events == []

    invalid_id_repository = _FakeRepository()
    _assert_conflict(
        lambda: DBIAdminService(
            invalid_id_repository
        ).guard_membership_change(
            _actor(),
            before,
            after,
            target_membership_id="not-a-uuid",  # type: ignore[arg-type]
            expected_updated_at=NOW,
            persisted_updated_at=NOW,
        )
    )
    assert invalid_id_repository.events == []


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "admin_service.py"
    ).read_text(encoding="utf-8").lower()

    for required in (
        "dbiadminpolicy.require_membership_change",
        "_require_current_version",
        "lock_organization_authority",
        "count_remaining_administrators",
        "for update",
    ):
        assert required in source

    policy_position = source.index("dbiadminpolicy.require_membership_change")
    version_position = source.index("_require_current_version", policy_position)
    lock_position = source.index("lock_organization_authority", version_position)
    count_position = source.index("count_remaining_administrators", lock_position)
    assert policy_position < version_position < lock_position < count_position

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
    validate_principal_registration_guard()
    validate_membership_create_guard()
    validate_membership_change_without_protection()
    validate_last_admin_order_and_result()
    validate_denial_precedes_version_check()
    validate_version_barriers()
    validate_static_boundaries()
    print("Guardas administrativas DBI aprobadas offline.")


if __name__ == "__main__":
    main()
