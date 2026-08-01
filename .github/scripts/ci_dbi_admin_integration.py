"""Prueba funcional administrativa DBI sobre PostgreSQL/PostGIS efímero.

El fixture crea un rol API local con privilegios mínimos, siembra datos
controlados como administrador del contenedor y ejecuta la mutación real con la
fábrica de sesiones DBI. No admite hosts remotos, staging ni producción.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import load_dbi_database_config  # noqa: E402
from app.db.dbi_session import (  # noqa: E402
    create_dbi_engine,
    create_dbi_session_factory,
    dbi_session_scope,
)
from app.dbi.admin_persistence import DBIAdminPersistenceRepository  # noqa: E402
from app.dbi.admin_policy import (  # noqa: E402
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminMembershipStatus,
)
from app.dbi.admin_service import DBIAdminService  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.models.admin_audit import DBIAdminAuditEvent  # noqa: E402
from app.dbi.models.identity import (  # noqa: E402
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
    DBIPrincipal,
)

HOST = "127.0.0.1"
PORT = 5432
DATABASE = "dbi_test"
ADMIN_ROLE = "postgres"
API_ROLE = "dbi_test_api"
TENANT = "tenant-ci-admin"
ORG_A = "organization-ci-a"
ORG_B = "organization-ci-b"
ORG_C = "organization-ci-c"
NOW = datetime(2026, 8, 1, 15, 30, tzinfo=timezone.utc)
NEXT = NOW + timedelta(microseconds=1)
NEXT_AFTER = NEXT + timedelta(microseconds=1)

ACTOR_PRINCIPAL_ID = UUID("10000000-0000-0000-0000-000000000001")
TARGET_PRINCIPAL_ID = UUID("10000000-0000-0000-0000-000000000002")
BACKUP_PRINCIPAL_ID = UUID("10000000-0000-0000-0000-000000000003")
ACTOR_MEMBERSHIP_ID = UUID("20000000-0000-0000-0000-000000000001")
TARGET_MEMBERSHIP_ID = UUID("20000000-0000-0000-0000-000000000002")
BACKUP_MEMBERSHIP_ID = UUID("20000000-0000-0000-0000-000000000003")
FARM_A_ID = UUID("30000000-0000-0000-0000-000000000001")
FARM_B_ID = UUID("30000000-0000-0000-0000-000000000002")
PLOT_B_ID = UUID("40000000-0000-0000-0000-000000000001")


def _require_ci_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError(
            "La integración administrativa DBI solo puede ejecutarse en GitHub Actions."
        )
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL no está permitida en esta integración DBI.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración administrativa exige ambiente test.")

    config = load_dbi_database_config()
    identity = (
        config.database_name,
        config.url.username,
        config.url.host,
        config.url.port,
    )
    if identity != (DATABASE, API_ROLE, HOST, PORT):
        raise RuntimeError(
            "La URL DBI no apunta al rol API efímero autorizado."
        )


def _admin_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=ADMIN_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _provision_api_role() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                (API_ROLE,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(API_ROLE))
                )

            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DATABASE),
                    sql.Identifier(API_ROLE),
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON SCHEMA dbi FROM {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA dbi FROM {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT ON TABLE "
                    "dbi.dbi_principals, dbi.dbi_memberships, "
                    "dbi.dbi_membership_permissions, dbi.dbi_membership_scopes, "
                    "dbi.dbi_admin_audit_events TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, updated_at) "
                    "ON TABLE dbi.dbi_memberships TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT INSERT, DELETE ON TABLE "
                    "dbi.dbi_membership_permissions, dbi.dbi_membership_scopes "
                    "TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT INSERT ON TABLE dbi.dbi_admin_audit_events TO {}"
                ).format(sql.Identifier(API_ROLE))
            )


def _seed_fixture() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO dbi.dbi_farms
                    (id, organization_ref, code, name, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    (FARM_A_ID, ORG_A, "CI-A", "CI Farm A", NOW, NOW),
                    (FARM_B_ID, ORG_B, "CI-B", "CI Farm B", NOW, NOW),
                ),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_plots
                    (id, farm_id, code, name, area_hectares, boundary,
                     status, created_at, updated_at)
                VALUES (%s, %s, 'CI-PLOT-B', 'CI Plot B', NULL, NULL,
                        'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (PLOT_B_ID, FARM_B_ID, NOW, NOW),
            )
            cursor.executemany(
                """
                INSERT INTO dbi.dbi_principals
                    (id, legacy_identity_ref, status, created_at, updated_at)
                VALUES (%s, %s, 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    (ACTOR_PRINCIPAL_ID, "ci-admin-actor", NOW, NOW),
                    (TARGET_PRINCIPAL_ID, "ci-admin-target", NOW, NOW),
                    (BACKUP_PRINCIPAL_ID, "ci-admin-backup", NOW, NOW),
                ),
            )
            cursor.executemany(
                """
                INSERT INTO dbi.dbi_memberships
                    (id, principal_id, tenant_ref, status, created_at, updated_at)
                VALUES (%s, %s, %s, 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    (ACTOR_MEMBERSHIP_ID, ACTOR_PRINCIPAL_ID, TENANT, NOW, NOW),
                    (TARGET_MEMBERSHIP_ID, TARGET_PRINCIPAL_ID, TENANT, NOW, NOW),
                    (BACKUP_MEMBERSHIP_ID, BACKUP_PRINCIPAL_ID, TENANT, NOW, NOW),
                ),
            )
            cursor.executemany(
                """
                INSERT INTO dbi.dbi_membership_permissions
                    (membership_id, permission)
                VALUES (%s, %s)
                ON CONFLICT (membership_id, permission) DO NOTHING
                """,
                (
                    (ACTOR_MEMBERSHIP_ID, "read"),
                    (ACTOR_MEMBERSHIP_ID, "write"),
                    (ACTOR_MEMBERSHIP_ID, "manage"),
                    (TARGET_MEMBERSHIP_ID, "read"),
                    (TARGET_MEMBERSHIP_ID, "manage"),
                    (BACKUP_MEMBERSHIP_ID, "manage"),
                ),
            )
            scope_rows = (
                (UUID("50000000-0000-0000-0000-000000000001"), ACTOR_MEMBERSHIP_ID, ORG_A),
                (UUID("50000000-0000-0000-0000-000000000002"), ACTOR_MEMBERSHIP_ID, ORG_B),
                (UUID("50000000-0000-0000-0000-000000000003"), ACTOR_MEMBERSHIP_ID, ORG_C),
                (UUID("50000000-0000-0000-0000-000000000004"), TARGET_MEMBERSHIP_ID, ORG_A),
                (UUID("50000000-0000-0000-0000-000000000005"), TARGET_MEMBERSHIP_ID, ORG_B),
                (UUID("50000000-0000-0000-0000-000000000006"), BACKUP_MEMBERSHIP_ID, ORG_A),
                (UUID("50000000-0000-0000-0000-000000000007"), BACKUP_MEMBERSHIP_ID, ORG_B),
            )
            cursor.executemany(
                """
                INSERT INTO dbi.dbi_membership_scopes
                    (id, membership_id, scope_type, organization_ref,
                     farm_id, plot_id)
                VALUES (%s, %s, 'organization', %s, NULL, NULL)
                ON CONFLICT (id) DO NOTHING
                """,
                scope_rows,
            )


def _validate_role_capabilities() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication,
                       rolbypassrls
                FROM pg_roles
                WHERE rolname = %s
                """,
                (API_ROLE,),
            )
            capabilities = cursor.fetchone()
            if capabilities != (False, False, False, False, False):
                raise AssertionError(
                    "El rol API DBI conserva capacidades globales no autorizadas."
                )

            checks = {
                "schema_usage": "has_schema_privilege(%s, 'dbi', 'USAGE')",
                "schema_create": "has_schema_privilege(%s, 'dbi', 'CREATE')",
                "principal_select": "has_table_privilege(%s, 'dbi.dbi_principals', 'SELECT')",
                "principal_insert": "has_table_privilege(%s, 'dbi.dbi_principals', 'INSERT')",
                "principal_update": "has_table_privilege(%s, 'dbi.dbi_principals', 'UPDATE')",
                "principal_delete": "has_table_privilege(%s, 'dbi.dbi_principals', 'DELETE')",
                "membership_select": "has_table_privilege(%s, 'dbi.dbi_memberships', 'SELECT')",
                "membership_insert": "has_table_privilege(%s, 'dbi.dbi_memberships', 'INSERT')",
                "membership_delete": "has_table_privilege(%s, 'dbi.dbi_memberships', 'DELETE')",
                "membership_status_update": "has_column_privilege(%s, 'dbi.dbi_memberships', 'status', 'UPDATE')",
                "membership_updated_at_update": "has_column_privilege(%s, 'dbi.dbi_memberships', 'updated_at', 'UPDATE')",
                "membership_tenant_update": "has_column_privilege(%s, 'dbi.dbi_memberships', 'tenant_ref', 'UPDATE')",
                "permission_select": "has_table_privilege(%s, 'dbi.dbi_membership_permissions', 'SELECT')",
                "permission_insert": "has_table_privilege(%s, 'dbi.dbi_membership_permissions', 'INSERT')",
                "permission_update": "has_table_privilege(%s, 'dbi.dbi_membership_permissions', 'UPDATE')",
                "permission_delete": "has_table_privilege(%s, 'dbi.dbi_membership_permissions', 'DELETE')",
                "scope_select": "has_table_privilege(%s, 'dbi.dbi_membership_scopes', 'SELECT')",
                "scope_insert": "has_table_privilege(%s, 'dbi.dbi_membership_scopes', 'INSERT')",
                "scope_update": "has_table_privilege(%s, 'dbi.dbi_membership_scopes', 'UPDATE')",
                "scope_delete": "has_table_privilege(%s, 'dbi.dbi_membership_scopes', 'DELETE')",
                "audit_select": "has_table_privilege(%s, 'dbi.dbi_admin_audit_events', 'SELECT')",
                "audit_insert": "has_table_privilege(%s, 'dbi.dbi_admin_audit_events', 'INSERT')",
                "audit_update": "has_table_privilege(%s, 'dbi.dbi_admin_audit_events', 'UPDATE')",
                "audit_delete": "has_table_privilege(%s, 'dbi.dbi_admin_audit_events', 'DELETE')",
            }
            results: dict[str, bool] = {}
            for name, expression in checks.items():
                cursor.execute(f"SELECT {expression}", (API_ROLE,))
                results[name] = bool(cursor.fetchone()[0])

    expected_true = {
        "schema_usage",
        "principal_select",
        "membership_select",
        "membership_status_update",
        "membership_updated_at_update",
        "permission_select",
        "permission_insert",
        "permission_delete",
        "scope_select",
        "scope_insert",
        "scope_delete",
        "audit_select",
        "audit_insert",
    }
    if {name for name, enabled in results.items() if enabled} != expected_true:
        raise AssertionError(
            "La matriz de privilegios del rol API DBI no es mínima y exacta."
        )


