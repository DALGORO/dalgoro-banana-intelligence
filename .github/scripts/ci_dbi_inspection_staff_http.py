"""HTTP INSPECT institucional: opt-in, límites de payload y transacción única.

Prueba FastAPI sin DB/credenciales reales. Los permisos y locks reales están
cubiertos por ci_dbi_inspection_staff_workflow.py y el PostGIS efímero.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_inspect_staff_http.db")
os.environ.setdefault("JWT_SECRET", "ci-dbi-staff-http-test-only")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.api.v1 import dbi_inspection_staff_api, get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIAccessDenied, DBIFarmScope, DBIPlotScope,
    DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session  # noqa: E402
from app.dbi.inspection.campaign_link_service import (  # noqa: E402
    DBIInspectionCampaignLinkUnavailable,
)
from app.dbi.inspection.dual_approval import DBIInspectionApprovalConflict  # noqa: E402
from app.dbi.inspection.institutional_staff_directory import (  # noqa: E402
    DBIInspectionInstitutionalStaffDirectory,
)
from app.dbi.inspection.repository import DBIInspectionConflict  # noqa: E402

FARM = UUID("10000000-0000-4000-8000-000000000233")
PLOT = UUID("20000000-0000-4000-8000-000000000233")
CAMPAIGN = UUID("30000000-0000-4000-8000-000000000233")
OBSERVATION = UUID("40000000-0000-4000-8000-000000000233")
VERSION = UUID("50000000-0000-4000-8000-000000000233")
LINK = UUID("60000000-0000-4000-8000-000000000233")
STAFF = UUID("70000000-0000-4000-8000-000000000233")
BASE = f"/api/v1/dbi/organizations/dalgoro-test/farms/{FARM}/plots/{PLOT}"
LINK_PATH = f"{BASE}/campaigns/{CAMPAIGN}/inspection-links"
TECH_PATH = f"{BASE}/inspection-links/{LINK}/technical-validation"
ADMIN_PATH = f"{BASE}/inspection-links/{LINK}/administrative-authorization"


def context() -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref=str(STAFF),
        tenant_ref="tenant-ci-233",
        organization_refs=frozenset({"dalgoro-test"}),
        farm_scopes=frozenset({DBIFarmScope("dalgoro-test", FARM)}),
        plot_scopes=frozenset({DBIPlotScope("dalgoro-test", FARM, PLOT)}),
        permissions=frozenset({
            DBIPermission.READ, DBIPermission.WRITE,
            DBIPermission.MANAGE, DBIPermission.APPROVE_AGRONOMIC,
        }),
    )


def make_app(*, enabled: bool) -> FastAPI:
    if enabled:
        os.environ["DBI_INSPECT_STAFF_HTTP_ENABLED"] = "1"
    else:
        os.environ.pop("DBI_INSPECT_STAFF_HTTP_ENABLED", None)
    app = FastAPI()
    app.include_router(get_api_router(), prefix="/api/v1")
    return app


def main() -> None:
    disabled = make_app(enabled=False)
    paths = {route.path for route in disabled.routes}
    for target in (LINK_PATH, TECH_PATH, ADMIN_PATH):
        assert target not in paths
    with TestClient(disabled) as client:
        assert client.post(LINK_PATH, json={}).status_code == 404

    app = make_app(enabled=True)
    paths = {route.path for route in app.routes}
    assert all(target in paths for target in (LINK_PATH, TECH_PATH, ADMIN_PATH))
    session = MagicMock(spec=Session)
    staff = context()
    app.dependency_overrides[get_dbi_session] = lambda: session
    # Sin override de identidad, el JWT heredado sigue siendo obligatorio.
    with TestClient(app) as client:
        response = client.post(ADMIN_PATH, json={})
        assert response.status_code in (401, 403), response.text
        session.commit.assert_not_called()

    # Aislar sólo la dependencia de autenticación en test: el router conserva
    # Depends(get_dbi_access_context) para producción, nunca acepta actor HTTP.
    app.dependency_overrides[get_dbi_access_context] = lambda: staff
    with patch.object(dbi_inspection_staff_api, "DBIInspectionStaffWorkflow") as workflow:
        workflow.return_value.propose_link.return_value = (
            SimpleNamespace(id=LINK), True,
        )
        workflow.return_value.validate_technical.return_value = SimpleNamespace(
            stage="technical_validated",
        )
        workflow.return_value.authorize_administrative.return_value = SimpleNamespace(
            stage="self_approved",
        )
        with TestClient(app) as client:
            response = client.post(LINK_PATH, json={
                "observation_id": str(OBSERVATION),
                "observation_version_id": str(VERSION),
            })
            assert response.status_code == 201, response.text
            assert response.json() == {"link_id": str(LINK), "created": True}
            assert workflow.return_value.propose_link.call_args.args == (staff,)
            assert workflow.return_value.propose_link.call_args.kwargs == {
                "tenant_ref": staff.tenant_ref,
                "organization_ref": "dalgoro-test",
                "farm_id": FARM, "plot_id": PLOT,
                "campaign_id": CAMPAIGN,
                "observation_id": OBSERVATION,
                "observation_version_id": VERSION,
            }

            response = client.post(TECH_PATH, json={})
            assert response.status_code == 200, response.text
            assert response.json() == {"stage": "technical_validated"}
            assert workflow.return_value.validate_technical.call_args.args == (staff,)

            response = client.post(ADMIN_PATH, json={})
            assert response.status_code == 200, response.text
            assert response.json() == {"stage": "self_approved"}
            assert workflow.return_value.authorize_administrative.call_args.args == (staff,)
            assert workflow.return_value.authorize_administrative.call_args.kwargs == {
                "organization_ref": "dalgoro-test",
                "farm_id": FARM, "plot_id": PLOT, "link_id": LINK,
            }
            assert workflow.call_count == 3
            for call in workflow.call_args_list:
                assert call.args == (session,)
                directory = call.kwargs["staff_directory"]
                assert isinstance(directory, DBIInspectionInstitutionalStaffDirectory)
                assert directory._session is session
            assert session.commit.call_count == 3
            assert session.rollback.call_count == 0

            # Datos de cargo, identidad, tenant y "firma dual" jamás se aceptan.
            for path, payload in (
                (LINK_PATH, {
                    "observation_id": str(OBSERVATION),
                    "observation_version_id": str(VERSION),
                    "tenant_ref": "forged",
                }),
                (TECH_PATH, {"actor_ref": str(STAFF)}),
                (ADMIN_PATH, {"_staff_dual_role_verified": True}),
            ):
                assert client.post(path, json=payload).status_code == 422
            assert workflow.call_count == 3

            workflow.return_value.validate_technical.side_effect = DBIAccessDenied()
            assert client.post(TECH_PATH, json={}).status_code == 404
            workflow.return_value.validate_technical.side_effect = DBIInspectionApprovalConflict()
            assert client.post(TECH_PATH, json={}).status_code == 409
            workflow.return_value.propose_link.side_effect = DBIInspectionCampaignLinkUnavailable()
            assert client.post(LINK_PATH, json={
                "observation_id": str(OBSERVATION),
                "observation_version_id": str(VERSION),
            }).status_code == 404
            workflow.return_value.propose_link.side_effect = DBIInspectionConflict()
            assert client.post(LINK_PATH, json={
                "observation_id": str(OBSERVATION),
                "observation_version_id": str(VERSION),
            }).status_code == 409
            assert session.commit.call_count == 3
            assert session.rollback.call_count == 4

    os.environ.pop("DBI_INSPECT_STAFF_HTTP_ENABLED", None)
    print("OK: 3 rutas staff cerradas por defecto; JWT, scope, DTO y commit único.")


if __name__ == "__main__":
    main()
