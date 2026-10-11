"""Regresiones offline de recepción GIS privada y autorización exacta DBI."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
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
    list_gis_imports, receive_gis_import,
)
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.portal_gis_staging import (  # noqa: E402
    PortalGISSourceInvalid, normalize_upload_filename, validate_staged_source,
)
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
    paths = {r.path for r in get_api_router().routes}
    base = "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports"
    assert base in paths
    print("Recepción GIS DBI: límites, aislamiento, almacenamiento, rollback y rutas aprobados.")
