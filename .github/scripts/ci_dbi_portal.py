"""Prueba offline del catálogo del cliente: sin escalada por tenant/lote."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_portal.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-portal")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from sqlalchemy.dialects import postgresql  # noqa: E402
from app.api.v1 import get_api_router  # noqa: E402
from app.dbi import portal  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission,
)


def validate_portal() -> None:
    principal_id, farm_id, plot_id = uuid4(), uuid4(), uuid4()
    other_farm, other_plot = uuid4(), uuid4()
    context = DBIAccessContext(
        principal_ref="principal-1", tenant_ref="tenant-a",
        organization_refs=frozenset({"org-a"}),
        farm_scopes=frozenset({DBIFarmScope("org-a", farm_id)}),
        plot_scopes=frozenset({DBIPlotScope("org-a", farm_id, plot_id)}),
        permissions=frozenset({DBIPermission.READ}),
    )

    class FakeRepo:
        def __init__(self, session): pass
        def list_principals(self, *, legacy_identity_ref):
            assert legacy_identity_ref == "42"
            return [SimpleNamespace(id=principal_id, status="active")]

    class FakeResolver:
        def __init__(self, repo): pass
        def resolve(self, *, legacy_identity_ref, tenant_ref):
            assert legacy_identity_ref == "42" and tenant_ref == "tenant-a"
            return context

    class FakeSession:
        def __init__(self): self.sql = []
        def execute(self, stmt):
            sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
            self.sql.append((sql, stmt.compile(dialect=postgresql.dialect()).params))
            if "dbi_memberships" in sql:
                rows = ["tenant-a"]
            elif "from dbi_farms" in sql:
                rows = [
                    SimpleNamespace(
                        id=farm_id, organization_ref="org-a", name="Finca A",
                        code="F-A", status="active",
                    ),
                    SimpleNamespace(
                        id=other_farm, organization_ref="org-b", name="Finca B",
                        code="F-B", status="active",
                    ),
                ]
            elif "from dbi_plots" in sql:
                rows = [
                    SimpleNamespace(
                        id=plot_id, farm_id=farm_id, name="Lote 1",
                        code="L-1", area_hectares=Decimal("12.50"),
                    ),
                    SimpleNamespace(
                        id=other_plot, farm_id=other_farm, name="Lote B",
                        code="L-B", area_hectares=None,
                    ),
                ]
            else:
                raise AssertionError(f"Consulta no prevista: {sql}")
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    session = FakeSession()
    with patch.object(portal, "DBIIdentityRepository", FakeRepo), patch.object(
        portal, "DBIAccessContextResolver", FakeResolver
    ):
        response = portal.read_portal_accounts(
            session, authenticated_user_id=42
        )
    assert len(response) == 1
    assert response[0].tenant_ref == "tenant-a"
    assert len(response[0].farms) == 1
    assert response[0].farms[0].name == "Finca A"
    assert len(response[0].farms[0].plots) == 1
    assert response[0].farms[0].plots[0].area_hectares == 12.5
    assert "dbi_farms.id in" in session.sql[1][0]
    assert "dbi_plots.id in" in session.sql[2][0]
    assert all("object_key" not in field for field in response[0].model_fields)

    paths = {route.path for route in get_api_router().routes}
    assert "/dbi/portal/accounts" in paths
    print("DBI portal: aislamiento de cuentas/fincas/lotes validado offline.")


if __name__ == "__main__":
    validate_portal()