def _assert_forbidden_sql(statement: str) -> None:
    config = load_dbi_database_config()
    engine = create_dbi_engine(config)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(statement))
            except DBAPIError as error:
                transaction.rollback()
                if getattr(error.orig, "sqlstate", None) != "42501":
                    raise
            else:
                transaction.rollback()
                raise AssertionError(
                    "El rol API ejecutó una sentencia explícitamente prohibida."
                )
    finally:
        engine.dispose()


def _actor_snapshot() -> DBIAdminAuthoritySnapshot:
    return DBIAdminAuthoritySnapshot(
        principal_ref="ci-admin-actor",
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        permissions=frozenset(
            {DBIPermission.READ, DBIPermission.WRITE, DBIPermission.MANAGE}
        ),
        organization_scopes=frozenset({ORG_A, ORG_B, ORG_C}),
    )


def _target_before() -> DBIAdminAuthoritySnapshot:
    return DBIAdminAuthoritySnapshot(
        principal_ref="ci-admin-target",
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE}),
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )


def _target_after() -> DBIAdminAuthoritySnapshot:
    return DBIAdminAuthoritySnapshot(
        principal_ref="ci-admin-target",
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.INACTIVE,
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A}),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref=ORG_A, farm_id=FARM_A_ID)}
        ),
        plot_scopes=frozenset(
            {
                DBIPlotScope(
                    organization_ref=ORG_B,
                    farm_id=FARM_B_ID,
                    plot_id=PLOT_B_ID,
                )
            }
        ),
    )


