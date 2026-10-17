"""Offline CI: real ReportLab PDF bytes and institutional publication guard.

No PostGIS fixture or real principals/credentials are used in this test.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from app.api.v1.dbi_published_reports import _create_pdf, INDICES
from app.dbi.authorization import DBIAccessDenied
from app.dbi.campaigns.institutional_publication import (
    require_institutional_campaign_publisher,
)
from app.dbi.inspection.staff_workflow import (
    DBIInspectionStaffAssignment, DBIInspectionStaffRole,
)

ACTOR = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")
FARM = UUID("33333333-3333-4333-8333-333333333333")
PLOT = UUID("44444444-4444-4444-8444-444444444444")
NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


def test_real_pdf() -> None:
    assert tuple(k for k, _ in INDICES) == (
        "ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"
    )
    campaign = SimpleNamespace(
        id=FARM, analysis_type="density", captured_at=NOW,
        approved_at=NOW, published_at=NOW,
    )
    data = _create_pdf(
        campaign=campaign,
        layer_counts=[("plants", 1, 456), ("density_hexagons", 2, 10)],
        index_values={"ndvi": (0.35, 20, 30), "evi2": (None, 0, 20)},
        evidence_scope="Última muestra verificada, no un diagnóstico.",
    )
    assert data.startswith(b"%PDF-") and len(data) > 1800


class StubDirectory:
    def __init__(self, _session) -> None:
        self.active_admin = ACTOR
        self.snapshot_acquired = False

    def acquire_approval_snapshot(self) -> None:
        self.snapshot_acquired = True

    def list_active_administrators(self):
        return [self.active_admin]

    def list_assignments(self, *, principal_id, tenant_ref, organization_ref):
        return [
            DBIInspectionStaffAssignment(
                principal_id=principal_id, tenant_ref=tenant_ref,
                organization_ref=organization_ref,
                role=DBIInspectionStaffRole.ADMINISTRATOR, status="active",
            )
        ]


class StubResolver:
    def __init__(self, _repo) -> None:
        pass

    def resolve(self, *, context):
        return SimpleNamespace(principal_id=UUID(context.principal_ref))


def test_institutional_guard() -> None:
    context = SimpleNamespace(
        tenant_ref="ci-t", organization_ref="ci-o", principal_ref=str(ACTOR),
    )
    with (
        patch(
            "app.dbi.campaigns.institutional_publication."
            "DBIAuthorizationPolicy.require_plot", return_value=None,
        ) as scope,
        patch(
            "app.dbi.campaigns.institutional_publication."
            "DBIInspectionInstitutionalStaffDirectory", StubDirectory,
        ),
        patch(
            "app.dbi.campaigns.institutional_publication."
            "DBIAdminActorRepository", lambda session: session,
        ),
        patch(
            "app.dbi.campaigns.institutional_publication."
            "DBIAdminActorResolver", StubResolver,
        ),
    ):
        require_institutional_campaign_publisher(
            object(), context,
            organization_ref="ci-o", farm_id=FARM, plot_id=PLOT,
        )
        assert scope.called
        # Un admin de una compañía no se acredita con solo un permiso MANAGE.
        original = StubDirectory.list_active_administrators
        StubDirectory.list_active_administrators = lambda self: [OTHER]
        try:
            try:
                require_institutional_campaign_publisher(
                    object(), context,
                    organization_ref="ci-o", farm_id=FARM, plot_id=PLOT,
                )
                raise AssertionError("Se aceptó un administrador de otra identidad")
            except DBIAccessDenied:
                pass
        finally:
            StubDirectory.list_active_administrators = original


if __name__ == "__main__":
    test_real_pdf()
    test_institutional_guard()
    print("CI H13 published PDF + institutional publication guard: OK")
