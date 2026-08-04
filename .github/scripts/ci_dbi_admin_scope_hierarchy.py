"""Valida integridad jerárquica de ámbitos administrativos DBI offline."""

from __future__ import annotations

import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
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
HEAD = "dbi_0011_flight_manifest"
HIERARCHY_REVISION = "dbi_0008_scope_hierarchy"
DOWN_REVISION = "dbi_0007_admin_audit"
EXPECTED_CONSTRAINTS = {
    "uq_dbi_farms_id_organization",
    "uq_dbi_plots_id_farm",
    "fk_dbi_membership_scopes_farm_organization",
    "fk_dbi_membership_scopes_plot_farm",
}


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


def _constraint(table, name: str):
    return next(
        constraint
        for constraint in table.constraints
        if constraint.name == name
    )


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
    farm_identity = _constraint(
        Farm.__table__,
        "uq_dbi_farms_id_organization",
    )
    assert isinstance(farm_identity, UniqueConstraint)
    assert [column.name for column in farm_identity.columns] == [
        "id",
        "organization_ref",
    ]

    plot_identity = _constraint(
        Plot.__table__,
        "uq_dbi_plots_id_farm",
    )
    assert isinstance(plot_identity, UniqueConstraint)
    assert [column.name for column in plot_identity.columns] == [
        "id",
        "farm_id",
    ]

    farm_scope = _constraint(
        DBIMembershipScope.__table__,
        "fk_dbi_membership_scopes_farm_organization",
    )
    assert isinstance(farm_scope, ForeignKeyConstraint)
    assert [column.name for column in farm_scope.columns] == [
        "farm_id",
        "organization_ref",
    ]
    assert [element.target_fullname for element in farm_scope.elements] == [
        "dbi_farms.id",
        "dbi_farms.organization_ref",
    ]
    assert farm_scope.ondelete == "RESTRICT"

    plot_scope = _constraint(
        DBIMembershipScope.__table__,
        "fk_dbi_membership_scopes_plot_farm",
    )
    assert isinstance(plot_scope, ForeignKeyConstraint)
    assert [column.name for column in plot_scope.columns] == [
        "plot_id",
        "farm_id",
    ]
    assert [element.target_fullname for element in plot_scope.elements] == [
        "dbi_plots.id",
        "dbi_plots.farm_id",
    ]
    assert plot_scope.ondelete == "RESTRICT"


def validate_migration_contract() -> None:
    config = Config(str(BACKEND / "dbi_alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_bases() == ["dbi_0001_baseline"]
    assert scripts.get_heads() == [HEAD]
    revision = scripts.get_revision(HIERARCHY_REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    lineage = {
        item.revision
        for item in scripts.iterate_revisions(HEAD, "base")
    }
    assert HIERARCHY_REVISION in lineage

    output = StringIO()
    environment = {
        "DBI_ENVIRONMENT": "test",
        "DBI_DATABASE_URL": (
            "postgresql+psycopg://dbi_test_migrator:placeholder@"
            "example.invalid:5432/dbi_test"
        ),
    }
    with patch.dict(os.environ, environment, clear=True):
        with redirect_stdout(output):
            command.upgrade(config, "head", sql=True)

    sql = " ".join(output.getvalue().lower().split())
    assert HEAD in sql
    for constraint_name in EXPECTED_CONSTRAINTS:
        assert constraint_name in sql
    assert "foreign key(farm_id, organization_ref)" in sql
    assert "foreign key(plot_id, farm_id)" in sql
    assert "on delete restrict" in sql

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
    for forbidden in (
        "op.execute",
        "op.bulk_insert",
        "alter_column",
        "drop database",
        "truncate ",
        "users",
        "companies",
        "documents",
    ):
        assert forbidden not in source


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
