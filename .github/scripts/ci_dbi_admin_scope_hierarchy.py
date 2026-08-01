"""Valida integridad jerárquica de ámbitos administrativos DBI offline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_repository import DBIAdminRepository  # noqa: E402
from app.dbi.authorization import DBIFarmScope, DBIPlotScope  # noqa: E402
from app.dbi.models.agriculture import Farm, Plot  # noqa: E402
from app.dbi.models.identity import DBIMembershipScope  # noqa: E402

ORG_A = "organization-a"
ORG_B = "organization-b"


class _Result:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, results: tuple[_Result, ...] = ()) -> None:
        self.results = list(results)
        self.statements: list[Any] = []

    def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        if not self.results:
            raise AssertionError("No había resultado preparado para la consulta.")
        return self.results.pop(0)


def _compiled(statement: Any) -> str:
    compiled = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(compiled).lower().split())


def _assert_type_error(factory) -> None:
    try:
        factory()
    except TypeError:
        return
    raise AssertionError("La entrada jerárquica inválida debía rechazarse.")


def validate_exact_hierarchy_queries() -> None:
    farm_id = uuid4()
    plot_id = uuid4()
    farm_scope = DBIFarmScope(organization_ref=ORG_A, farm_id=farm_id)
    plot_scope = DBIPlotScope(
        organization_ref=ORG_A,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    session = _FakeSession(
        (
            _Result(((farm_id, ORG_A),)),
            _Result(((plot_id, farm_id, ORG_A),)),
        )
    )
    repository = DBIAdminRepository(session)  # type: ignore[arg-type]

    assert repository.scope_hierarchy_matches(
        farm_scopes=frozenset({farm_scope}),
        plot_scopes=frozenset({plot_scope}),
    ) is True
    assert len(session.statements) == 2

    farm_sql = _compiled(session.statements[0])
    plot_sql = _compiled(session.statements[1])
    assert "from dbi_farms" in farm_sql
    assert "dbi_farms.id in" in farm_sql
    assert "from dbi_plots join dbi_farms" in plot_sql
    assert "dbi_plots.farm_id = dbi_farms.id" in plot_sql
    assert "dbi_plots.id in" in plot_sql


def validate_mismatch_and_empty_contract() -> None:
    farm_id = uuid4()
    plot_id = uuid4()
    farm_scope = DBIFarmScope(organization_ref=ORG_A, farm_id=farm_id)
    plot_scope = DBIPlotScope(
        organization_ref=ORG_A,
        farm_id=farm_id,
        plot_id=plot_id,
    )

    farm_mismatch = DBIAdminRepository(
        _FakeSession((_Result(((farm_id, ORG_B),)),))  # type: ignore[arg-type]
    )
    assert farm_mismatch.scope_hierarchy_matches(
        farm_scopes=frozenset({farm_scope}),
        plot_scopes=frozenset(),
    ) is False

    plot_mismatch = DBIAdminRepository(
        _FakeSession(
            (
                _Result(((plot_id, uuid4(), ORG_A),)),
            )
        )  # type: ignore[arg-type]
    )
    assert plot_mismatch.scope_hierarchy_matches(
        farm_scopes=frozenset(),
        plot_scopes=frozenset({plot_scope}),
    ) is False

    empty_session = _FakeSession()
    assert DBIAdminRepository(  # type: ignore[arg-type]
        empty_session
    ).scope_hierarchy_matches(
        farm_scopes=frozenset(),
        plot_scopes=frozenset(),
    ) is True
    assert empty_session.statements == []

    repository = DBIAdminRepository(_FakeSession())  # type: ignore[arg-type]
    _assert_type_error(
        lambda: repository.scope_hierarchy_matches(
            farm_scopes=set(),  # type: ignore[arg-type]
            plot_scopes=frozenset(),
        )
    )
    _assert_type_error(
        lambda: repository.scope_hierarchy_matches(
            farm_scopes=frozenset(),
            plot_scopes=frozenset({object()}),  # type: ignore[arg-type]
        )
    )


def validate_metadata_constraints() -> None:
    farm_constraints = {
        constraint.name for constraint in Farm.__table__.constraints
    }
    plot_constraints = {
        constraint.name for constraint in Plot.__table__.constraints
    }
    scope_constraints = {
        constraint.name for constraint in DBIMembershipScope.__table__.constraints
    }

    assert "uq_dbi_farms_id_organization" in farm_constraints
    assert "uq_dbi_plots_id_farm" in plot_constraints
    assert (
        "fk_dbi_membership_scopes_farm_organization" in scope_constraints
    )
    assert "fk_dbi_membership_scopes_plot_farm" in scope_constraints


def validate_migration_contract() -> None:
    path = (
        BACKEND
        / "dbi_alembic"
        / "versions"
        / "20260801_08_scope_hierarchy.py"
    )
    source = path.read_text(encoding="utf-8").lower()
    for required in (
        'revision: str = "dbi_0008_scope_hierarchy"',
        '"dbi_0007_admin_audit"',
        '"uq_dbi_farms_id_organization"',
        '"uq_dbi_plots_id_farm"',
        '"fk_dbi_membership_scopes_farm_organization"',
        '"fk_dbi_membership_scopes_plot_farm"',
        "op.create_unique_constraint",
        "op.create_foreign_key",
        "op.drop_constraint",
    ):
        assert required in source


def validate_static_boundaries() -> None:
    repository_source = (
        BACKEND / "app" / "dbi" / "admin_repository.py"
    ).read_text(encoding="utf-8").lower()
    assert "def scope_hierarchy_matches" in repository_source
    assert "select(farm.id, farm.organization_ref)" in repository_source
    assert "select(plot.id, plot.farm_id, farm.organization_ref)" in repository_source
    for forbidden in (
        ".commit(",
        ".rollback(",
        "create_engine",
        "sessionmaker",
        "database_url",
        "app.models.user",
        "app.models.company",
    ):
        assert forbidden not in repository_source


def main() -> None:
    validate_exact_hierarchy_queries()
    validate_mismatch_and_empty_contract()
    validate_metadata_constraints()
    validate_migration_contract()
    validate_static_boundaries()
    print("Jerarquía administrativa DBI aprobada offline.")


if __name__ == "__main__":
    main()
