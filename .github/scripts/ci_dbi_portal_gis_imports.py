"""Regresiones offline de recepción GIS privada y autorización exacta DBI."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from io import BytesIO
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_gis_import.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-gis-stage")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from fastapi import HTTPException  # noqa: E402
from app.api.v1 import get_api_router  # noqa: E402
from app.api.v1.dbi_portal_gis_imports import (  # noqa: E402
    list_gis_imports, receive_gis_import, select_gis_import_layer,
    PortalGISLayerChoice, get_gis_import_preview,
)
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.portal_gis_staging import (  # noqa: E402
    PortalGISSourceInvalid, normalize_upload_filename, validate_staged_source,
)
from app.dbi.models.portal_gis_imports import DBIPortalGISImport  # noqa: E402
from app.dbi.storage_contracts import DBIStoragePurpose  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402


def _shapefile_zip():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for extension in ("shp", "shx", "dbf", "prj"):
            archive.writestr(f"sector.{extension}", b"content-" + extension.encode())
    return buffer.getvalue()


class Request:
    def __init__(self, data, *, content_type="application/octet-stream", length=None):
        self.data = data
        self.headers = {"content-type": content_type}
        if length is not None:
            self.headers["content-length"] = str(length)

    async def stream(self):
        midpoint = len(self.data) // 2
        yield self.data[:midpoint]
        yield self.data[midpoint:]


class Store:
    def __init__(self):
        self.saved = []
        self.retired = []

    def put(self, request, stream):
        data = stream.read()
        metadata = request.metadata
        assert metadata.address.purpose is DBIStoragePurpose.TECHNICAL_SOURCE
        assert sha256(data).hexdigest() == metadata.sha256
        assert len(data) == metadata.size_bytes
        self.saved.append((metadata, data))
        return SimpleNamespace(record=SimpleNamespace(metadata=metadata))

    def retire(self, address, *, retired_at):
        self.retired.append(address)
        return True


class Session:
    def __init__(self, campaign_id):
        self.campaign_id = campaign_id
        self.rows = []
        self.failed_commit = False

    def execute(self, statement):
        text = str(statement).lower()
        if "from dbi_campaigns" in text:
            return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(id=self.campaign_id))
        assert "from dbi_portal_gis_imports" in text
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.rows))

    def add(self, row):
        if row.id is None:
            row.id = uuid4()
        self.rows.append(row)

    def commit(self):
        if self.failed_commit:
            raise RuntimeError("mock database not available")

    def refresh(self, row):
        row.created_at = datetime.now(timezone.utc)

    def rollback(self):
        self.rows.clear()


def _context(farm_id, plot_id, permissions):
    return DBIAccessContext(
        principal_ref="staff-gis", tenant_ref="tenant-a",
        organization_refs=frozenset({"org-a"}),
        farm_scopes=frozenset({DBIFarmScope("org-a", farm_id)}),
        plot_scopes=frozenset({DBIPlotScope("org-a", farm_id, plot_id)}),
        permissions=frozenset(permissions),
    )


async def check_http():
    farm, plot, campaign = uuid4(), uuid4(), uuid4()
    session = Session(campaign)
    store = Store()
    writer = _context(farm, plot, {DBIPermission.MANAGE})
    reader = _context(farm, plot, {DBIPermission.READ})
    data = _shapefile_zip()
    kwargs = {
        "organization_ref": "org-a", "farm_id": farm, "plot_id": plot,
        "session": session, "store": store, "campaign_id": campaign,
        "layer_kind": "plants", "filename": "sector.zip", "name": "Inventario de plantas",
    }
    receipt = await receive_gis_import(Request(data, length=len(data)), context=writer, **kwargs)
    assert receipt.status == "received"
    assert receipt.original_filename == "sector.zip"
    assert receipt.campaign_id == campaign
    assert not hasattr(receipt, "sha256") and not hasattr(receipt, "source_object_id")
    assert len(store.saved) == 1
    assert store.saved[0][0].address.tenant_ref == "tenant-a"
    assert list_gis_imports("org-a", farm, plot, session, writer)[0].id == receipt.id

    try:
        await receive_gis_import(Request(data), context=reader, **kwargs)
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("READ no debe cargar GIS")

    try:
        await receive_gis_import(Request(data), context=writer, **{**kwargs, "plot_id": uuid4()})
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("Otro lote debe permanecer oculto")

    for case in (
        Request(data, content_type="text/plain"),
        Request(data, length=31457281),
        Request(b"not a ZIP"),
    ):
        try:
            await receive_gis_import(case, context=writer, **kwargs)
        except HTTPException as error:
            assert error.status_code in (413, 415, 422)
        else:
            raise AssertionError("Contenido no permitido debe ser rechazado")
    assert len(store.saved) == 1

    session.failed_commit = True
    try:
        await receive_gis_import(Request(data), context=writer, **kwargs)
    except HTTPException as error:
        assert error.status_code == 503
    else:
        raise AssertionError("Sin DB no se confirma la recepción.")
    assert len(store.retired) == 1



class ChoiceSession:
    """Emula consultas exactas y comprueba FOR UPDATE sin Postgres real."""
    def __init__(self, row):
        self.row = row
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False
        self.locked = False
        self.campaign_valid = True

    def execute(self, statement):
        sql = str(statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ))
        if "FROM dbi_portal_gis_imports" in sql:
            self.locked = "FOR UPDATE" in sql
            matched = all(
                f"dbi_portal_gis_imports.{field} = '{value}'" in sql
                for field, value in (
                    ("id", self.row.id),
                    ("tenant_ref", self.row.tenant_ref),
                    ("organization_ref", self.row.organization_ref),
                    ("farm_id", self.row.farm_id),
                    ("plot_id", self.row.plot_id),
                )
            )
            return SimpleNamespace(
                scalar_one_or_none=lambda: self.row if matched else None,
            )
        assert "FROM dbi_campaigns" in sql, sql
        matched = self.campaign_valid and all(
            f"dbi_campaigns.{field} = '{value}'" in sql
            for field, value in (
                ("id", self.row.campaign_id),
                ("tenant_ref", self.row.tenant_ref),
                ("organization_ref", self.row.organization_ref),
                ("farm_id", self.row.farm_id),
                ("plot_id", self.row.plot_id),
            )
        )
        return SimpleNamespace(
            scalar_one_or_none=lambda: SimpleNamespace(id=self.row.campaign_id) if matched else None,
        )

    def commit(self):
        if self.fail_commit:
            raise SQLAlchemyError("private DB unavailable")
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        self.row.selected_layer = None


def _choice_receipt():
    return DBIPortalGISImport(
        id=uuid4(), tenant_ref="tenant-a", organization_ref="org-a",
        farm_id=uuid4(), plot_id=uuid4(), campaign_id=uuid4(),
        source_object_id=uuid4(), source_format="gpkg",
        original_filename="sector.gpkg", name="Inventario",
        layer_kind="plants", size_bytes=256, sha256="a" * 64,
        status="needs_selection", available_layers=["plantas", "límites finca"],
        selected_layer=None, attempt_count=1,
        created_at=datetime.now(timezone.utc), created_by_ref="staff-gis",
    )


def check_layer_selection():
    row = _choice_receipt()
    session = ChoiceSession(row)
    writer = _context(row.farm_id, row.plot_id, {DBIPermission.MANAGE})
    reader = _context(row.farm_id, row.plot_id, {DBIPermission.READ})

    def choose(layer="plantas", context=writer, import_id=None, org="org-a",
               farm=None, plot=None):
        return select_gis_import_layer(
            org, farm or row.farm_id, plot or row.plot_id, import_id or row.id,
            PortalGISLayerChoice(layer=layer), session, context,
        )

    def reject(code, operation):
        before = session.commits
        try:
            operation()
        except HTTPException as error:
            assert error.status_code == code, (error.status_code, code)
        else:
            raise AssertionError(f"Se esperaba denegación HTTP {code}")
        assert session.commits == before

    reject(404, lambda: choose(context=reader))
    reject(404, lambda: choose(context=_context(row.farm_id, uuid4(), {DBIPermission.MANAGE})))
    reject(404, lambda: choose(context=_context(uuid4(), row.plot_id, {DBIPermission.MANAGE})))
    reject(404, lambda: choose(org="otra-org"))
    reject(404, lambda: choose(import_id=uuid4()))
    other_tenant = DBIAccessContext(
        principal_ref="other-staff", tenant_ref="tenant-b",
        organization_refs=frozenset({"org-a"}),
        farm_scopes=frozenset({DBIFarmScope("org-a", row.farm_id)}),
        plot_scopes=frozenset({DBIPlotScope("org-a", row.farm_id, row.plot_id)}),
        permissions=frozenset({DBIPermission.MANAGE}),
    )
    reject(404, lambda: choose(context=other_tenant))
    session.campaign_valid = False
    reject(404, choose)
    session.campaign_valid = True

    for candidate in ("fantasma", "Plantas", "plantas ", "limites finca"):
        reject(422, lambda candidate=candidate: choose(layer=candidate))
    for malformed in ({}, {"layer": ""}, {"layer": "x" * 101},
                      {"layer": "plantas", "force": True}, {"layer": 123}):
        try:
            PortalGISLayerChoice.model_validate(malformed)
        except ValidationError:
            pass
        else:
            raise AssertionError("Payload de selección inseguro aceptado")

    session.fail_commit = True
    reject(503, choose)
    assert session.rollbacks == 1 and row.selected_layer is None
    session.fail_commit = False

    saved = choose(layer="límites finca")
    assert session.locked and saved.selected_layer == "límites finca"
    assert saved.available_layers == ["plantas", "límites finca"]
    assert saved.status == "needs_selection" and saved.published_layer_id is None
    assert row.attempt_count == 1 and session.commits == 1
    assert not hasattr(saved, "sha256") and not hasattr(saved, "source_object_id")

    replay = choose(layer="límites finca")
    assert replay.selected_layer == saved.selected_layer and session.commits == 1
    reject(409, choose)
    reject(404, lambda: get_gis_import_preview(
        "org-a", row.farm_id, row.plot_id, row.id, session, writer,
    ))

    for state in ("received", "processing", "prepared", "published", "failed"):
        row.status = state
        reject(409, lambda: choose(layer="límites finca"))
    row.status = "needs_selection"
    row.source_format = "shp_zip"
    reject(409, lambda: choose(layer="límites finca"))


def check_zip():
    zip_data = _shapefile_zip()
    validate_staged_source(BytesIO(zip_data), "shp_zip")
    assert normalize_upload_filename("valid.GPKG")[1] == "gpkg"
    assert normalize_upload_filename("valid.zip")[2] == "application/zip"
    for filename in ("../secret.gpkg", "..\\secret.zip", "fake.exe", "something:bad.zip"):
        try:
            normalize_upload_filename(filename)
        except PortalGISSourceInvalid:
            pass
        else:
            raise AssertionError(f"Nombre peligroso permitido: {filename}")
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        for suffix in ("shp", "shx", "dbf", "prj"):
            archive.writestr(f"../hacked.{suffix}", b"a")
    try:
        validate_staged_source(BytesIO(payload.getvalue()), "shp_zip")
    except PortalGISSourceInvalid:
        pass
    else:
        raise AssertionError("ZIP traversal permitido")
    try:
        validate_staged_source(BytesIO(b"PK\x03\x04corrupt"), "shp_zip")
    except PortalGISSourceInvalid:
        pass
    else:
        raise AssertionError("ZIP corrupto permitido")

    assert "application/zip" in DBIStoragePolicy.allowed_content_types[DBIStoragePurpose.TECHNICAL_SOURCE]
    assert "application/geopackage+sqlite3" in DBIStoragePolicy.allowed_content_types[DBIStoragePurpose.TECHNICAL_SOURCE]


if __name__ == "__main__":
    check_zip()
    asyncio.run(check_http())
    check_layer_selection()
    paths = {r.path for r in get_api_router().routes}
    base = "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports"
    assert base in paths
    assert f"{base}/{{import_id}}/select-layer" in paths
    print("Recepción GIS DBI: límites, aislamiento, almacenamiento, rollback y rutas aprobados.")
