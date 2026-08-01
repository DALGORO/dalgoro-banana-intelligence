"""Prueba real de altas administrativas DBI con rol API combinado mínimo."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from psycopg import sql
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from ci_dbi_admin_integration import (  # noqa: E402
    ACTOR_MEMBERSHIP_ID,
    ACTOR_PRINCIPAL_ID,
    API_ROLE,
    FARM_A_ID,
    FARM_B_ID,
    NEXT_AFTER,
    ORG_A,
    ORG_B,
    PLOT_B_ID,
    TENANT,
    _actor_snapshot,
    _admin_connect,
    _assert_forbidden_sql,
    _provision_api_role,
    _require_ci_scope,
    _seed_fixture,
)
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
    DBIAdminDenied,
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
    DBIMembershipStatus,
    DBIPrincipal,
    DBIPrincipalStatus,
)

CREATED_AT = datetime(2026, 8, 1, 16, 0, tzinfo=timezone.utc)
NEW_PRINCIPAL_ID = UUID("60000000-0000-0000-0000-000000000001")
NEW_MEMBERSHIP_ID = UUID("70000000-0000-0000-0000-000000000001")
INACTIVE_PRINCIPAL_ID = UUID("60000000-0000-0000-0000-000000000002")
NEW_PRINCIPAL_REF = "ci-created-principal"
INACTIVE_PRINCIPAL_REF = "ci-inactive-principal"
PRINCIPAL_CORRELATION = "ci-principal-create-001"
MEMBERSHIP_CORRELATION = "ci-membership-create-001"


def _grant_creation_privileges() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "GRANT INSERT ON TABLE "
                    "dbi.dbi_principals, dbi.dbi_memberships TO {}"
                ).format(sql.Identifier(API_ROLE))
            )


def _validate_combined_acl() -> None:
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
        "farm_select": "has_table_privilege(%s, 'dbi.dbi_farms', 'SELECT')",
        "farm_insert": "has_table_privilege(%s, 'dbi.dbi_farms', 'INSERT')",
        "farm_update": "has_table_privilege(%s, 'dbi.dbi_farms', 'UPDATE')",
        "farm_delete": "has_table_privilege(%s, 'dbi.dbi_farms', 'DELETE')",
        "plot_select": "has_table_privilege(%s, 'dbi.dbi_plots', 'SELECT')",
        "plot_insert": "has_table_privilege(%s, 'dbi.dbi_plots', 'INSERT')",
        "plot_update": "has_table_privilege(%s, 'dbi.dbi_plots', 'UPDATE')",
        "plot_delete": "has_table_privilege(%s, 'dbi.dbi_plots', 'DELETE')",
    }
    results: dict[str, bool] = {}
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            for name, expression in checks.items():
                cursor.execute(f"SELECT {expression}", (API_ROLE,))
                results[name] = bool(cursor.fetchone()[0])

    expected_true = {
        "schema_usage",
        "principal_select",
        "principal_insert",
        "membership_select",
        "membership_insert",
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
        "farm_select",
        "plot_select",
    }
    enabled = {name for name, value in results.items() if value}
    if enabled != expected_true:
        raise AssertionError(
            "La ACL combinada del rol API DBI no es mínima y exacta. "
            f"Habilitados={sorted(enabled)!r}; esperados={sorted(expected_true)!r}"
        )


def _seed_inactive_principal() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO dbi.dbi_principals
                    (id, legacy_identity_ref, status, created_at, updated_at)
                VALUES (%s, %s, 'inactive', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    INACTIVE_PRINCIPAL_ID,
                    INACTIVE_PRINCIPAL_REF,
                    CREATED_AT,
                    CREATED_AT,
                ),
            )


def _requested_authority(
    *,
    permissions: frozenset[DBIPermission] | None = None,
) -> DBIAdminAuthoritySnapshot:
    return DBIAdminAuthoritySnapshot(
        principal_ref=NEW_PRINCIPAL_REF,
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        permissions=(
            permissions
            if permissions is not None
            else frozenset({DBIPermission.READ, DBIPermission.WRITE})
        ),
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


def _run_principal_registration(*, principal_id: UUID, principal_ref: str):
    config = load_dbi_database_config()
    engine = create_dbi_engine(config)
    factory = create_dbi_session_factory(engine)
    try:
        with dbi_session_scope(factory) as session:
            return DBIAdminService(
                DBIAdminPersistenceRepository(session)
            ).register_principal(
                _actor_snapshot(),
                actor_membership_id=ACTOR_MEMBERSHIP_ID,
                principal_id=principal_id,
                target_principal_ref=principal_ref,
                tenant_ref=TENANT,
                organization_refs=frozenset({ORG_A, ORG_B}),
                occurred_at=CREATED_AT,
                correlation_ref=PRINCIPAL_CORRELATION,
            )
    finally:
        engine.dispose()


def _run_membership_creation(
    *,
    membership_id: UUID,
    principal_id: UUID,
    requested: DBIAdminAuthoritySnapshot,
):
    config = load_dbi_database_config()
    engine = create_dbi_engine(config)
    factory = create_dbi_session_factory(engine)
    try:
        with dbi_session_scope(factory) as session:
            return DBIAdminService(
                DBIAdminPersistenceRepository(session)
            ).create_membership(
                _actor_snapshot(),
                requested,
                actor_membership_id=ACTOR_MEMBERSHIP_ID,
                membership_id=membership_id,
                principal_id=principal_id,
                occurred_at=CREATED_AT,
                correlation_ref=MEMBERSHIP_CORRELATION,
            )
    finally:
        engine.dispose()


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAdminConflict:
        return
    raise AssertionError("La alta DBI real debía producir conflicto.")


def _assert_denied(factory) -> None:
    try:
        factory()
    except DBIAdminDenied:
        return
    raise AssertionError("La alta DBI real debía ser denegada.")


def _verify_created_state() -> dict[str, int]:
    config = load_dbi_database_config()
    engine = create_dbi_engine(config)
    factory = create_dbi_session_factory(engine)
    try:
        with dbi_session_scope(factory) as session:
            principal = session.get(DBIPrincipal, NEW_PRINCIPAL_ID)
            if (
                principal is None
                or principal.legacy_identity_ref != NEW_PRINCIPAL_REF
                or principal.status != DBIPrincipalStatus.ACTIVE.value
            ):
                raise AssertionError("El principal creado no es exacto y activo.")

            membership = session.get(DBIMembership, NEW_MEMBERSHIP_ID)
            if (
                membership is None
                or membership.principal_id != NEW_PRINCIPAL_ID
                or membership.tenant_ref != TENANT
                or membership.status != DBIMembershipStatus.ACTIVE.value
                or membership.updated_at.astimezone(timezone.utc) != CREATED_AT
            ):
                raise AssertionError("La membresía creada no es exacta y activa.")

            permissions = set(
                session.scalars(
                    select(DBIMembershipPermission.permission).where(
                        DBIMembershipPermission.membership_id
                        == NEW_MEMBERSHIP_ID
                    )
                ).all()
            )
            if permissions != {"read", "write"}:
                raise AssertionError("Los permisos del alta son divergentes.")

            scopes = tuple(
                session.scalars(
                    select(DBIMembershipScope).where(
                        DBIMembershipScope.membership_id == NEW_MEMBERSHIP_ID
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
            expected_scopes = {
                (DBIMembershipScopeType.ORGANIZATION.value, ORG_A, None, None),
                (DBIMembershipScopeType.FARM.value, ORG_A, FARM_A_ID, None),
                (DBIMembershipScopeType.PLOT.value, ORG_B, FARM_B_ID, PLOT_B_ID),
            }
            if scope_keys != expected_scopes:
                raise AssertionError("Los ámbitos del alta son divergentes.")

            audit_events = tuple(
                session.scalars(
                    select(DBIAdminAuditEvent).where(
                        DBIAdminAuditEvent.resource_ref.in_(
                            (str(NEW_PRINCIPAL_ID), str(NEW_MEMBERSHIP_ID))
                        )
                    )
                ).all()
            )
            principal_events = [
                event
                for event in audit_events
                if event.resource_ref == str(NEW_PRINCIPAL_ID)
            ]
            membership_events = [
                event
                for event in audit_events
                if event.resource_ref == str(NEW_MEMBERSHIP_ID)
            ]
            if len(principal_events) != 2 or len(membership_events) != 2:
                raise AssertionError("Las altas no produjeron auditoría exacta.")
            if any(
                event.actor_principal_id != ACTOR_PRINCIPAL_ID
                or event.actor_membership_id != ACTOR_MEMBERSHIP_ID
                or event.tenant_ref != TENANT
                or event.occurred_at.astimezone(timezone.utc) != CREATED_AT
                for event in audit_events
            ):
                raise AssertionError("La auditoría de altas perdió actor o fecha.")

            inactive = session.get(DBIPrincipal, INACTIVE_PRINCIPAL_ID)
            if inactive is None or inactive.status != DBIPrincipalStatus.INACTIVE.value:
                raise AssertionError("Un conflicto reactivó el principal inactivo.")

            return {
                "audit_events": len(audit_events),
                "permissions": len(permissions),
                "scopes": len(scopes),
            }
    finally:
        engine.dispose()


def main() -> None:
    _require_ci_scope()
    _provision_api_role()
    _seed_fixture()
    _grant_creation_privileges()
    _validate_combined_acl()
    _seed_inactive_principal()

    for statement in (
        "CREATE TABLE dbi.ci_creation_forbidden (id integer)",
        "UPDATE dbi.dbi_principals SET status = status WHERE false",
        "DELETE FROM dbi.dbi_principals WHERE false",
        "DELETE FROM dbi.dbi_memberships WHERE false",
        "UPDATE dbi.dbi_memberships SET tenant_ref = tenant_ref WHERE false",
    ):
        _assert_forbidden_sql(statement)

    principal = _run_principal_registration(
        principal_id=NEW_PRINCIPAL_ID,
        principal_ref=NEW_PRINCIPAL_REF,
    )
    if principal.created is not True:
        raise AssertionError("La primera alta de principal debía crearlo.")
    repeated_principal = _run_principal_registration(
        principal_id=NEW_PRINCIPAL_ID,
        principal_ref=NEW_PRINCIPAL_REF,
    )
    if repeated_principal.created is not False:
        raise AssertionError("El principal repetido debía ser no-op.")

    _assert_conflict(
        lambda: _run_principal_registration(
            principal_id=UUID("60000000-0000-0000-0000-000000000099"),
            principal_ref=NEW_PRINCIPAL_REF,
        )
    )
    _assert_conflict(
        lambda: _run_principal_registration(
            principal_id=INACTIVE_PRINCIPAL_ID,
            principal_ref=INACTIVE_PRINCIPAL_REF,
        )
    )

    requested = _requested_authority()
    membership = _run_membership_creation(
        membership_id=NEW_MEMBERSHIP_ID,
        principal_id=NEW_PRINCIPAL_ID,
        requested=requested,
    )
    if membership.created is not True:
        raise AssertionError("La primera membresía debía crearse.")
    repeated_membership = _run_membership_creation(
        membership_id=NEW_MEMBERSHIP_ID,
        principal_id=NEW_PRINCIPAL_ID,
        requested=requested,
    )
    if repeated_membership.created is not False:
        raise AssertionError("La membresía repetida debía ser no-op.")

    _assert_conflict(
        lambda: _run_membership_creation(
            membership_id=UUID("70000000-0000-0000-0000-000000000099"),
            principal_id=NEW_PRINCIPAL_ID,
            requested=requested,
        )
    )
    _assert_conflict(
        lambda: _run_membership_creation(
            membership_id=NEW_MEMBERSHIP_ID,
            principal_id=NEW_PRINCIPAL_ID,
            requested=_requested_authority(
                permissions=frozenset({DBIPermission.READ})
            ),
        )
    )
    inactive_requested = DBIAdminAuthoritySnapshot(
        principal_ref=INACTIVE_PRINCIPAL_REF,
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A}),
    )
    _assert_conflict(
        lambda: _run_membership_creation(
            membership_id=UUID("70000000-0000-0000-0000-000000000098"),
            principal_id=INACTIVE_PRINCIPAL_ID,
            requested=inactive_requested,
        )
    )

    self_requested = DBIAdminAuthoritySnapshot(
        principal_ref="ci-admin-actor",
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        permissions=frozenset({DBIPermission.READ}),
        organization_scopes=frozenset({ORG_A}),
    )
    _assert_denied(
        lambda: _run_membership_creation(
            membership_id=UUID("70000000-0000-0000-0000-000000000097"),
            principal_id=ACTOR_PRINCIPAL_ID,
            requested=self_requested,
        )
    )

    evidence = _verify_created_state()
    output = {
        "api_role": API_ROLE,
        "principal_created": True,
        "principal_no_op": True,
        "membership_created": True,
        "membership_no_op": True,
        "conflicts_rejected": True,
        **evidence,
    }
    print(json.dumps(output, sort_keys=True))
    print("Altas administrativas DBI reales aprobadas con ACL combinada mínima.")


if __name__ == "__main__":
    main()
