"""Valida consultas y bloqueos administrativos DBI completamente offline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_repository import (  # noqa: E402
    DBIAdminRepository,
    organization_advisory_lock_key,
)

ORG_A = "organization-a"
ORG_B = "organization-b"
TENANT = "tenant-a"


class _ScalarView:
    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _Result:
    def __init__(
        self,
        *,
        scalar_values: tuple[object, ...] = (),
        rows: tuple[tuple[object, ...], ...] = (),
    ) -> None:
        self._scalar_values = scalar_values
        self._rows = rows

    def scalars(self) -> _ScalarView:
        return _ScalarView(self._scalar_values)

    def all(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class _FakeSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.added: list[object] = []
        self.scalar_values: tuple[object, ...] = ()
        self.rows: tuple[tuple[object, ...], ...] = ()

    def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(
            scalar_values=self.scalar_values,
            rows=self.rows,
        )

    def add(self, entity: object) -> None:
        self.added.append(entity)


def _compiled(statement: Any) -> tuple[str, dict[str, object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(compiled).lower().split()), dict(compiled.params)


def _param_values(params: dict[str, object]) -> set[object]:
    values: set[object] = set()
    for value in params.values():
        if isinstance(value, (tuple, list, set, frozenset)):
            values.update(value)
        else:
            values.add(value)
    return values


def _assert_rejected(factory, expected_error: type[Exception]) -> None:
    try:
        factory()
    except expected_error:
        return
    raise AssertionError(f"La operación debía lanzar {expected_error.__name__}.")


def validate_lock_key_contract() -> None:
    first = organization_advisory_lock_key(
        tenant_ref=TENANT,
        organization_ref=ORG_A,
    )
    repeated = organization_advisory_lock_key(
        tenant_ref=TENANT,
        organization_ref=ORG_A,
    )
    other_tenant = organization_advisory_lock_key(
        tenant_ref="tenant-b",
        organization_ref=ORG_A,
    )
    other_organization = organization_advisory_lock_key(
        tenant_ref=TENANT,
        organization_ref=ORG_B,
    )

    assert first == repeated
    assert first not in {0, other_tenant, other_organization}
    assert -(2**63) <= first < 2**63
    _assert_rejected(
        lambda: organization_advisory_lock_key(
            tenant_ref="*",
            organization_ref=ORG_A,
        ),
        ValueError,
    )


def validate_row_locking_queries() -> None:
    session = _FakeSession()
    repository = DBIAdminRepository(session)
    principal_id = uuid4()
    membership_a = uuid4()
    membership_b = uuid4()

    repository.list_principals_by_legacy_ref(
        legacy_identity_ref="legacy-identity",
        for_update=True,
    )
    principal_sql, principal_params = _compiled(session.statements[-1])
    assert "from dbi_principals" in principal_sql
    assert "for update" in principal_sql
    assert "legacy_identity_ref" in principal_sql
    assert "legacy-identity" in _param_values(principal_params)

    repository.list_memberships(
        principal_id=principal_id,
        tenant_ref=TENANT,
        for_update=True,
    )
    membership_sql, membership_params = _compiled(session.statements[-1])
    membership_values = _param_values(membership_params)
    assert "from dbi_memberships" in membership_sql
    assert "for update" in membership_sql
    assert "tenant_ref" in membership_sql
    assert {principal_id, TENANT}.issubset(membership_values)

    repository.lock_memberships(
        tenant_ref=TENANT,
        membership_ids=frozenset({membership_b, membership_a}),
    )
    lock_sql, lock_params = _compiled(session.statements[-1])
    lock_values = _param_values(lock_params)
    assert "from dbi_memberships" in lock_sql
    assert "order by dbi_memberships.id" in lock_sql
    assert "for update" in lock_sql
    assert TENANT in lock_values
    assert {membership_a, membership_b}.issubset(lock_values)


def validate_organization_advisory_locks() -> None:
    session = _FakeSession()
    repository = DBIAdminRepository(session)
    keys = repository.lock_organization_authority(
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_B, ORG_A}),
    )

    expected = tuple(
        organization_advisory_lock_key(
            tenant_ref=TENANT,
            organization_ref=organization_ref,
        )
        for organization_ref in (ORG_A, ORG_B)
    )
    assert keys == expected
    assert len(session.statements) == 2

    compiled_calls = [_compiled(statement) for statement in session.statements]
    for index, (sql, params) in enumerate(compiled_calls):
        assert "pg_advisory_xact_lock" in sql
        assert expected[index] in _param_values(params)

    _assert_rejected(
        lambda: repository.lock_organization_authority(
            tenant_ref=TENANT,
            organization_refs=frozenset(),
        ),
        ValueError,
    )


def validate_remaining_admin_query() -> None:
    session = _FakeSession()
    session.rows = ((ORG_A, 2),)
    repository = DBIAdminRepository(session)
    excluded_membership_id = uuid4()

    counts = repository.count_remaining_administrators(
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG_A, ORG_B}),
        excluded_membership_id=excluded_membership_id,
    )
    assert counts == {ORG_A: 2, ORG_B: 0}

    sql, params = _compiled(session.statements[-1])
    values = _param_values(params)
    for table in (
        "dbi_membership_scopes",
        "dbi_memberships",
        "dbi_principals",
        "dbi_membership_permissions",
    ):
        assert table in sql
    assert "count(distinct(dbi_memberships.id))" in sql.replace(" ", "")
    assert "group by dbi_membership_scopes.organization_ref" in sql
    assert "dbi_memberships.id !=" in sql
    assert {TENANT, ORG_A, ORG_B, excluded_membership_id}.issubset(values)
    assert {"active", "manage", "organization"}.issubset(values)


def validate_add_without_transaction_side_effects() -> None:
    session = _FakeSession()
    repository = DBIAdminRepository(session)
    entity = object()
    assert repository.add(entity) is entity
    assert session.added == [entity]
    assert session.statements == []


def validate_input_barriers() -> None:
    repository = DBIAdminRepository(_FakeSession())
    _assert_rejected(
        lambda: repository.list_memberships(
            principal_id="not-a-uuid",  # type: ignore[arg-type]
            tenant_ref=TENANT,
        ),
        TypeError,
    )
    _assert_rejected(
        lambda: repository.lock_memberships(
            tenant_ref=TENANT,
            membership_ids=frozenset(),
        ),
        ValueError,
    )
    _assert_rejected(
        lambda: repository.count_remaining_administrators(
            tenant_ref=TENANT,
            organization_refs=frozenset({ORG_A}),
            excluded_membership_id="not-a-uuid",  # type: ignore[arg-type]
        ),
        TypeError,
    )


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "admin_repository.py"
    ).read_text(encoding="utf-8").lower()

    for required in (
        "with_for_update",
        "pg_advisory_xact_lock",
        "count_remaining_administrators",
        "dbimembershipstatus.active",
        "dbiprincipalstatus.active",
        "dbimembershipscopetype.organization",
    ):
        assert required in source

    for forbidden in (
        "create_engine",
        "sessionmaker",
        "sessionlocal",
        "from app.db.session",
        "app.models.user",
        "app.models.company",
        "database_url",
        ".commit(",
        ".rollback(",
        ".close(",
        "delete(",
        "drop table",
        "fastapi",
    ):
        assert forbidden not in source


def main() -> None:
    validate_lock_key_contract()
    validate_row_locking_queries()
    validate_organization_advisory_locks()
    validate_remaining_admin_query()
    validate_add_without_transaction_side_effects()
    validate_input_barriers()
    validate_static_boundaries()
    print("Repositorio administrativo DBI aprobado offline.")


if __name__ == "__main__":
    main()
