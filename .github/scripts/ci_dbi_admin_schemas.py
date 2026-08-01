"""Valida contratos administrativos DBI estrictos sin conexiones."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.admin_policy import (  # noqa: E402
    DBIAdminAuthoritySnapshot,
    DBIAdminMembershipStatus,
)
from app.dbi.admin_schemas import (  # noqa: E402
    DBIAdminFarmScopeInput,
    DBIAdminMembershipCreationRequest,
    DBIAdminMembershipMutationRequest,
    DBIAdminPlotScopeInput,
    DBIAdminPrincipalRegistrationRequest,
)
from app.dbi.authorization import DBIFarmScope, DBIPermission, DBIPlotScope  # noqa: E402

TENANT = "tenant-a"
ORG_A = "organization-a"
ORG_B = "organization-b"


def _assert_validation_error(factory) -> None:
    try:
        factory()
    except ValidationError:
        return
    raise AssertionError("El contrato administrativo inválido debía rechazarse.")


def validate_principal_registration_contract() -> None:
    principal_id = uuid4()
    payload = DBIAdminPrincipalRegistrationRequest(
        principal_id=principal_id,
        legacy_identity_ref=" legacy-user-a ",
        organization_refs=(ORG_A, ORG_B),
        correlation_ref=" correlation-a ",
    )
    assert payload.principal_id == principal_id
    assert payload.legacy_identity_ref == "legacy-user-a"
    assert payload.correlation_ref == "correlation-a"
    assert payload.organization_set == frozenset({ORG_A, ORG_B})

    _assert_validation_error(
        lambda: DBIAdminPrincipalRegistrationRequest(
            principal_id=principal_id,
            legacy_identity_ref="legacy-user-a",
            organization_refs=(ORG_A, ORG_A),
            correlation_ref="correlation-a",
        )
    )
    _assert_validation_error(
        lambda: DBIAdminPrincipalRegistrationRequest(
            principal_id=principal_id,
            legacy_identity_ref="all",
            organization_refs=(ORG_A,),
            correlation_ref="correlation-a",
        )
    )
    _assert_validation_error(
        lambda: DBIAdminPrincipalRegistrationRequest.model_validate(
            {
                "principal_id": str(principal_id),
                "legacy_identity_ref": "legacy-user-a",
                "organization_refs": [ORG_A],
                "correlation_ref": "correlation-a",
                "principal_active": True,
            }
        )
    )


def validate_membership_creation_contract() -> None:
    membership_id = uuid4()
    principal_id = uuid4()
    farm_id = uuid4()
    plot_id = uuid4()
    payload = DBIAdminMembershipCreationRequest(
        membership_id=membership_id,
        principal_id=principal_id,
        principal_ref="legacy-user-b",
        permissions=(DBIPermission.READ, DBIPermission.MANAGE),
        organization_scopes=(ORG_A,),
        farm_scopes=(
            DBIAdminFarmScopeInput(
                organization_ref=ORG_A,
                farm_id=farm_id,
            ),
        ),
        plot_scopes=(
            DBIAdminPlotScopeInput(
                organization_ref=ORG_A,
                farm_id=farm_id,
                plot_id=plot_id,
            ),
        ),
        correlation_ref="membership-create-a",
    )
    snapshot = payload.to_authority_snapshot(tenant_ref=TENANT)
    assert snapshot.principal_ref == "legacy-user-b"
    assert snapshot.tenant_ref == TENANT
    assert snapshot.principal_active is True
    assert snapshot.membership_status is DBIAdminMembershipStatus.ACTIVE
    assert snapshot.permissions == frozenset(
        {DBIPermission.READ, DBIPermission.MANAGE}
    )
    assert snapshot.organization_scopes == frozenset({ORG_A})
    assert snapshot.farm_scopes == frozenset(
        {DBIFarmScope(organization_ref=ORG_A, farm_id=farm_id)}
    )
    assert snapshot.plot_scopes == frozenset(
        {
            DBIPlotScope(
                organization_ref=ORG_A,
                farm_id=farm_id,
                plot_id=plot_id,
            )
        }
    )

    _assert_validation_error(
        lambda: DBIAdminMembershipCreationRequest(
            membership_id=membership_id,
            principal_id=principal_id,
            principal_ref="legacy-user-b",
            permissions=(DBIPermission.READ, DBIPermission.READ),
            organization_scopes=(ORG_A,),
            correlation_ref="membership-create-a",
        )
    )
    duplicate_scope = DBIAdminFarmScopeInput(
        organization_ref=ORG_A,
        farm_id=farm_id,
    )
    _assert_validation_error(
        lambda: DBIAdminMembershipCreationRequest(
            membership_id=membership_id,
            principal_id=principal_id,
            principal_ref="legacy-user-b",
            permissions=(DBIPermission.READ,),
            farm_scopes=(duplicate_scope, duplicate_scope),
            correlation_ref="membership-create-a",
        )
    )
    _assert_validation_error(
        lambda: DBIAdminMembershipCreationRequest.model_validate(
            {
                "membership_id": str(membership_id),
                "principal_id": str(principal_id),
                "principal_ref": "legacy-user-b",
                "permissions": ["read"],
                "organization_scopes": [ORG_A],
                "correlation_ref": "membership-create-a",
                "membership_status": "active",
            }
        )
    )


def validate_membership_mutation_contract() -> None:
    farm_id = uuid4()
    source_timezone = timezone(timedelta(hours=-5))
    expected_local = datetime(2026, 8, 1, 13, 0, tzinfo=source_timezone)
    before = DBIAdminAuthoritySnapshot(
        principal_ref="legacy-user-c",
        tenant_ref=TENANT,
        principal_active=True,
        membership_status=DBIAdminMembershipStatus.ACTIVE,
        permissions=frozenset({DBIPermission.READ, DBIPermission.MANAGE}),
        organization_scopes=frozenset({ORG_A}),
    )
    payload = DBIAdminMembershipMutationRequest(
        expected_updated_at=expected_local,
        status=DBIAdminMembershipStatus.INACTIVE,
        permissions=(DBIPermission.READ,),
        organization_scopes=(ORG_A,),
        farm_scopes=(
            DBIAdminFarmScopeInput(
                organization_ref=ORG_A,
                farm_id=farm_id,
            ),
        ),
        correlation_ref="membership-update-a",
    )
    after = payload.to_authority_snapshot(before=before)
    assert payload.expected_updated_at == datetime(
        2026, 8, 1, 18, 0, tzinfo=timezone.utc
    )
    assert after.principal_ref == before.principal_ref
    assert after.tenant_ref == before.tenant_ref
    assert after.principal_active is before.principal_active
    assert after.membership_status is DBIAdminMembershipStatus.INACTIVE
    assert after.permissions == frozenset({DBIPermission.READ})

    _assert_validation_error(
        lambda: DBIAdminMembershipMutationRequest(
            expected_updated_at=datetime(2026, 8, 1, 18, 0),
            status=DBIAdminMembershipStatus.ACTIVE,
            permissions=(DBIPermission.READ,),
            organization_scopes=(ORG_A,),
            correlation_ref="membership-update-a",
        )
    )
    _assert_validation_error(
        lambda: DBIAdminMembershipMutationRequest(
            expected_updated_at=expected_local,
            status=DBIAdminMembershipStatus.ACTIVE,
            permissions=(DBIPermission.READ,),
            correlation_ref="membership-update-a",
        )
    )


def main() -> None:
    validate_principal_registration_contract()
    validate_membership_creation_contract()
    validate_membership_mutation_contract()
    print("Contratos administrativos DBI: validación estricta aprobada.")


if __name__ == "__main__":
    main()
