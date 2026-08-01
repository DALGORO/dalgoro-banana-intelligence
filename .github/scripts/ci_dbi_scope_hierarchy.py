"""Valida la integridad jerárquica de ámbitos DBI completamente offline."""

from __future__ import annotations

import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_base import DBIBase  # noqa: E402
from app.dbi import models as dbi_models  # noqa: E402,F401

HEAD = "dbi_0008_scope_hierarchy"
DOWN_REVISION = "dbi_0007_admin_audit"
EXPECTED_CONSTRAINTS = {
    "uq_dbi_farms_id_organization",
    "uq_dbi_plots_id_farm",
    "fk_dbi_membership_scopes_farm_organization",
    "fk_dbi_membership_scopes_plot_farm",
}


def _constraint(table_name: str, name: str):
    table = DBIBase.metadata.tables[table_name]
    return next(
        constraint
        for constraint in table.constraints
        if constraint.name == name
    )


def validate_metadata_contract() -> None:
    farm_identity = _constraint(
        "dbi_farms",
        "uq_dbi_farms_id_organization",
    )
    assert isinstance(farm_identity, UniqueConstraint)
    assert [column.name for column in farm_identity.columns] == [
        "id",
        "organization_ref",
    ]

    plot_identity = _constraint(
        "dbi_plots",
        "uq_dbi_plots_id_farm",
    )
    assert isinstance(plot_identity, UniqueConstraint)
    assert [column.name for column in plot_identity.columns] == [
        "id",
        "farm_id",
    ]

    farm_scope = _constraint(
        "dbi_membership_scopes",
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
        "dbi_membership_scopes",
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


def validate_linear_migration_and_sql() -> None:
    config = Config(str(BACKEND / "dbi_alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_bases() == ["dbi_0001_baseline"]
    assert scripts.get_heads() == [HEAD]
    revision = scripts.get_revision(HEAD)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION

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

    sql = output.getvalue().lower()
    assert HEAD in sql
    for constraint_name in EXPECTED_CONSTRAINTS:
        assert constraint_name in sql
    assert "foreign key(farm_id, organization_ref)" in " ".join(sql.split())
    assert "foreign key(plot_id, farm_id)" in " ".join(sql.split())
    assert "on delete restrict" in " ".join(sql.split())


def validate_source_boundaries() -> None:
    migration_source = (
        BACKEND
        / "dbi_alembic"
        / "versions"
        / "20260801_08_scope_hierarchy.py"
    ).read_text(encoding="utf-8").lower()
    agriculture_source = (
        BACKEND / "app" / "dbi" / "models" / "agriculture.py"
    ).read_text(encoding="utf-8").lower()
    identity_source = (
        BACKEND / "app" / "dbi" / "models" / "identity.py"
    ).read_text(encoding="utf-8").lower()

    assert 'revision: str = "dbi_0008_scope_hierarchy"' in migration_source
    assert '"dbi_0007_admin_audit"' in migration_source
    for constraint_name in EXPECTED_CONSTRAINTS:
        assert constraint_name in migration_source
    assert "uq_dbi_farms_id_organization" in agriculture_source
    assert "uq_dbi_plots_id_farm" in agriculture_source
    assert "fk_dbi_membership_scopes_farm_organization" in identity_source
    assert "fk_dbi_membership_scopes_plot_farm" in identity_source

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
        assert forbidden not in migration_source


def main() -> None:
    validate_metadata_contract()
    validate_linear_migration_and_sql()
    validate_source_boundaries()
    print("Jerarquía organizacional de ámbitos DBI aprobada offline.")


if __name__ == "__main__":
    main()
