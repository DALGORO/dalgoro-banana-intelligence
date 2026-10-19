"""Regresiones offline de publicación GIS y aislamiento DBI."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
import os
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_portal_vector.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-portal-vector")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402
from app.api.v1 import get_api_router  # noqa: E402
from app.api.v1.dbi_portal_vectors import _editable_campaign, _require_scope, list_vector_campaigns  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.portal_vector_validation import (  # noqa: E402
    validate_portal_geojson, DBIPortalVectorInvalid,
)


def check_vectors():
    raw = {
        "type": "FeatureCollection", "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-79.8, -3.3]},
            "properties": {"densidad": 1450.0, "object_key": "private/file", "nota": "Correcta"},
        }],
    }
    result = validate_portal_geojson(json.dumps(raw).encode())
    assert result.feature_count == 1
    assert len(result.source_sha256) == 64
    props = json.loads(result.geojson_text)["features"][0]["properties"]
    assert props == {"densidad": 1450.0, "nota": "Correcta"}

    for geometry in (
        {"type": "Point", "coordinates": [600000, 9500000]},
        {"type": "GeometryCollection", "geometries": []},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]]},
    ):
        broken = {**raw, "features": [{**raw["features"][0], "geometry": geometry}]}
        try:
            validate_portal_geojson(json.dumps(broken).encode())
        except DBIPortalVectorInvalid:
            pass
        else:
            raise AssertionError("Geometría insegura debería rechazarse")

    farm, plot = uuid4(), uuid4()
    base = dict(
        principal_ref="principal-a", tenant_ref="tenant-a",
        organization_refs=frozenset({"org-a"}),
        farm_scopes=frozenset({DBIFarmScope("org-a", farm)}),
        plot_scopes=frozenset({DBIPlotScope("org-a", farm, plot)}),
    )
    readonly = DBIAccessContext(**base, permissions=frozenset({DBIPermission.READ}))
    try:
        _require_scope(readonly, "org-a", farm, plot, publish=True)
    except HTTPException as err:
        assert err.status_code == 404
    else:
        raise AssertionError("Lector no debe publicar capas")
    manage = DBIAccessContext(**base, permissions=frozenset({DBIPermission.MANAGE}))
    _require_scope(manage, "org-a", farm, plot, publish=True)
    try:
        _require_scope(manage, "org-a", farm, uuid4(), publish=True)
    except HTTPException as err:
        assert err.status_code == 404
    else:
        raise AssertionError("Otro lote debe denegarse")

    # Descubrimiento de Campaign independiente de RGB, sin otro tenant o lote.
    expected_campaign = SimpleNamespace(
        id=uuid4(), name="Vuelo densidad autorizado",
        captured_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        analysis_type="density", status="PUBLISHED",
    )

    class ScopedSession:
        def execute(self, statement):
            compiled = statement.compile(dialect=postgresql.dialect())
            sql = str(compiled).lower()
            assert "dbi_campaigns.tenant_ref =" in sql
            assert "dbi_campaigns.organization_ref =" in sql
            assert "dbi_campaigns.farm_id =" in sql
            assert "dbi_campaigns.plot_id =" in sql
            assert "dbi_campaigns.analysis_type in" in sql
            assert "dbi_campaigns.captured_at is not null" in sql
            assert "limit" in sql
            assert "tenant-a" in compiled.params.values()
            assert "org-a" in compiled.params.values()
            assert farm in compiled.params.values()
            assert plot in compiled.params.values()
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [expected_campaign])
            )

    scoped = list_vector_campaigns("org-a", farm, plot, ScopedSession(), readonly)
    assert len(scoped) == 1
    assert scoped[0].id == expected_campaign.id
    assert scoped[0].analysis_type == "density"
    assert scoped[0].captured_at == expected_campaign.captured_at
    try:
        list_vector_campaigns("org-a", farm, uuid4(), ScopedSession(), readonly)
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("Campañas de otro lote deben quedar ocultas")

    # Regression: un cambio de capa DESPUÉS de APPROVED podría entrar en la
    # Campaign publicada sin revisión del archivo añadido. Fail closed.
    class EditableSession:
        def __init__(self, row):
            self.row = row
            self.queries = 0

        def execute(self, statement):
            compiled = statement.compile(dialect=postgresql.dialect())
            sql = str(compiled).lower()
            assert "for update" in sql
            assert "dbi_campaigns.tenant_ref =" in sql
            assert "dbi_campaigns.organization_ref =" in sql
            assert "dbi_campaigns.farm_id =" in sql
            assert "dbi_campaigns.plot_id =" in sql
            assert "tenant-a" in compiled.params.values()
            assert "org-a" in compiled.params.values()
            assert farm in compiled.params.values()
            assert plot in compiled.params.values()
            self.queries += 1
            return SimpleNamespace(scalar_one_or_none=lambda: self.row)

    def check_locked_campaign(status, *, approved_at=None, published_at=None, permitted=False):
        row = SimpleNamespace(
            id=expected_campaign.id, status=status,
            approved_at=approved_at, published_at=published_at,
        )
        session = EditableSession(row)
        if permitted:
            result = _editable_campaign(
                session, manage, "org-a", farm, plot, expected_campaign.id,
            )
            assert result is row
        else:
            try:
                _editable_campaign(
                    session, manage, "org-a", farm, plot, expected_campaign.id,
                )
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Una Campaign aprobada aceptó edición GIS.")
        assert session.queries == 1

    for state in ("DRAFT", "PROCESSING", "ANALYZED", "TECHNICAL_REVIEW", "FIELD_COMPLETED"):
        check_locked_campaign(state, permitted=True)
    for state in ("APPROVED", "PUBLISHED"):
        check_locked_campaign(state)
    now = datetime(2026, 10, 18, 15, tzinfo=timezone.utc)
    check_locked_campaign("TECHNICAL_REVIEW", approved_at=now)
    check_locked_campaign("DRAFT", published_at=now)
    try:
        _editable_campaign(
            EditableSession(None), manage, "org-a", farm, plot, expected_campaign.id,
        )
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("Una Campaign inexistente debe permanecer oculta.")

    paths = {route.path for route in get_api_router().routes}
    base_path = "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/vector-layers"
    assert base_path in paths and base_path + "/{layer_id}" in paths
    assert base_path.replace("vector-layers", "vector-campaigns") in paths
    print("Capas GIS del portal: validaciones GeoJSON y tenant/plot/rol aprobadas.")


if __name__ == "__main__":
    check_vectors()
