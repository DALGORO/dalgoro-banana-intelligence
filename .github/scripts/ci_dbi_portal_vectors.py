"""Regresiones offline de publicación GIS y aislamiento DBI."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_portal_vector.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-portal-vector")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from fastapi import HTTPException  # noqa: E402
from app.api.v1 import get_api_router  # noqa: E402
from app.api.v1.dbi_portal_vectors import _require_scope  # noqa: E402
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

    paths = {route.path for route in get_api_router().routes}
    base_path = "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/vector-layers"
    assert base_path in paths and base_path + "/{layer_id}" in paths
    print("Capas GIS del portal: validaciones GeoJSON y tenant/plot/rol aprobadas.")


if __name__ == "__main__":
    check_vectors()
