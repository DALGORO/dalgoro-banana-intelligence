"""Valida identidad y membresías DBI completamente offline."""

from __future__ import annotations

import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.dbi_base import DBIBase  # noqa: E402
from app.dbi import models as dbi_models  # noqa: E402, F401
from app.dbi.authorization import (  # noqa: E402
    DENIED_MESSAGE,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.identity import (  # noqa: E402
    DBIAccessContextResolver,
    DBIIdentityRepository,
)
from app.dbi.models.identity import (  # noqa: E402
    DBI_PERMISSION_VALUES,
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
    DBIMembershipStatus,
    DBIPrincipal,
    DBIPrincipalStatus,
)

LEGACY_HEADS = {
    "20260411_01",
    "2cec060d9aa4",
    "7ce73aae44ce",
}
NEW_TABLES = {
    "dbi_principals",
    "dbi_memberships",
    "dbi_membership_permissions",
    "dbi_membership_scopes",
}


class FakeResult:
    """Resultado mínimo para consultas SQLAlchemy offline."""

    def __init__(
        self,
        *,
        values: tuple[object, ...] = (),
        scalar: object | None = None,
    ) -> None:
        self._values = values
        self._scalar = scalar

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> tuple[object, ...]:
        return self._values

    def scalar_one_or_none(self) -> object | None:
        return self._scalar


class RecordingSession:
    """Doble que registra sentencias sin crear motor o conexión."""

    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.scalar = uuid4()

    def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(scalar=self.scalar)


class FakeIdentityRepository:
    """Autoridad en memoria para probar únicamente el resolvedor."""

    def __init__(
        self,
        *,
        principals: tuple[DBIPrincipal, ...],
        memberships: tuple[DBIMembership, ...],
        permissions: tuple[DBIMembershipPermission, ...],
        scopes: tuple[DBIMembershipScope, ...],
        farm_matches: set[tuple[str, UUID]],
        plot_matches: set[tuple[str, UUID, UUID]],
    ) -> None:
        self.principals = principals
        self.memberships = memberships
        self.permissions = permissions
        self.scopes = scopes
        self.farm_matches = farm_matches
        self.plot_matches = plot_matches

    def list_principals(
        self,
        *,
        legacy_identity_ref: str,
    ) -> tuple[DBIPrincipal, ...]:
        return self.principals

    def list_memberships(
        self,
        *,
        principal_id: UUID,
        tenant_ref: str,
    ) -> tuple[DBIMembership, ...]:
        return self.memberships

    def list_permissions(
        self,
        *,
        membership_id: UUID,
    ) -> tuple[DBIMembershipPermission, ...]:
        return self.permissions

    def list_scopes(
        self,
        *,
        membership_id: UUID,
    ) -> tuple[DBIMembershipScope, ...]:
        return self.scopes

    def farm_matches_scope(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
    ) -> bool:
        return (organization_ref, farm_id) in self.farm_matches

    def plot_matches_scope(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> bool:
        return (
            organization_ref,
            farm_id,
            plot_id,
        ) in self.plot_matches


def _repository_fixture() -> tuple[
    FakeIdentityRepository,
    DBIPrincipal,
    DBIMembership,
    UUID,
    UUID,
]:
    principal_id = uuid4()
    membership_id = uuid4()
    farm_id = uuid4()
    plot_id = uuid4()
    principal = DBIPrincipal(
        id=principal_id,
        legacy_identity_ref="legacy-user-001",
        status=DBIPrincipalStatus.ACTIVE.value,
    )
    membership = DBIMembership(
        id=membership_id,
        principal_id=principal_id,
        tenant_ref="tenant-001",
        status=DBIMembershipStatus.ACTIVE.value,
    )
    permissions = (
        DBIMembershipPermission(
            membership_id=membership_id,
            permission=DBIPermission.READ.value,
        ),
        DBIMembershipPermission(
            membership_id=membership_id,
            permission=DBIPermission.SUBMIT_ANALYSIS.value,
        ),
    )
    scopes = (
        DBIMembershipScope(
            id=uuid4(),
            membership_id=membership_id,
            scope_type=DBIMembershipScopeType.ORGANIZATION.value,
            organization_ref="organization-001",
        ),
        DBIMembershipScope(
            id=uuid4(),
            membership_id=membership_id,
            scope_type=DBIMembershipScopeType.FARM.value,
            organization_ref="organization-001",
            farm_id=farm_id,
        ),
        DBIMembershipScope(
            id=uuid4(),
            membership_id=membership_id,
            scope_type=DBIMembershipScopeType.PLOT.value,
            organization_ref="organization-001",
            farm_id=farm_id,
            plot_id=plot_id,
        ),
    )
    repository = FakeIdentityRepository(
        principals=(principal,),
        memberships=(membership,),
        permissions=permissions,
        scopes=scopes,
        farm_matches={("organization-001", farm_id)},
        plot_matches={("organization-001", farm_id, plot_id)},
    )
    return repository, principal, membership, farm_id, plot_id


def validate_metadata_authority() -> None:
    """Comprueba tablas, referencias y restricciones exclusivas de DBI."""

    assert NEW_TABLES.issubset(DBIBase.metadata.tables)
    expected_permissions = tuple(
        permission.value for permission in DBIPermission
    )
    assert DBI_PERMISSION_VALUES == expected_permissions

    foreign_targets = {
        str(foreign_key.column)
        for table_name in NEW_TABLES
        for foreign_key in DBIBase.metadata.tables[table_name].foreign_keys
    }
    assert foreign_targets == {
        "dbi_principals.id",
        "dbi_memberships.id",
        "dbi_farms.id",
        "dbi_plots.id",
    }
    assert not any(
        legacy in target
        for target in foreign_targets
        for legacy in ("users", "companies")
    )

    principal_table = DBIBase.metadata.tables["dbi_principals"]
    membership_table = DBIBase.metadata.tables["dbi_memberships"]
    scope_table = DBIBase.metadata.tables["dbi_membership_scopes"]
    assert "legacy_identity_ref" in principal_table.c
    assert "tenant_ref" in membership_table.c
    assert "organization_ref" in scope_table.c

    scope_indexes = {
        index.name: index
        for index in scope_table.indexes
        if index.unique
    }
    assert set(scope_indexes) == {
        "uq_dbi_membership_scopes_organization",
        "uq_dbi_membership_scopes_farm",
        "uq_dbi_membership_scopes_plot",
    }
    for index in scope_indexes.values():
        assert index.dialect_options["postgresql"]["where"] is not None


def validate_migration_and_offline_sql() -> None:
    """Comprueba el linaje de identidad y genera el historial sin conexión."""

    legacy_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    legacy_scripts = ScriptDirectory.from_config(legacy_config)
    assert set(legacy_scripts.get_heads()) == LEGACY_HEADS

    dbi_config = Config(str(BACKEND_ROOT / "dbi_alembic.ini"))
    dbi_scripts = ScriptDirectory.from_config(dbi_config)
    assert dbi_scripts.get_bases() == ["dbi_0001_baseline"]
    heads = dbi_scripts.get_heads()
    assert len(heads) == 1
    lineage = {
        revision.revision
        for revision in dbi_scripts.iterate_revisions(heads[0], "base")
    }
    assert "dbi_0005_identity_memberships" in lineage
    identity_revision = dbi_scripts.get_revision(
        "dbi_0005_identity_memberships"
    )
    assert identity_revision is not None
    assert identity_revision.down_revision == "dbi_0004_assets_artifacts"

    output = StringIO()
    environment = {
        "DBI_ENVIRONMENT": "test",
        "DBI_DATABASE_URL": (
            "postgresql+psycopg://dbi_user:dbi-password"
            "@example.internal:5432/dbi_test"
        ),
    }
    with patch.dict(os.environ, environment, clear=True):
        with redirect_stdout(output):
            command.upgrade(dbi_config, "head", sql=True)

    sql = output.getvalue().lower()
    for table_name in NEW_TABLES:
        assert table_name in sql
    assert "dbi_0004_assets_artifacts" in (
        BACKEND_ROOT
        / "dbi_alembic"
        / "versions"
        / "20260729_05_identity_memberships.py"
    ).read_text(encoding="utf-8")
    assert "users" not in sql
    assert "companies" not in sql
    assert "drop database" not in sql


def _compiled(statement: Any) -> tuple[str, set[object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled).lower(), set(compiled.params.values())


def validate_repository_queries() -> None:
    """Compila todas las consultas sobre una sesión falsa."""

    session = RecordingSession()
    repository = DBIIdentityRepository(session)  # type: ignore[arg-type]
    principal_id = uuid4()
    membership_id = uuid4()
    farm_id = uuid4()
    plot_id = uuid4()

    calls = (
        (
            repository.list_principals,
            {"legacy_identity_ref": "legacy-user-001"},
            {"dbi_principals"},
            {"legacy-user-001"},
        ),
        (
            repository.list_memberships,
            {
                "principal_id": principal_id,
                "tenant_ref": "tenant-001",
            },
            {"dbi_memberships"},
            {principal_id, "tenant-001"},
        ),
        (
            repository.list_permissions,
            {"membership_id": membership_id},
            {"dbi_membership_permissions"},
            {membership_id},
        ),
        (
            repository.list_scopes,
            {"membership_id": membership_id},
            {"dbi_membership_scopes"},
            {membership_id},
        ),
        (
            repository.farm_matches_scope,
            {
                "organization_ref": "organization-001",
                "farm_id": farm_id,
            },
            {"dbi_farms"},
            {"organization-001", farm_id},
        ),
        (
            repository.plot_matches_scope,
            {
                "organization_ref": "organization-001",
                "farm_id": farm_id,
                "plot_id": plot_id,
            },
            {"dbi_plots", "dbi_farms"},
            {"organization-001", farm_id, plot_id},
        ),
    )

    for method, arguments, expected_tables, expected_values in calls:
        method(**arguments)
        sql, values = _compiled(session.statements[-1])
        assert expected_tables.issubset(set(sql.split()))
        assert expected_values.issubset(values)


def validate_valid_resolution() -> None:
    """Comprueba contexto completo y membresía válida solo de tenant."""

    repository, principal, membership, farm_id, plot_id = (
        _repository_fixture()
    )
    context = DBIAccessContextResolver(repository).resolve(
        legacy_identity_ref="legacy-user-001",
        tenant_ref="tenant-001",
    )
    assert context.principal_ref == str(principal.id)
    assert context.tenant_ref == membership.tenant_ref
    assert context.permissions == frozenset(
        {
            DBIPermission.READ,
            DBIPermission.SUBMIT_ANALYSIS,
        }
    )
    assert context.organization_refs == frozenset({"organization-001"})
    assert context.farm_scopes == frozenset(
        {
            DBIFarmScope(
                organization_ref="organization-001",
                farm_id=farm_id,
            )
        }
    )
    assert context.plot_scopes == frozenset(
        {
            DBIPlotScope(
                organization_ref="organization-001",
                farm_id=farm_id,
                plot_id=plot_id,
            )
        }
    )

    repository.scopes = ()
    context = DBIAccessContextResolver(repository).resolve(
        legacy_identity_ref="legacy-user-001",
        tenant_ref="tenant-001",
    )
    assert context.organization_refs == frozenset()
    assert context.farm_scopes == frozenset()
    assert context.plot_scopes == frozenset()


def _assert_denied(operation: Callable[[], object]) -> None:
    try:
        operation()
    except DBIAccessDenied as error:
        assert type(error) is DBIAccessDenied
        assert str(error) == DENIED_MESSAGE
    else:
        raise AssertionError("El resolvedor aceptó autoridad inválida.")


def validate_closed_denials() -> None:
    """Comprueba ausencia, duplicidad, inactividad e inconsistencia."""

    operations: list[Callable[[], object]] = []

    repository, principal, membership, _, _ = _repository_fixture()
    resolver = DBIAccessContextResolver(repository)
    operations.extend(
        [
            lambda: resolver.resolve(
                legacy_identity_ref="*",
                tenant_ref="tenant-001",
            ),
            lambda: resolver.resolve(
                legacy_identity_ref="legacy-user-001",
                tenant_ref="ANY",
            ),
        ]
    )

    repository, principal, membership, _, _ = _repository_fixture()
    repository.principals = ()
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    repository.principals = (principal, principal)
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    principal.status = DBIPrincipalStatus.INACTIVE.value
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    principal.legacy_identity_ref = "legacy-user-other"
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    repository.memberships = ()
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    repository.memberships = (membership, membership)
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    membership.tenant_ref = "tenant-other"
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    membership.status = DBIMembershipStatus.REVOKED.value
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    membership.status = DBIMembershipStatus.INACTIVE.value
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    membership.principal_id = uuid4()
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    repository.permissions = ()
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    duplicate = DBIMembershipPermission(
        membership_id=membership.id,
        permission=DBIPermission.READ.value,
    )
    repository.permissions = (duplicate, duplicate)
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    repository.permissions = (
        DBIMembershipPermission(
            membership_id=membership.id,
            permission="unknown",
        ),
    )
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    repository.permissions = (
        DBIMembershipPermission(
            membership_id=uuid4(),
            permission=DBIPermission.READ.value,
        ),
    )
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    repository.scopes = (repository.scopes[-1], repository.scopes[-1])
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    repository.farm_matches = set()
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    repository, principal, membership, _, _ = _repository_fixture()
    repository.plot_matches = set()
    operations.append(
        lambda repository=repository: DBIAccessContextResolver(
            repository
        ).resolve(
            legacy_identity_ref="legacy-user-001",
            tenant_ref="tenant-001",
        )
    )

    for operation in operations:
        _assert_denied(operation)


def validate_source_boundaries() -> None:
    """Bloquea autenticación heredada, conexiones y efectos laterales."""

    identity_source = (
        BACKEND_ROOT / "app" / "dbi" / "identity.py"
    ).read_text(encoding="utf-8").lower()
    model_source = (
        BACKEND_ROOT / "app" / "dbi" / "models" / "identity.py"
    ).read_text(encoding="utf-8").lower()
    migration_source = (
        BACKEND_ROOT
        / "dbi_alembic"
        / "versions"
        / "20260729_05_identity_memberships.py"
    ).read_text(encoding="utf-8").lower()

    combined = "\n".join((identity_source, model_source, migration_source))
    for forbidden in (
        "fastapi",
        "app.core.security",
        "app.models.user",
        "app.models.company",
        "app.db.session",
        "app.db.dbi_session",
        "create_engine",
        "sessionmaker",
        ".connect(",
        ".commit(",
        ".rollback(",
        ".close(",
        "decode_token",
        "depends(",
        "httpexception",
        "celery",
        "redis",
        "rabbit",
        "boto",
        "google.cloud.storage",
        "run_full_pipeline",
    ):
        assert forbidden not in combined

    assert "foreignkey(\"users." not in combined
    assert "foreignkey(\"companies." not in combined
    assert "op.execute(" not in migration_source


def main() -> None:
    """Ejecuta todas las barreras de identidad DBI offline."""

    validate_metadata_authority()
    validate_migration_and_offline_sql()
    validate_repository_queries()
    validate_valid_resolution()
    validate_closed_denials()
    validate_source_boundaries()
    print("Identidad y membresías DBI: validación offline aprobada.")


if __name__ == "__main__":
    main()
