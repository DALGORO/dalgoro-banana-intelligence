"""Aprobación GIS: solo tras preview, MANAGE, Campaign válida e idempotencia."""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_gis_approval.db")
os.environ.setdefault("JWT_SECRET", "ci-gis-approval-only")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from fastapi import HTTPException  # noqa: E402
from app.api.v1 import get_api_router  # noqa: E402
from app.api.v1.dbi_portal_gis_imports import publish_reviewed_gis_import  # noqa: E402
from app.dbi.authorization import DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission  # noqa: E402
from app.dbi.models.portal_gis_imports import DBIPortalGISImport, DBIPortalGISPreview  # noqa: E402
from app.dbi.models.portal_vectors import DBIPortalVectorLayer  # noqa: E402


def context(row, permission=DBIPermission.MANAGE):
    return DBIAccessContext(
        principal_ref="gis-reviewer", tenant_ref=row.tenant_ref,
        organization_refs=frozenset({row.organization_ref}),
        farm_scopes=frozenset({DBIFarmScope(row.organization_ref, row.farm_id)}),
        plot_scopes=frozenset({DBIPlotScope(row.organization_ref, row.farm_id, row.plot_id)}),
        permissions=frozenset({permission}),
    )


class Session:
    def __init__(self, row, preview):
        self.row = row
        self.preview = preview
        self.layer = None
        self.additions = 0
        self.commits = 0

    def execute(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        if "FROM dbi_portal_gis_imports" in sql:
            found = self.row if all(value in sql for value in (
                str(self.row.id), self.row.tenant_ref, self.row.organization_ref,
                str(self.row.farm_id), str(self.row.plot_id),
            )) else None
        elif "FROM dbi_campaigns" in sql:
            found = object() if all(value in sql for value in (
                str(self.row.campaign_id), self.row.tenant_ref,
                self.row.organization_ref, str(self.row.farm_id), str(self.row.plot_id),
            )) else None
        elif "FROM dbi_portal_vector_layers" in sql:
            found = self.layer
            if found is not None and not all(value in sql for value in (
                self.row.tenant_ref, self.row.organization_ref, str(self.row.farm_id),
                str(self.row.plot_id), str(self.row.campaign_id), self.row.layer_kind,
                self.preview.sha256,
            )):
                found = None
            if found is not None and self.row.status == "published" and str(found.id) not in sql:
                found = None
        else:
            raise AssertionError("Consulta no reconocida para prueba: " + sql[:150])

        class Result:
            def scalar_one_or_none(self):
                return found
        return Result()

    def get(self, model, import_id):
        assert model is DBIPortalGISPreview
        return self.preview if self.preview and self.preview.import_id == import_id else None

    def add(self, layer):
        assert isinstance(layer, DBIPortalVectorLayer)
        self.layer = layer
        self.additions += 1

    def flush(self):
        # Simula la CHECK PostgreSQL: status published exige FK antes del flush.
        assert self.row.status != "published" or self.row.published_layer_id is not None
        if self.layer is not None and self.layer.created_at is None:
            self.layer.created_at = datetime.now(timezone.utc)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def run():
    raw = json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-79.8, -3.3]},
            "properties": {"densidad": 1430},
        }],
    }, separators=(",", ":"), ensure_ascii=False)
    row = DBIPortalGISImport(
        id=uuid4(), tenant_ref="tenant-gis", organization_ref="org-gis",
        farm_id=uuid4(), plot_id=uuid4(), campaign_id=uuid4(), source_object_id=uuid4(),
        source_format="gpkg", original_filename="sector.gpkg", name="Plantas GPS",
        layer_kind="plants", size_bytes=1000, sha256="f"*64, status="prepared",
        attempt_count=1, created_at=datetime.now(timezone.utc), created_by_ref="gis-uploader",
    )
    preview = DBIPortalGISPreview(
        import_id=row.id, geojson_text=raw, sha256=sha256(raw.encode()).hexdigest(),
        feature_count=1,
    )
    session = Session(row, preview)
    args = (row.organization_ref, row.farm_id, row.plot_id, row.id)
    for invalid_context, invalid_plot in (
        (context(row, DBIPermission.READ), row.plot_id),
        (context(row), uuid4()),
    ):
        try:
            publish_reviewed_gis_import(args[0], args[1], invalid_plot, args[3], session, invalid_context)
        except HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError("Denegación MANAGE o plot omitida")
    assert session.commits == 0

    original = preview.sha256
    preview.sha256 = "0" * 64
    try:
        publish_reviewed_gis_import(*args, session, context(row))
    except HTTPException as error:
        assert error.status_code == 409
    else:
        raise AssertionError("Preview adulterado publicado")
    assert session.additions == 0
    preview.sha256 = original

    row.status = "received"
    try:
        publish_reviewed_gis_import(*args, session, context(row))
    except HTTPException as error:
        assert error.status_code == 409
    else:
        raise AssertionError("Se publicó sin conversión")
    row.status = "prepared"

    layer = publish_reviewed_gis_import(*args, session, context(row))
    assert row.status == "published"
    assert row.published_layer_id == layer.id
    assert row.approved_by_ref == "gis-reviewer"
    assert row.approved_at is not None
    assert session.layer.source_bytes == raw.encode()
    assert session.layer.source_sha256 == original
    assert session.additions == 1 and session.commits == 1

    again = publish_reviewed_gis_import(*args, session, context(row))
    assert again.id == layer.id
    assert session.additions == 1 and session.commits == 1
    paths = {entry.path for entry in get_api_router().routes}
    assert ("/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
            "/map/gis-imports/{import_id}/publish") in paths
    print("Aprobación GIS: MANAGE exacto, huella, revisión, audit trail e idempotencia OK.")


if __name__ == "__main__":
    run()