def _run_real_mutation() -> tuple[tuple[str, str], ...]:
    config = load_dbi_database_config()
    engine = create_dbi_engine(config)
    factory = create_dbi_session_factory(engine)
    try:
        with dbi_session_scope(factory) as session:
            repository = DBIAdminPersistenceRepository(session)
            evidence = DBIAdminService(repository).mutate_membership(
                _actor_snapshot(),
                _target_before(),
                _target_after(),
                actor_membership_id=ACTOR_MEMBERSHIP_ID,
                target_membership_id=TARGET_MEMBERSHIP_ID,
                expected_updated_at=NOW,
                next_updated_at=NEXT,
                correlation_ref="ci-admin-mutation-001",
            )
            if not evidence.plan.applied:
                raise AssertionError("La mutación administrativa debía aplicarse.")
            return tuple(
                (event.organization_ref, event.action.value)
                for event in evidence.plan.audit_events
            )
    finally:
        engine.dispose()


def _run_no_op() -> None:
    config = load_dbi_database_config()
    engine = create_dbi_engine(config)
    factory = create_dbi_session_factory(engine)
    try:
        with dbi_session_scope(factory) as session:
            repository = DBIAdminPersistenceRepository(session)
            evidence = DBIAdminService(repository).mutate_membership(
                _actor_snapshot(),
                _target_after(),
                _target_after(),
                actor_membership_id=ACTOR_MEMBERSHIP_ID,
                target_membership_id=TARGET_MEMBERSHIP_ID,
                expected_updated_at=NEXT,
                next_updated_at=NEXT_AFTER,
                correlation_ref="ci-admin-noop-001",
            )
            if evidence.plan.applied or evidence.plan.audit_events:
                raise AssertionError("La repetición idéntica debía ser no-op.")
    finally:
        engine.dispose()


