"""CI H14/2E: QML privada de bytes reales sintéticos, sin DB/S3/Render."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-only-scientific-qml-private")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from app.api.v1.dbi_scientific_qml_private import (  # noqa: E402
    MAX_QML_BYTES, _address, _store, get_private_qml_receipt, receive_private_qml,
)
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.campaigns.contracts import DBICampaignSnapshot  # noqa: E402
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402

FARM = UUID("91000000-0000-4000-8000-000000000001")
PLOT = UUID("91000000-0000-4000-8000-000000000002")
CAMPAIGN = UUID("91000000-0000-4000-8000-000000000003")
DATE = datetime(2026, 10, 18, 9, 30, tzinfo=timezone.utc)
TENANT = "tenant-ci"
ORG = "org-ci"
QML = b'<?xml version="1.0"?><qgis><rasterrenderer type="singlebandpseudocolor"/></qgis>'


def snapshot(**changes) -> DBICampaignSnapshot:
    data = {
        "campaign_id": CAMPAIGN, "tenant_ref": TENANT, "organization_ref": ORG,
        "farm_id": FARM, "plot_id": PLOT, "analysis_type": "multispectral",
        "captured_at": DATE, "status": "TECHNICAL_REVIEW",
        "processed_at": None, "created_at": DATE, "updated_at": DATE,
        "reviewed_at": None, "field_started_at": None,
        "field_completed_at": None, "approved_at": None, "published_at": None,
        "current_revision_id": None, "source_job_id": None,
    }
    data.update(changes)
    return DBICampaignSnapshot.model_validate(data)


def context(permission=DBIPermission.MANAGE, *, tenant=TENANT):
    return DBIAccessContext(
        principal_ref="scientist-ci", tenant_ref=tenant,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset({DBIFarmScope(ORG, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORG, FARM, PLOT)}),
        permissions=frozenset({permission}),
    )


class FakeSession:
    def commit(self):
        raise AssertionError("Jamás escribir en DB.")

    def add(self, *_):
        raise AssertionError("Jamás añadir a DB.")


class RequestDouble:
    def __init__(self, payload: bytes, store):
        self.payload = payload
        self.app = SimpleNamespace(state=SimpleNamespace(dbi_object_store=store))
        self.stream_calls = 0

    async def stream(self):
        self.stream_calls += 1
        for start in range(0, len(self.payload), 13):
            yield self.payload[start:start + 13]


class Reader:
    current = snapshot()
    calls = 0

    def __init__(self, session):
        assert isinstance(session, FakeSession)

    def read_campaign(self, **kwargs):
        Reader.calls += 1
        assert kwargs["tenant_ref"] in {TENANT, "another"}
        assert {key: value for key, value in kwargs.items() if key != "tenant_ref"} == {
            "organization_ref": ORG, "farm_id": FARM,
            "plot_id": PLOT, "campaign_id": CAMPAIGN,
        }
        return Reader.current


def upload(request, *, ctx=None, index="ndvi", size=None, hash_value=None,
           mime="application/octet-stream"):
    return asyncio.run(receive_private_qml(
        ORG, FARM, PLOT, CAMPAIGN, index, request, Response(),
        FakeSession(), ctx or context(),
        len(request.payload) if size is None else size,
        sha256(request.payload).hexdigest() if hash_value is None else hash_value,
        mime,
    ))


def deny(call, code):
    try:
        call()
    except HTTPException as error:
        assert error.status_code == code, error
    else:
        raise AssertionError(f"Operación insegura admitida (HTTP {code}).")


def fake_test_store(request):
    provider = request.app.state.dbi_object_store
    if provider is None:
        raise HTTPException(503, detail="CI: no hay almacenamiento.")
    return provider


def run_tests():
    store = DBIInMemoryObjectStore()
    # El adaptador en memoria NO debe poder ser destino productivo.
    deny(lambda: _store(RequestDouble(QML, store)), 503)
    deny(lambda: _store(RequestDouble(QML, None)), 503)
    with patch.dict(os.environ, {"DBI_SCIENTIFIC_QML_INTAKE_ENABLED": "1"}), patch(
        "app.api.v1.dbi_scientific_qml_private.DBICampaignReader", Reader
    ), patch("app.api.v1.dbi_scientific_qml_private._store", fake_test_store):
        request = RequestDouble(QML, store)
        response = upload(request)
        assert response.schema_version == "dbi-h14-private-qml-receipt.v1"
        assert response.created is True and response.file_received_privately
        assert not any((response.bundle_received, response.scientific_validated,
                        response.institutional_approved, response.published))
        assert response.sha256 == sha256(QML).hexdigest()
        assert request.stream_calls == 1
        address = _address(context(), ORG, FARM, PLOT, CAMPAIGN, "ndvi")
        with store.open_read(address) as original:
            assert original.read() == QML, "Los bytes originales se alteraron."
        again = upload(RequestDouble(QML, store))
        assert not again.created and again.object_id == response.object_id
        stored = get_private_qml_receipt(
            ORG, FARM, PLOT, CAMPAIGN, "ndvi",
            RequestDouble(b"", store), Response(), FakeSession(), context(),
        )
        assert stored.sha256 == response.sha256 and stored.size_bytes == len(QML)
        assert not stored.scientific_validated and not stored.published

        different = RequestDouble(b"<qgis>MODIFICADO</qgis>", store)
        deny(lambda: upload(different), 409)
        with store.open_read(address) as original:
            assert original.read() == QML

        deny(lambda: upload(RequestDouble(QML, store), hash_value="a" * 64), 422)
        deny(lambda: upload(RequestDouble(QML, store), hash_value="A" * 64), 422)
        deny(lambda: upload(RequestDouble(QML, store), size=len(QML) + 1), 422)
        deny(lambda: upload(RequestDouble(QML, store), mime="text/xml"), 415)
        deny(lambda: upload(RequestDouble(b"", store)), 413)
        deny(lambda: upload(RequestDouble(b"x" * 17, store), size=16), 413)
        deny(lambda: upload(RequestDouble(b"x", store), size=MAX_QML_BYTES + 1), 413)
        deny(lambda: upload(RequestDouble(b"x" * (MAX_QML_BYTES + 1), store)), 413)

        forbidden = RequestDouble(QML, store)
        before = Reader.calls
        deny(lambda: upload(forbidden, ctx=context(DBIPermission.READ)), 404)
        assert forbidden.stream_calls == 0 and Reader.calls == before
        forbidden_org = RequestDouble(QML, store)
        deny(lambda: upload(forbidden_org, ctx=context(tenant="another")), 404)
        assert forbidden_org.stream_calls == 0

        for overrides in [
            {"analysis_type": "density"}, {"status": "APPROVED"},
            {"status": "PUBLISHED"}, {"approved_at": DATE},
            {"published_at": DATE}, {"organization_ref": "other"},
            {"campaign_id": UUID("91000000-0000-4000-8000-000000000099")},
        ]:
            Reader.current = snapshot(**overrides)
            invalid = RequestDouble(QML, store)
            deny(lambda: upload(invalid), 404)
            assert invalid.stream_calls == 0
            deny(lambda: get_private_qml_receipt(
                ORG, FARM, PLOT, CAMPAIGN, "ndvi",
                invalid, Response(), FakeSession(), context()), 404)
        Reader.current = snapshot()

        missing = RequestDouble(QML, None)
        deny(lambda: upload(missing), 503)
        assert missing.stream_calls == 0
        deny(lambda: get_private_qml_receipt(
            ORG, FARM, PLOT, CAMPAIGN, "ndre",
            RequestDouble(b"", store), Response(), FakeSession(), context()), 404)

        for index in ("ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"):
            other = upload(RequestDouble(QML, store), index=index)
            assert other.object_id != response.object_id
            assert not other.published
        assert address.object_key.startswith("tenants/")
        assert "/analysis-inputs/" in address.object_key
        assert "ndvi" not in address.object_key
        assert "org-ci" not in address.object_key

    with patch.dict(os.environ, {"DBI_SCIENTIFIC_QML_INTAKE_ENABLED": "0"}), patch(
        "app.api.v1.dbi_scientific_qml_private.DBICampaignReader", Reader
    ):
        off = RequestDouble(QML, store)
        deny(lambda: upload(off), 404)
        assert off.stream_calls == 0

    router_source = (ROOT / "apps/platform-web/backend/app/api/v1/__init__.py").read_text()
    assert 'if os.environ.get("DBI_SCIENTIFIC_QML_INTAKE_ENABLED") == "1"' in router_source
    assert "dbi_scientific_qml_private_router" in router_source
    endpoint_source = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_qml_private.py").read_text()
    assert "DBIPermission.MANAGE" in endpoint_source
    assert "session.commit(" not in endpoint_source
    assert "issue_temporary_access" not in endpoint_source
    assert "isinstance(provider, DBIS3ObjectStore)" in endpoint_source
    assert "published=True" not in endpoint_source
    print("H14/2E OK: seis QML privados, MANAGE, bytes intactos, SHA servidor, idempotencia, fail-closed.")


if __name__ == "__main__":
    run_tests()
