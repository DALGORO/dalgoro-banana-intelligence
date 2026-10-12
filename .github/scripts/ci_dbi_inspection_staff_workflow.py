"""Barrera offline: personal DALGORO explícito y DBI membership activa.

Sin credenciales, DB o endpoints; se testean denegación, rol, scope, autoridad
persistida y delegación exacta sin cambiar los servicios anteriores.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.dbi.admin_policy import DBIAdminConflict  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIAccessDenied, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.inspection.staff_workflow import (  # noqa: E402
    DBIInspectionStaffAssignment, DBIInspectionStaffRole, DBIInspectionStaffWorkflow,
)

TECH_ID = UUID("71000000-0000-4000-8000-000000000226")
ADMIN_ID = UUID("72000000-0000-4000-8000-000000000226")
FARM = UUID("10000000-0000-4000-8000-000000000226")
PLOT = UUID("20000000-0000-4000-8000-000000000226")
CAMPAIGN = UUID("30000000-0000-4000-8000-000000000226")
OBS = UUID("40000000-0000-4000-8000-000000000226")
VERSION = UUID("50000000-0000-4000-8000-000000000226")
LINK = UUID("60000000-0000-4000-8000-000000000226")
TENANT = "tenant-staff-ci"
ORG = "organization-staff-ci"


def context(who, permissions, *, tenant=TENANT, plot=PLOT):
    return DBIAccessContext(
        principal_ref=str(who), tenant_ref=tenant,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset({DBIFarmScope(ORG, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORG, FARM, plot)}),
        permissions=frozenset(permissions),
    )


TECH = context(TECH_ID, {DBIPermission.READ, DBIPermission.WRITE})
ADMIN = context(ADMIN_ID, {
    DBIPermission.READ, DBIPermission.WRITE,
    DBIPermission.MANAGE, DBIPermission.APPROVE_AGRONOMIC,
})


def appointment(who, role, **overrides):
    return replace(DBIInspectionStaffAssignment(
        principal_id=who, tenant_ref=TENANT,
        organization_ref=ORG, role=role, status="active",
    ), **overrides)


class Directory:
    def __init__(self, *rows):
        self.rows = rows
        self.calls = []

    def list_assignments(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


def parameters():
    return dict(organization_ref=ORG, farm_id=FARM, plot_id=PLOT, link_id=LINK)


def propose(workflow, actor=TECH, *, tenant=TENANT):
    return workflow.propose_link(
        actor, tenant_ref=tenant, organization_ref=ORG,
        farm_id=FARM, plot_id=PLOT, campaign_id=CAMPAIGN,
        observation_id=OBS, observation_version_id=VERSION,
    )


def denied(callback, error=DBIAccessDenied):
    try:
        callback()
    except error:
        return
    raise AssertionError("La operación debería haberse denegado.")


def verify() -> None:
    session = MagicMock(spec=Session)
    tech_directory = Directory(appointment(TECH_ID, DBIInspectionStaffRole.TECHNICIAN))
    admin_directory = Directory(appointment(ADMIN_ID, DBIInspectionStaffRole.ADMINISTRATOR))
    with (
        patch("app.dbi.inspection.staff_workflow.DBIAdminActorResolver") as resolver,
        patch("app.dbi.inspection.staff_workflow.DBIInspectionCampaignLinkService") as link,
        patch("app.dbi.inspection.staff_workflow.DBIInspectionCampaignApprovalService") as approval,
    ):
        resolver.return_value.resolve.side_effect = (
            lambda *, context: SimpleNamespace(principal_id=UUID(context.principal_ref))
        )
        link.return_value.propose_link.return_value = ("link-created", True)
        approval.return_value.validate_technical.return_value = "tech-signed"
        approval.return_value.authorize_administrative.return_value = "admin-signed"

        # Sin directorio INSTITUCIONAL explícito nadie accede, aunque sea ADMIN DBI.
        denied(lambda: propose(DBIInspectionStaffWorkflow(session)))
        denied(lambda: DBIInspectionStaffWorkflow(session).authorize_administrative(
            ADMIN, **parameters(),
        ))
        link.assert_not_called()
        approval.assert_not_called()
        resolver.assert_not_called()

        # Cliente con WRITE DBI no es técnico si no tiene cargo acreditado.
        no_staff = DBIInspectionStaffWorkflow(session, staff_directory=Directory())
        denied(lambda: propose(no_staff))
        link.assert_not_called()

        tech = DBIInspectionStaffWorkflow(session, staff_directory=tech_directory)
        admin = DBIInspectionStaffWorkflow(session, staff_directory=admin_directory)

        # Abuso de tenant y lote no provoca ninguna consulta al directorio.
        before = len(tech_directory.calls)
        denied(lambda: propose(tech, tenant="tenant-cross"))
        denied(lambda: propose(tech, context(
            TECH_ID, {DBIPermission.READ, DBIPermission.WRITE},
            plot=UUID("20000000-0000-4000-8000-000000000227"),
        )))
        denied(lambda: propose(tech, context(TECH_ID, {DBIPermission.READ})))
        denied(lambda: propose(tech, object()))
        assert len(tech_directory.calls) == before

        # Un cargo técnico solo permite firma técnica, no administrativa.
        assert propose(tech) == ("link-created", True)
        assert tech.validate_technical(TECH, **parameters()) == "tech-signed"
        denied(lambda: tech.authorize_administrative(
            context(TECH_ID, ADMIN.permissions), **parameters(),
        ))
        assert approval.return_value.authorize_administrative.call_count == 0
        # Cargo administrativo permite autorización, pero no firma técnica.
        assert admin.authorize_administrative(ADMIN, **parameters()) == "admin-signed"
        denied(lambda: admin.validate_technical(ADMIN, **parameters()))
        assert approval.return_value.validate_technical.call_count == 1
        assert admin_directory.calls[-1] == {
            "principal_id": ADMIN_ID, "tenant_ref": TENANT,
            "organization_ref": ORG,
        }
        assert link.return_value.propose_link.call_args.kwargs[
            "observation_version_id"
        ] == VERSION
        assert approval.return_value.authorize_administrative.call_args.args == (ADMIN,)

        # No basta cargo admin para firmar sin AMBOS privilegios.
        for permissions in (
            {DBIPermission.MANAGE},
            {DBIPermission.APPROVE_AGRONOMIC},
        ):
            denied(lambda p=permissions: admin.authorize_administrative(
                context(ADMIN_ID, p), **parameters(),
            ))
        assert approval.return_value.authorize_administrative.call_count == 1

        # Activo/rol/identidad/scope ambiguo/revocado: fail closed.
        variants = (
            (),
            (appointment(TECH_ID, DBIInspectionStaffRole.TECHNICIAN, status="revoked"),),
            (appointment(TECH_ID, DBIInspectionStaffRole.ADMINISTRATOR),),
            (appointment(ADMIN_ID, DBIInspectionStaffRole.TECHNICIAN),),
            (appointment(TECH_ID, DBIInspectionStaffRole.TECHNICIAN, tenant_ref="other"),),
            (appointment(TECH_ID, DBIInspectionStaffRole.TECHNICIAN,
                         organization_ref="other"),),
            (appointment(TECH_ID, DBIInspectionStaffRole.TECHNICIAN),) * 2,
            ("some-client-json",),
        )
        for rows in variants:
            candidate = DBIInspectionStaffWorkflow(
                session, staff_directory=Directory(*rows),
            )
            denied(lambda w=candidate: propose(w))
        assert link.return_value.propose_link.call_count == 1

        # Un JWT/permisos coherentes NO suplantan un principal que DBI ya revocó.
        resolver.return_value.resolve.side_effect = DBIAdminConflict()
        denied(lambda: propose(tech))
        denied(lambda: admin.authorize_administrative(ADMIN, **parameters()))
        assert link.return_value.propose_link.call_count == 1
        assert approval.return_value.authorize_administrative.call_count == 1

        # Una divergencia entre identidad declarada y DBI persistido bloquea.
        resolver.return_value.resolve.side_effect = None
        resolver.return_value.resolve.return_value = SimpleNamespace(
            principal_id=ADMIN_ID,
        )
        denied(lambda: propose(tech))
        assert link.return_value.propose_link.call_count == 1

    # Contrato estático: no habrá rutas ni migraciones en este microhito.
    source = (
        ROOT / "apps/platform-web/backend/app/dbi/inspection/staff_workflow.py"
    ).read_text(encoding="utf-8")
    assert "DBIAdminActorResolver(" in source
    assert "DBIAdminActorRepository(self._session)" in source
    assert "self._staff_directory is None" in source
    assert "get_current_user" not in source
    assert "APIRouter" not in source
    assert "commit(" not in source
    print("OK: personal institucional explícito + membresía DBI activa; fail closed.")


if __name__ == "__main__":
    verify()