def _assert_service_conflict(
    *,
    actor: DBIAdminAuthoritySnapshot,
    before: DBIAdminAuthoritySnapshot,
    after: DBIAdminAuthoritySnapshot,
    actor_membership_id: UUID,
    target_membership_id: UUID,
    expected_updated_at: datetime,
    correlation_ref: str,
) -> None:
    config = load_dbi_database_config()
    engine = create_dbi_engine(config)
    factory = create_dbi_session_factory(engine)
    try:
        try:
            with dbi_session_scope(factory) as session:
                repository = DBIAdminPersistenceRepository(session)
                DBIAdminService(repository).mutate_membership(
                    actor,
                    before,
                    after,
                    actor_membership_id=actor_membership_id,
                    target_membership_id=target_membership_id,
                    expected_updated_at=expected_updated_at,
                    next_updated_at=NEXT_AFTER,
                    correlation_ref=correlation_ref,
                )
        except DBIAdminConflict:
            return
        raise AssertionError("La operación administrativa debía producir conflicto.")
    finally:
        engine.dispose()


def _verify_persisted(expected_events: tuple[tuple[str, str], ...]) -> dict[str, int]:
    config = load_dbi_database_config()
    engine = create_dbi_engine(config)
    factory = create_dbi_session_factory(engine)
    try:
        with dbi_session_scope(factory) as session:
            target = session.get(DBIMembership, TARGET_MEMBERSHIP_ID)
            if target is None:
                raise AssertionError("La membresía objetivo no existe.")
            if target.status != DBIAdminMembershipStatus.INACTIVE.value:
                raise AssertionError("El estado de membresía no fue persistido.")
            if target.updated_at.astimezone(timezone.utc) != NEXT:
                raise AssertionError("membership.updated_at no avanzó exactamente.")

            permissions = tuple(
                session.scalars(
                    select(DBIMembershipPermission.permission)
                    .where(
                        DBIMembershipPermission.membership_id
                        == TARGET_MEMBERSHIP_ID
                    )
                    .order_by(DBIMembershipPermission.permission)
                ).all()
            )
            if permissions != (DBIPermission.READ.value,):
                raise AssertionError("Los permisos persistidos son divergentes.")

            scopes = tuple(
                session.scalars(
                    select(DBIMembershipScope)
                    .where(
                        DBIMembershipScope.membership_id
                        == TARGET_MEMBERSHIP_ID
                    )
                    .order_by(
                        DBIMembershipScope.scope_type,
                        DBIMembershipScope.organization_ref,
                        DBIMembershipScope.id,
                    )
                ).all()
            )
            scope_keys = {
                (
                    scope.scope_type,
                    scope.organization_ref,
                    scope.farm_id,
                    scope.plot_id,
                )
                for scope in scopes
            }
            expected_scope_keys = {
                (DBIMembershipScopeType.ORGANIZATION.value, ORG_A, None, None),
                (DBIMembershipScopeType.FARM.value, ORG_A, FARM_A_ID, None),
                (DBIMembershipScopeType.PLOT.value, ORG_B, FARM_B_ID, PLOT_B_ID),
            }
            if scope_keys != expected_scope_keys:
                raise AssertionError("Los ámbitos persistidos no son exactos.")
            if (
                DBIMembershipScopeType.FARM.value,
                ORG_B,
                FARM_B_ID,
                None,
            ) in scope_keys:
                raise AssertionError("Un lote fabricó un ámbito de finca.")

            events = tuple(
                session.scalars(
                    select(DBIAdminAuditEvent)
                    .where(
                        DBIAdminAuditEvent.resource_ref
                        == str(TARGET_MEMBERSHIP_ID)
                    )
                    .order_by(
                        DBIAdminAuditEvent.organization_ref,
                        DBIAdminAuditEvent.action,
                    )
                ).all()
            )
            event_keys = tuple(
                sorted((event.organization_ref, event.action) for event in events)
            )
            if event_keys != tuple(sorted(expected_events)):
                raise AssertionError("La auditoría persistida es divergente.")
            if any(
                event.actor_principal_id != ACTOR_PRINCIPAL_ID
                or event.actor_membership_id != ACTOR_MEMBERSHIP_ID
                or event.tenant_ref != TENANT
                or event.correlation_ref != "ci-admin-mutation-001"
                or event.occurred_at.astimezone(timezone.utc) != NEXT
                for event in events
            ):
                raise AssertionError("La evidencia de auditoría perdió identidad o fecha.")

            actor_scopes = set(
                session.scalars(
                    select(DBIMembershipScope.organization_ref).where(
                        DBIMembershipScope.membership_id == ACTOR_MEMBERSHIP_ID,
                        DBIMembershipScope.scope_type
                        == DBIMembershipScopeType.ORGANIZATION.value,
                    )
                ).all()
            )
            if actor_scopes != {ORG_A, ORG_B, ORG_C}:
                raise AssertionError("La protección del último administrador falló.")

            principal = session.get(DBIPrincipal, TARGET_PRINCIPAL_ID)
            if principal is None or principal.status != "active":
                raise AssertionError("La mutación alteró el principal global.")

            return {
                "audit_events": len(events),
                "permissions": len(permissions),
                "scopes": len(scopes),
            }
    finally:
        engine.dispose()


