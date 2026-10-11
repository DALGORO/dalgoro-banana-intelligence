"""Pruebas offline de doble aprobación INSPECT, sin DB ni red."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIAccessDenied, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.inspection.dual_approval import (  # noqa: E402
    DBIInspectionApprovalConflict, DBIInspectionApprovalState,
)

FARM = UUID("10000000-0000-4000-8000-000000000151")
PLOT = UUID("20000000-0000-4000-8000-000000000151")
CAMPAIGN = UUID("30000000-0000-4000-8000-000000000151")
SECOND_CAMPAIGN = UUID("30000000-0000-4000-8000-000000000152")
OBS = UUID("40000000-0000-4000-8000-000000000151")
VERSION_1 = UUID("50000000-0000-4000-8000-000000000151")
VERSION_2 = UUID("50000000-0000-4000-8000-000000000152")
NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def context(
    principal: str,
    permissions: set[DBIPermission],
    *,
    tenant: str = "tenant-inspect",
    plot: UUID = PLOT,
) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref=principal,
        tenant_ref=tenant,
        organization_refs=frozenset({"org-inspect"}),
        farm_scopes=frozenset({DBIFarmScope("org-inspect", FARM)}),
        plot_scopes=frozenset({DBIPlotScope("org-inspect", FARM, plot)}),
        permissions=frozenset(permissions),
    )


def pending(version_id: UUID = VERSION_1) -> DBIInspectionApprovalState:
    return DBIInspectionApprovalState(
        tenant_ref="tenant-inspect",
        organization_ref="org-inspect",
        farm_id=FARM,
        plot_id=PLOT,
        campaign_id=CAMPAIGN,
        observation_id=OBS,
        observation_version_id=version_id,
    )


def denied(fn: object, *errors: type[Exception]) -> None:
    try:
        fn()
    except errors:
        pass
    else:
        raise AssertionError("Se esperaba denegación fail-closed.")


def validate_contract() -> None:
    technical = context("tech-A", {DBIPermission.READ, DBIPermission.WRITE})
    admin = context("admin-B", {DBIPermission.READ, DBIPermission.MANAGE, DBIPermission.APPROVE_AGRONOMIC})
    external = context("client-C", {DBIPermission.READ})

    original = pending()
    assert original.stage == "pending"
    assert not original.eligible_for_client_read(
        current_version_id=VERSION_1, campaign_id=CAMPAIGN, campaign_link_verified=True
    )

    denied(
        lambda: original.validate_technical(external, at=NOW, current_version_id=VERSION_1),
        DBIAccessDenied,
    )
    denied(
        lambda: original.validate_technical(
            context("other-tenant", {DBIPermission.WRITE}, tenant="other"),
            at=NOW, current_version_id=VERSION_1,
        ),
        DBIAccessDenied,
    )
    denied(
        lambda: original.validate_technical(
            context("other-plot", {DBIPermission.WRITE}, plot=VERSION_1),
            at=NOW, current_version_id=VERSION_1,
        ),
        DBIAccessDenied,
    )
    denied(
        lambda: original.approve_administrative(
            admin, at=NOW, current_version_id=VERSION_1, campaign_link_verified=True
        ),
        DBIInspectionApprovalConflict,
    )

    reviewed = original.validate_technical(technical, at=NOW, current_version_id=VERSION_1)
    assert original.stage == "pending"  # inmutable
    assert reviewed.stage == "technical_validated"
    assert reviewed.technical_by == "tech-A"
    assert not reviewed.eligible_for_client_read(
        current_version_id=VERSION_1, campaign_id=CAMPAIGN, campaign_link_verified=True
    )

    denied(
        lambda: reviewed.validate_technical(technical, at=NOW, current_version_id=VERSION_1),
        DBIInspectionApprovalConflict,
    )
    denied(
        lambda: reviewed.approve_administrative(
            context("tech-A", {DBIPermission.MANAGE, DBIPermission.APPROVE_AGRONOMIC}),
            at=NOW + timedelta(minutes=1),
            current_version_id=VERSION_1,
            campaign_link_verified=True,
        ),
        DBIInspectionApprovalConflict,
    )
    for perms in (
        {DBIPermission.WRITE},
        {DBIPermission.APPROVE_AGRONOMIC},
        {DBIPermission.MANAGE},
        {DBIPermission.READ},
    ):
        denied(
            lambda perms=perms: reviewed.approve_administrative(
                context("admin-B", perms), at=NOW + timedelta(minutes=1),
                current_version_id=VERSION_1, campaign_link_verified=True,
            ),
            DBIAccessDenied,
        )
    denied(
        lambda: reviewed.approve_administrative(
            admin, at=NOW + timedelta(minutes=1),
            current_version_id=VERSION_1, campaign_link_verified=False,
        ),
        DBIInspectionApprovalConflict,
    )
    denied(
        lambda: reviewed.approve_administrative(
            admin, at=NOW - timedelta(minutes=1),
            current_version_id=VERSION_1, campaign_link_verified=True,
        ),
        DBIInspectionApprovalConflict,
    )
    denied(
        lambda: reviewed.approve_administrative(
            admin, at=NOW + timedelta(minutes=1),
            current_version_id=VERSION_2, campaign_link_verified=True,
        ),
        DBIInspectionApprovalConflict,
    )

    approved = reviewed.approve_administrative(
        admin, at=NOW + timedelta(minutes=1),
        current_version_id=VERSION_1, campaign_link_verified=True,
    )
    assert reviewed.stage == "technical_validated"
    assert approved.stage == "dual_approved"
    assert approved.technical_by != approved.administrative_by
    assert approved.eligible_for_client_read(
        current_version_id=VERSION_1, campaign_id=CAMPAIGN, campaign_link_verified=True
    )
    assert not approved.eligible_for_client_read(
        current_version_id=VERSION_1, campaign_id=SECOND_CAMPAIGN, campaign_link_verified=True
    )
    assert not approved.eligible_for_client_read(
        current_version_id=VERSION_1, campaign_id=CAMPAIGN, campaign_link_verified=False
    )
    assert not approved.eligible_for_client_read(
        current_version_id=VERSION_2, campaign_id=CAMPAIGN, campaign_link_verified=True
    )
    corrected = pending(VERSION_2)
    assert corrected.stage == "pending"
    assert not corrected.eligible_for_client_read(
        current_version_id=VERSION_2, campaign_id=CAMPAIGN, campaign_link_verified=True
    )
    denied(
        lambda: replace(reviewed, administrative_by="tech-A",
                        administrative_at=NOW + timedelta(minutes=1)),
        DBIInspectionApprovalConflict,
    )
    denied(
        lambda: replace(original, administrative_by="admin-B",
                        administrative_at=NOW + timedelta(minutes=1)),
        DBIInspectionApprovalConflict,
    )
    denied(
        lambda: original.validate_technical(
            technical, at=NOW.replace(tzinfo=None), current_version_id=VERSION_1
        ),
        DBIInspectionApprovalConflict,
    )


if __name__ == "__main__":
    validate_contract()
    print("OK: política dual INSPECT fail-closed, dos actores y versión exacta.")
