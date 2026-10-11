"""Regresiones de aprobación GIS separada de recepción y conversión."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_gis_publication.db")
os.environ.setdefault("JWT_SECRET", "ci-dbi-gis-publication")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from fastapi import HTTPException  # noqa: E402
from app.api.v1 import get_api_router  # noqa: E402
from app.api.v1.dbi_portal_gis_imports import publish_prepared_gis_import  # noqa: E402
from app.dbi.authorization import DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission  # noqa: E402
from app.dbi.models.portal_gis_imports import DBIPortalGISImport, DBIPortalGISPreview  # noqa: E402
from app.dbi.models.portal_vectors import DBIPortalVectorLayer  # noqa: E402
from app.dbi.portal_vector_validation import validate_portal_geojson  # noqa: E402


def data():
    return json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-79.8, -3.3]},
            "properties": {"plantas": 1420},
        }],
    }, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class FakeSession:
    def __init__(self, row, preview):
        self.row, self.preview = row, preview
        self.layer = None
        self.added_layers = 0
        self.commits = 0

    def execute(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        row = self.row
        # Solo los IDs solicitados explícitamente satisfacen el mock.
        scoped = all(key in sql for key in (
            row.tenant_ref, row.organization_ref,
            str(row.farm_id), str(row.plot_id),
        ))
        if "FROM dbi_campaigns" in sql:
            found = object() if scoped and str(row.campaign_id) in sql else None
        elif "FROM dbi_portal_gis_imports" in sql:
            found = row if scoped and str(row.id) in sql else None
        elif "FROM dbi_portal_vector_layers" in sql:
            found = self.layer if scoped and str(row.campaign_id) in sql else None
        else:
            raise AssertionError(f"SQL inesperado: {sql}")
        return type("One", (), {"scalar_one_or_none": lambda self: found})()

    def get(self, model, identifier):
        if model is DBIPortalGISPreview:
            return self.preview if identifier == self.row.id else None
        if model is DBIPortalVectorLayer:
            return self.layer if self.layer is not None and self.layer.id == identifier else None
        raise AssertionError("Modelo desconocido")

    def add(self, entity):
        assert isinstance(entity, DBIPortalVectorLayer)
        entity.id = uuid4()
        entity.created_at = datetime.now(timezone.utc)
        self.layer = entity
        self.added_layers += 1

    def flush(self):
        pass

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass

    def rollback(self):
        raise AssertionError("El caso de éxito no debe hacer rollback.")


def make_case(*, status="prepared"):
    raw = data()
    normalized = validate_portal_geojson(raw).geojson_text
    original = DBIPortalGISImport(
        id=uuid4(), tenant_ref="orgtenant-gis", organization_ref="org-gis",
        farm_id=uuid4(), plot_id=uuid4(), campaign_id=uuid4(),
        source_object_id=uuid4(), source_format="gpkg",
        original_filename="plants.gpkg", name="Inventario verificado",
        layer_kind="plants", size_bytes=30,
        sha256=sha256(b"dummy source").hexdigest(),
        status=status, attempt_count=1,
        created_by_ref="gestor-gis", created_at=datetime.now(timezone.utc),
    )
    preview = DBIPortalGISPreview(
        import_id=original.id, geojson_text=normalized,
        sha256=sha256(normalized.encode("utf-8")).hexdigest(),
        feature_count=1, created_at=datetime.now(timezone.utc),
    )
    return original, preview, FakeSession(original, preview)


def context(row, *, manager=True):
    return DBIAccessContext(
        principal_ref="gestor-gis", tenant_ref=row.tenant_ref,
        organization_refs=frozenset({row.organization_ref}),
        farm_scopes=frozenset({DBIFarmScope(row.organization_ref, row.farm_id)}),
        plot_scopes=frozenset({DBIPlotScope(row.organization_ref, row.farm_id, row.plot_id)}),
        permissions=frozenset({DBIPermission.MANAGE if manager else DBIPermission.READ}),
    )


def call(row, session, ctx, *, plot_id=None):
    return publish_prepared_gis_import(
        row.organization_ref, row.farm_id, plot_id or row.plot_id,
        row.id, session, ctx,
    )


def expect_denied(fn, code: int):
    try:
        fn()
    except HTTPException as error:
        assert error.status_code == code, (error.status_code, error.detail)
    else:
        raise AssertionError(f"Se esperaba rechazo HTTP {code}")


def main():
    row, preview, session = make_case()
    expect_denied(lambda: call(row, session, context(row, manager=False)), 404)
    expect_denied(lambda: call(row, session, context(row), plot_id=uuid4()), 404)
    assert session.commits == 0
    assert session.layer is None

    layer = call(row, session, context(row))
    assert row.status == "published"
    assert row.published_layer_id == layer.id
    assert row.published_at is not None
    assert session.added_layers == 1
    assert session.layer.source_sha256 == preview.sha256
    assert session.layer.campaign_id == row.campaign_id
    assert session.layer.created_by_ref == "gestor-gis"
    assert session.layer.source_bytes == preview.geojson_text.encode("utf-8")
    assert session.commits == 1
    replay = call(row, session, context(row))
    assert replay.id == layer.id
    assert session.added_layers == 1
    assert session.commits == 1

    pending, _, pending_session = make_case(status="received")
    expect_denied(lambda: call(pending, pending_session, context(pending)), 409)
    assert pending_session.layer is None
    for field, broken in (("sha256", "f" * 64), ("feature_count", 2),
                          ("geojson_text", preview.geojson_text.replace("-79.8", "1e999"))):
        forged, forged_preview, forged_session = make_case()
        setattr(forged_preview, field, broken)
        expect_denied(lambda: call(forged, forged_session, context(forged)), 409)
        assert forged_session.layer is None
        assert forged.status == "prepared"

    path = "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports/{import_id}/publish"
    assert path in {route.path for route in get_api_router().routes}
    print("GIS aprobado: MANAGE, scope, Campaign, SHA, idempotencia y ausencia de publicación implícita OK.")


if __name__ == "__main__":
    main()