def main() -> None:
    _require_ci_scope()
    _provision_api_role()
    _validate_role_capabilities()
    _seed_fixture()

    for statement in (
        "CREATE TABLE dbi.ci_forbidden_table (id integer)",
        "DELETE FROM dbi.dbi_principals WHERE false",
        "UPDATE dbi.dbi_principals SET status = status WHERE false",
        "DELETE FROM dbi.dbi_memberships WHERE false",
        "UPDATE dbi.dbi_memberships SET tenant_ref = tenant_ref WHERE false",
        "UPDATE dbi.dbi_membership_permissions SET permission = permission WHERE false",
        "UPDATE dbi.dbi_membership_scopes SET organization_ref = organization_ref WHERE false",
        "DELETE FROM dbi.dbi_admin_audit_events WHERE false",
    ):
        _assert_forbidden_sql(statement)

    expected_events = _run_real_mutation()
    initial = _verify_persisted(expected_events)
    _run_no_op()

    _assert_service_conflict(
        actor=_actor_snapshot(),
        before=_target_after(),
        after=_target_after(),
        actor_membership_id=ACTOR_MEMBERSHIP_ID,
        target_membership_id=TARGET_MEMBERSHIP_ID,
        expected_updated_at=NOW,
        correlation_ref="ci-admin-stale-001",
    )

    actor_after = DBIAdminAuthoritySnapshot(
        principal_ref="ci-admin-actor",
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        permissions=_actor_snapshot().permissions,
        organization_scopes=frozenset({ORG_A, ORG_B}),
    )
    _assert_service_conflict(
        actor=_actor_snapshot(),
        before=_actor_snapshot(),
        after=actor_after,
        actor_membership_id=ACTOR_MEMBERSHIP_ID,
        target_membership_id=ACTOR_MEMBERSHIP_ID,
        expected_updated_at=NOW,
        correlation_ref="ci-admin-last-admin-001",
    )

    final = _verify_persisted(expected_events)
    if final != initial:
        raise AssertionError("No-op o conflicto alteraron el estado confirmado.")

    evidence = {
        "api_role": API_ROLE,
        "audit_events": final["audit_events"],
        "permissions": final["permissions"],
        "scopes": final["scopes"],
        "stale_conflict": True,
        "last_admin_protected": True,
        "no_op_idempotent": True,
    }
    print(json.dumps(evidence, sort_keys=True))
    print("Mutación administrativa DBI real aprobada con rol API mínimo.")


if __name__ == "__main__":
    main()
