"""Ejecutor cerrado de altas administrativas DBI reales."""

from __future__ import annotations

import ci_dbi_admin_creation_integration as creation_integration
from ci_dbi_admin_integration import (
    ACTOR_MEMBERSHIP_ID,
    ACTOR_PRINCIPAL_ID,
    FARM_A_ID,
    FARM_B_ID,
    ORG_A,
    ORG_B,
    PLOT_B_ID,
    TARGET_MEMBERSHIP_ID,
    TENANT,
    _admin_connect,
)


def _require_mutation_fixture() -> None:
    """Comprueba el fixture previo sin resembrar autoridad ya mutada."""

    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    EXISTS (
                        SELECT 1
                        FROM dbi.dbi_principals
                        WHERE id = %s
                          AND legacy_identity_ref = 'ci-admin-actor'
                          AND status = 'active'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM dbi.dbi_memberships
                        WHERE id = %s
                          AND principal_id = %s
                          AND tenant_ref = %s
                          AND status = 'active'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM dbi.dbi_farms
                        WHERE id = %s
                          AND organization_ref = %s
                    ),
                    EXISTS (
                        SELECT 1
                        FROM dbi.dbi_farms
                        WHERE id = %s
                          AND organization_ref = %s
                    ),
                    EXISTS (
                        SELECT 1
                        FROM dbi.dbi_plots
                        WHERE id = %s
                          AND farm_id = %s
                    ),
                    EXISTS (
                        SELECT 1
                        FROM dbi.dbi_admin_audit_events
                        WHERE resource_ref = %s
                          AND correlation_ref = 'ci-admin-mutation-001'
                    )
                """,
                (
                    ACTOR_PRINCIPAL_ID,
                    ACTOR_MEMBERSHIP_ID,
                    ACTOR_PRINCIPAL_ID,
                    TENANT,
                    FARM_A_ID,
                    ORG_A,
                    FARM_B_ID,
                    ORG_B,
                    PLOT_B_ID,
                    FARM_B_ID,
                    str(TARGET_MEMBERSHIP_ID),
                ),
            )
            evidence = cursor.fetchone()

    if evidence != (True, True, True, True, True, True):
        raise AssertionError(
            "El fixture previo de mutación DBI no está completo y confirmado."
        )


def main() -> None:
    """Ejecuta las altas sobre el fixture confirmado sin reinsertarlo."""

    creation_integration._seed_fixture = _require_mutation_fixture
    creation_integration.main()


if __name__ == "__main__":
    main()
