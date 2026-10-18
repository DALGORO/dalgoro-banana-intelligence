"""CI H14: un QML real sintético en storage privado, sin DB, red o publicación."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID
import sys

from fastapi import HTTPException, Response
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-only-h14-qml")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from app.api.v1.dbi_scientific_qml import receive_private_scientific_qml  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.campaigns.contracts import DBICampaignSnapshot  # noqa: E402
from app.dbi.scientific_qml_receipt import (  # noqa: E402
    QML_MAX_BYTES, ScientificQMLIntakeItem, plan_scientific_qml_private_receipt,
)
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402

FARM = UUID("93000000-0000-4000-8000-000000000001")
PLOT = UUID("93000000-0000-4000-8000-000000000002")
CAMPAIGN = UUID("93000000-0000-4000-8000-000000000003")
TENANT = "tenant-ci-qml"
ORG = "org-ci-qml"
DATE = datetime(2026, 10, 18, 15, 30, tzinfo=timezone.utc)
BODY = b'<qgis version="3.34"><pipe/></qgis>'
PATH = "MULTI/NDVI.qml"


def snapshot(**kwargs):
    data = {
        "campaign_id": CAMPAIGN, "tenant_ref": TENANT, "organization_ref": ORG,
        "farm_id": FARM, "plot_id": PLOT, "analysis_type": "multispectral",
        "captured_at": DATE, "status": "TECHNICAL_REVIEW",
        "processed_at": None, "created_at": DATE, "updated_at": DATE,
        "reviewed_at": None, "field_started_at": None,
        "field_completed_at": None, "approved_at": None, "published_at": None,
        "current_revision_id": None, "source_job_id": None,
    }
    data.update(kwargs)
    return DBICampaignSnapshot.model_validate(data)


def context(permission=DBIPermission.MANAGE):
    return DBIAccessContext(
        principal_ref="operator-ci", tenant_ref=TENANT,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset({DBIFarmScope(ORG, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORG, FARM, PLOT)}),
        permissions=frozenset({permission}),
    )


class InputRequest:
    def __init__(self, data=BODY, store=None, *, headers=None, chunks=None):
        self.data = data
        self.headers = {
            "content-type": "text/plain",
            "content-length": str(len(data)),
            **(headers or {}),
        }
        self.app = SimpleNamespace(state=SimpleNamespace(dbi_object_store=store))
        self.read_started = False
        self.chunks = chunks

    async def stream(self):
        self.read_started = True
        if self.chunks is not None:
            for piece in self.chunks:
                yield piece
        else:
            yield self.data


async def send(request, *, permission=DBIPermission.MANAGE,
               index="ndvi", path=PATH, claim=None, size=None, campaign=None):
    response = Response()
    result = await receive_private_scientific_qml(
        ORG, FARM, PLOT, CAMPAIGN, index, request, response,
        object(), context(permission), path,
        claim if claim is not None else sha256(request.data).hexdigest(),
        size if size is not None else len(request.data),
    )
    return result, response


def expect_http(code, request, **kwargs):
    try:
        asyncio.run(send(request, **kwargs))
    except HTTPException as error:
        assert error.status_code == code, (error.status_code, error.detail)
        return
    raise AssertionError(f"Debió rechazar HTTP {code}")


def main() -> None:
    store = DBIInMemoryObjectStore()
    read_calls = []

    class Reader:
        campaign = snapshot()

        def __init__(self, session):
            pass

        def read_campaign(self, **kwargs):
            read_calls.append(kwargs)
            return self.campaign

    with patch("app.api.v1.dbi_scientific_qml.DBICampaignReader", Reader):
        # La rama exige opt-in incluso cuando la persona posee MANAGE.
        with patch.dict(os.environ, {"DBI_SCIENTIFIC_QML_INTAKE_ENABLED": "0", "DBI_ENVIRONMENT": "test"}):
            req = InputRequest(store=store)
            expect_http(503, req)
            assert not req.read_started

        with patch.dict(os.environ, {"DBI_SCIENTIFIC_QML_INTAKE_ENABLED": "1", "DBI_ENVIRONMENT": "production"}):
            req = InputRequest(store=store)
            expect_http(503, req)
            assert not req.read_started

        with patch.dict(os.environ, {"DBI_SCIENTIFIC_QML_INTAKE_ENABLED": "1", "DBI_ENVIRONMENT": "test"}):
            read_calls.clear()
            req = InputRequest(store=store)
            expect_http(404, req, permission=DBIPermission.READ)
            assert not req.read_started and not read_calls

            Reader.campaign = snapshot(status="PUBLISHED")
            req = InputRequest(store=store)
            expect_http(404, req)
            assert not req.read_started
            Reader.campaign = snapshot(approved_at=DATE)
            expect_http(404, InputRequest(store=store))
            Reader.campaign = snapshot(organization_ref="foreign-org")
            expect_http(404, InputRequest(store=store))
            Reader.campaign = snapshot(analysis_type="density")
            expect_http(404, InputRequest(store=store))
            Reader.campaign = snapshot()

            for bad in ("../NDVI.qml", "MULTI/../NDVI.qml", "MULTI/NDVI.tif", "MULTI\\NDVI.qml"):
                expect_http(422, InputRequest(store=store), path=bad)
            expect_http(422, InputRequest(store=store), index="unapproved")
            expect_http(422, InputRequest(store=store), size=QML_MAX_BYTES + 1)
            expect_http(422, InputRequest(store=store), claim="A" * 64)
            expect_http(415, InputRequest(store=store, headers={"content-type": "application/xml"}))
            expect_http(415, InputRequest(store=store, headers={"content-encoding": "gzip"}))
            expect_http(409, InputRequest(store=store, headers={"content-length": "1"}))
            expect_http(409, InputRequest(store=store), claim="0" * 64)
            expect_http(409, InputRequest(store=store), size=len(BODY) + 1)
            expect_http(413, InputRequest(store=store, chunks=[BODY, b"x"]))
            expect_http(503, InputRequest(store=None))

            req = InputRequest(store=store, chunks=[BODY[:5], BODY[5:]])
            receipt, response = asyncio.run(send(req))
            assert receipt.created and response.status_code == 201
            assert response.headers["Cache-Control"] == "private, no-store"
            assert receipt.transport_hash_verified and receipt.bundle_complete is False
            assert not any((receipt.scientific_validated, receipt.institutional_approved, receipt.published))
            assert "url" not in receipt.model_dump() and "object_key" not in receipt.model_dump()
            item = ScientificQMLIntakeItem.model_validate({
                "index": "ndvi", "relative_path": PATH,
                "size_bytes": len(BODY), "sha256": sha256(BODY).hexdigest(),
            })
            plan = plan_scientific_qml_private_receipt(
                tenant_ref=TENANT, organization_ref=ORG, farm_id=FARM,
                plot_id=PLOT, campaign_id=CAMPAIGN, item=item,
            )
            assert plan.metadata.address.object_id == receipt.object_id
            with store.open_read(plan.metadata.address) as f:
                assert f.read() == BODY, "La fuente QML debe conservarse byte a byte."
            receipt_again, response_again = asyncio.run(send(InputRequest(store=store)))
            assert receipt_again.created is False and response_again.status_code == 200
            assert receipt_again.object_id == receipt.object_id

            new_bytes = b'<qgis version="3.34"><pipe><x/></pipe></qgis>'
            distinct, _ = asyncio.run(send(InputRequest(data=new_bytes, store=store)))
            assert distinct.object_id != receipt.object_id
            with store.open_read(plan.metadata.address) as f:
                assert f.read() == BODY, "Una revisión QML no puede sobrescribir el original."
            assert plan_scientific_qml_private_receipt(
                tenant_ref="other-tenant", organization_ref=ORG, farm_id=FARM,
                plot_id=PLOT, campaign_id=CAMPAIGN, item=item,
            ).metadata.address.object_key != plan.metadata.address.object_key

    endpoint = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_qml.py").read_text(encoding="utf-8")
    assert "permission=DBIPermission.MANAGE" in endpoint
    assert "session.commit(" not in endpoint
    assert "published=True" not in endpoint
    assert "DBI_SCIENTIFIC_QML_INTAKE_ENABLED" in endpoint
    router = (ROOT / "apps/platform-web/backend/app/api/v1/__init__.py").read_text(encoding="utf-8")
    assert "api.include_router(dbi_scientific_qml_router)" in router
    print("H14 OK: original QML byte-exacto, MANAGE, SHA, idempotencia, privacidad y deny-by-default.")


if __name__ == "__main__":
    main()
