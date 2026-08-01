"""Valida el modelo y la revisión de auditoría administrativa DBI offline."""

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

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_base import DBIBase  # noqa: E402
from app.dbi import models as dbi_models  # noqa: E402,F401
from app.dbi.models.admin_audit import (  # noqa: E402
    DBI_ADMIN_AUDIT_ACTION_VALUES,
    DBI_ADMIN_AUDIT_RESOURCE_VALUES,
    DBIAdminAuditAction,
    DBIAdminAuditOutcome,
    DBIAdminAuditResourceType,
)

HEAD = "dbi_0007_admin_audit"
TABLE = "dbi_admin_audit_events"
EXPECTED_COLUMNS = {
    "id",
    "actor_principal_id",
    "actor_membership_id",
    "tenant_ref",
    "organization_ref",
    "action",
    "resource_type",
    "resource_ref",
    "outcome",
    "correlation_ref",
    "occurred_at",
}
EXPECTED_INDEXES = {
    "ix_dbi_admin_audit_tenant_occurred",
    "ix_dbi_admin_audit_organization_occurred",
    "ix_dbi_admin_audit_actor_occurred",
    "ix_dbi_admin_audit_resource",
}
EXPECTED_CHECKS = {
    "ck_dbi_admin_audit_action",
    "ck_dbi_admin_audit_resource_type",
    "ck_dbi_admin_audit_outcome",
    "ck_dbi_admin_audit_tenant_ref",
    "ck_dbi_admin_audit_organization_ref",
    "ck_dbi_admin_audit_resource_ref",
    "ck_dbi_admin_audit_correlation_ref",
}


def validate_metadata_contract() -> None:
    assert TABLE in DBIBase.metadata.tables
    table = DBIBase.metadata.tables[TABLE]
    assert set(table.c) == EXPECTED_COLUMNS
    assert not ({"payload", "description", "details", "metadata"} & set(table.c))

    foreign_keys = {
        (str(foreign_key.column), foreign_key.ondelete)
        for foreign_key in table.foreign_keys
    }
    assert foreign_keys == {
        ("dbi_principals.id", "RESTRICT"),
        ("dbi_memberships.id", "RESTRICT"),
    }

    assert {index.name for index in table.indexes} == EXPECTED_INDEXES
    assert {
        constraint.name
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    } == EXPECTED_CHECKS
    assert any(
        constraint.name == "uq_dbi_admin_audit_correlation_resource"
        for constraint in table.constraints
    )


def validate_enums_are_closed() -> None:
    assert DBI_ADMIN_AUDIT_ACTION_VALUES == tuple(
        action.value for action in DBIAdminAuditAction
    )
    assert DBI_ADMIN_AUDIT_RESOURCE_VALUES == tuple(
        resource.value for resource in DBIAdminAuditResourceType
    )
    assert set(DBI_ADMIN_AUDIT_ACTION_VALUES) == {
        "principal_registered",
        "membership_created",
        "membership_activated",
        "membership_inactivated",
        "membership_revoked",
        "membership_permissions_replaced",
        "membership_scopes_replaced",
    }
    assert set(DBI_ADMIN_AUDIT_RESOURCE_VALUES) == {
        "principal",
        "membership",
    }
    assert tuple(DBIAdminAuditOutcome) == (DBIAdminAuditOutcome.SUCCEEDED,)


def validate_migration_graph_and_sql() -> None:
    config = Config(str(BACKEND / "dbi_alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_bases() == ["dbi_0001_baseline"]
    assert scripts.get_heads() == [HEAD]

    revision = scripts.get_revision(HEAD)
    assert revision is not None
    assert revision.down_revision == "dbi_0006_plot_boundaries"

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
    for required in (
        TABLE,
        "dbi_0007_admin_audit",
        "uq_dbi_admin_audit_correlation_resource",
        "ix_dbi_admin_audit_organization_occurred",
        "foreign key(actor_principal_id)",
        "foreign key(actor_membership_id)",
    ):
        assert required in sql
    for forbidden in (
        "admin_audit_logs",
        "users",
        "companies",
        "jsonb",
        " payload ",
        " description ",
        "drop database",
    ):
        assert forbidden not in sql


def validate_source_boundaries() -> None:
    model_source = (
        BACKEND / "app" / "dbi" / "models" / "admin_audit.py"
    ).read_text(encoding="utf-8").lower()
    migration_source = (
        BACKEND
        / "dbi_alembic"
        / "versions"
        / "20260801_07_admin_audit.py"
    ).read_text(encoding="utf-8").lower()

    for required in (
        "dbi_admin_audit_events",
        "ondelete=\"restrict\"",
        "outcome = 'succeeded'",
        "correlation_ref",
    ):
        assert required in model_source

    for forbidden in (
        "app.models.user",
        "app.models.company",
        "app.db.base",
        "jsonb",
        "payload",
        "description",
        "relationship(",
        "database_url",
        "create_engine",
        "sessionmaker",
    ):
        assert forbidden not in model_source

    assert 'revision: str = "dbi_0007_admin_audit"' in migration_source
    assert '"dbi_0006_plot_boundaries"' in migration_source
    assert "alter_column" not in migration_source
    assert "drop database" not in migration_source
    assert "users" not in migration_source
    assert "companies" not in migration_source


def main() -> None:
    validate_metadata_contract()
    validate_enums_are_closed()
    validate_migration_graph_and_sql()
    validate_source_boundaries()
    print("Auditoría administrativa DBI aprobada offline.")


if __name__ == "__main__":
    main()
