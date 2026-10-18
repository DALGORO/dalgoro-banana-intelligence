"""CI H14/2F: manifiesto inmutable de 13 originales, metadata sintética y sin red."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException, Response
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-only-h14-private-manifest")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from app.api.v1.dbi_scientific_manifest_private import (  # noqa: E402
    MAX_QML_BYTES, MAX_RASTER_BYTES, MAX_BUNDLE_BYTES, _address, _store,
    PrivateScientificManifestSubmission, get_private_scientific_manifest,
    put_private_scientific_manifest,
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
INDEXES = ("ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green")


def sample() -> dict:
    files = [{
        "folder": "geospatial", "role": "rgb", "index": None,
        "relative_path": "GEO/ortho_RGB.tif", "size_bytes": 123456,
        "sha256": None, "file_content_verified": False,
    }]
    for index in INDEXES:
        for role, ext in (("scientific_cog", ".cog.tif"), ("qml_style", ".qml")):
            files.append({
                "folder": "multispectral", "role": role, "index": index,
                "relative_path": f"MULTI/{index}{ext}", "size_bytes": 512,
                "sha256": None, "file_content_verified": False,
            })
    hashes = [{
        "role": file["role"], "index": file["index"],
        "declared_sha256": sha256(file["relative_path"].encode()).hexdigest(),
    } for file in files]
    return {
        "schema_version": "dbi-h14-private-manifest-submission.v1",
        "source": "local_two_folders_unverified",
        "draft": {
            "schema_version": "dbi-h14-scientific-reception-draft.v1",
            "state": "local_metadata_only_not_uploaded",
            "scope": {
                "tenant_ref": TENANT, "organization_ref": ORG,
                "farm_id": str(FARM), "plot_id": str(PLOT),
                "campaign_id": str(CAMPAIGN),
            },
            "folders": {"geospatial": "GEO", "multispectral": "MULTI"},
            "files": files, "blockers": [], "structural_ready": True,
            "scientific_validated": False, "server_received": False,
            "institutional_approved": False, "published": False,
        },
        "declared_hashes": hashes,
    }


def snapshot(**changes):
    value = {
        "campaign_id": CAMPAIGN, "tenant_ref": TENANT, "organization_ref": ORG,
        "farm_id": FARM, "plot_id": PLOT, "analysis_type": "multispectral",
        "captured_at": DATE, "status": "TECHNICAL_REVIEW",
        "processed_at": None, "created_at": DATE, "updated_at": DATE,
        "reviewed_at": None, "field_started_at": None, "field_completed_at": None,
        "approved_at": None, "published_at": None,
        "current_revision_id": None, "source_job_id": None,
    }
    value.update(changes)
    return DBICampaignSnapshot.model_validate(value)


def context(permission=DBIPermission.MANAGE, *, tenant=TENANT, actor="operator-ci"):
    return DBIAccessContext(
        principal_ref=actor, tenant_ref=tenant,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset({DBIFarmScope(ORG, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORG, FARM, PLOT)}),
        permissions=frozenset({permission}),
    )


class FakeSession:
    def commit(self):
        raise AssertionError("Prohibida mutación SQL.")

    def add(self, *_):
        raise AssertionError("Prohibida mutación SQL.")


class Reader:
    current = snapshot()
    calls = 0

    def __init__(self, session):
        assert isinstance(session, FakeSession)

    def read_campaign(self, **kwargs):
        Reader.calls += 1
        assert kwargs == {
            "campaign_id": CAMPAIGN, "tenant_ref": kwargs["tenant_ref"],
            "organization_ref": ORG, "farm_id": FARM, "plot_id": PLOT,
        }
        return Reader.current


def request(store):
    return SimpleNamespace(app=SimpleNamespace(
        state=SimpleNamespace(dbi_object_store=store),
    ))


def fake_test_store(req):
    store = req.app.state.dbi_object_store
    if store is None:
        raise HTTPException(503, "CI: sin proveedor privado.")
    return store


def put(store, payload=None, ctx=None):
    response = Response()
    value = put_private_scientific_manifest(
        ORG, FARM, PLOT, CAMPAIGN,
        payload or PrivateScientificManifestSubmission.model_validate(sample()),
        request(store), response, FakeSession(), ctx or context(),
    )
    return value, response


def get(store, ctx=None):
    response = Response()
    value = get_private_scientific_manifest(
        ORG, FARM, PLOT, CAMPAIGN, request(store), response,
        FakeSession(), ctx or context(),
    )
    return value, response


def denied(call, status):
    try:
        call()
    except HTTPException as error:
        assert error.status_code == status, (status, error.status_code, error.detail)
    else:
        raise AssertionError(f"Operación indebida admitida, esperado HTTP {status}.")


def invalid(label, mutate):
    doc = sample()
    mutate(doc)
    try:
        PrivateScientificManifestSubmission.model_validate(doc)
    except ValidationError:
        pass
    else:
        raise AssertionError(f"Debía rechazar el contrato: {label}")


def run():
    valid = PrivateScientificManifestSubmission.model_validate(sample())
    assert len(valid.declared_hashes) == len(valid.draft.files) == 13
    assert MAX_QML_BYTES == 2 * 1024 * 1024
    assert MAX_RASTER_BYTES == 10 * 1024 ** 3
    assert MAX_BUNDLE_BYTES == 60 * 1024 ** 3
    for label, mutate in [
        ("hash mayúsculas", lambda p: p["declared_hashes"][0].update(declared_sha256="A" * 64)),
        ("hash inventado largo", lambda p: p["declared_hashes"][0].update(declared_sha256="x" * 64)),
        ("duplicado", lambda p: p["declared_hashes"][1].update(role="rgb", index=None)),
        ("faltante", lambda p: p["declared_hashes"].pop()),
        ("QML grande", lambda p: p["draft"]["files"][2].update(size_bytes=MAX_QML_BYTES + 1)),
        ("ráster grande", lambda p: p["draft"]["files"][0].update(size_bytes=MAX_RASTER_BYTES + 1)),
        ("cuota total", lambda p: [f.update(size_bytes=MAX_RASTER_BYTES) for f in p["draft"]["files"] if f["role"] != "qml_style"]),
        ("escape directorio", lambda p: p["draft"]["files"][0].update(relative_path="GEO/../escape.tif")),
        ("falseamiento verificación", lambda p: p["draft"]["files"][0].update(file_content_verified=True)),
        ("falseamiento publicación", lambda p: p["draft"].update(published=True)),
        ("campo ajeno", lambda p: p.update(external_bucket="secret")),
    ]:
        invalid(label, mutate)

    store = DBIInMemoryObjectStore()
    # El adaptador de prueba jamás se admite en producción.
    denied(lambda: _store(request(store)), 503)
    denied(lambda: _store(request(None)), 503)

    with patch.dict(os.environ, {"DBI_SCIENTIFIC_MANIFEST_ENABLED": "1", "DBI_ENVIRONMENT": "test"}), patch(
        "app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader
    ), patch("app.api.v1.dbi_scientific_manifest_private._store", fake_test_store):
        before = Reader.calls
        denied(lambda: put(store, ctx=context(DBIPermission.READ)), 404)
        assert Reader.calls == before, "READ no puede ni consultar Campaign."
        denied(lambda: get(store, ctx=context(DBIPermission.READ)), 404)
        assert Reader.calls == before

        denied(lambda: put(store, ctx=context(tenant="other")), 404)
        forged = sample()
        forged["draft"]["scope"]["campaign_id"] = str(
            UUID("91000000-0000-4000-8000-000000000099")
        )
        denied(lambda: put(
            store, PrivateScientificManifestSubmission.model_validate(forged),
        ), 404)

        for changes in (
            {"analysis_type": "density"}, {"status": "APPROVED"},
            {"status": "PUBLISHED"}, {"approved_at": DATE},
            {"published_at": DATE}, {"organization_ref": "other"},
            {"campaign_id": UUID("91000000-0000-4000-8000-000000000099")},
        ):
            Reader.current = snapshot(**changes)
            denied(lambda: put(store), 404)
            denied(lambda: get(store), 404)
        Reader.current = snapshot()

        denied(lambda: get(store), 404)
        receipt, response = put(store)
        assert response.status_code == 201
        assert response.headers["Cache-Control"] == "no-store"
        assert receipt.created and receipt.file_count == 13
        assert receipt.total_declared_bytes == 123456 + 12 * 512
        assert receipt.submitted_by == "operator-ci"
        assert receipt.manifest_received_privately
        assert not any((
            receipt.file_bytes_received, receipt.file_hashes_verified,
            receipt.scientific_validated, receipt.institutional_approved,
            receipt.published,
        ))
        address = _address(context(), ORG, FARM, PLOT, CAMPAIGN)
        assert address.object_id == receipt.object_id
        assert "/analysis-inputs/" in address.object_key
        assert ORG not in address.object_key
        with store.open_read(address) as data:
            original = data.read()
        parsed = json.loads(original)
        assert parsed["submitted_by"] == "operator-ci"
        assert parsed["file_bytes_received"] is False
        assert parsed["file_hashes_verified"] is False
        assert len(parsed["submission"]["draft"]["files"]) == 13
        assert sha256(original).hexdigest() == receipt.manifest_sha256

        again, again_response = put(store)
        assert again_response.status_code == 200 and not again.created
        assert again.manifest_sha256 == receipt.manifest_sha256
        ordered = sample()
        ordered["draft"]["files"].reverse()
        ordered["declared_hashes"].reverse()
        reordered, _ = put(
            store, PrivateScientificManifestSubmission.model_validate(ordered),
        )
        assert not reordered.created, "Orden de listas no debe crear conflicto."

        restored, restored_response = get(store)
        assert restored_response.headers["Cache-Control"] == "no-store"
        assert restored.manifest_sha256 == receipt.manifest_sha256
        assert restored.submission == receipt.submission
        assert restored.created_at == receipt.created_at
        assert restored.created is False

        changed = sample()
        changed["declared_hashes"][0]["declared_sha256"] = "b" * 64
        denied(lambda: put(
            store, PrivateScientificManifestSubmission.model_validate(changed),
        ), 409)
        denied(lambda: put(store, ctx=context(actor="other-operator")), 409)
        with store.open_read(address) as data:
            assert data.read() == original, "El original inmutable fue alterado."

        denied(lambda: put(None), 503)
        assert "org-ci" not in address.object_key

    with patch.dict(os.environ, {"DBI_SCIENTIFIC_MANIFEST_ENABLED": "0"}), patch(
        "app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader
    ), patch("app.api.v1.dbi_scientific_manifest_private._store", fake_test_store):
        before = Reader.calls
        denied(lambda: put(store), 404)
        denied(lambda: get(store), 404)
        assert Reader.calls == before

    with patch("app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader):
        for environment in ("production", "staging", ""):
            with patch.dict(os.environ, {
                "DBI_SCIENTIFIC_MANIFEST_ENABLED": "1",
                "DBI_ENVIRONMENT": environment,
            }):
                before = Reader.calls
                denied(lambda: put(store), 404)
                denied(lambda: get(store), 404)
                assert Reader.calls == before, "Un entorno prohibido no consulta Campaign."

    from app.api.v1 import get_api_router
    for environment, present in (("production", False), ("staging", False), ("test", True)):
        with patch.dict(os.environ, {
            "DBI_SCIENTIFIC_MANIFEST_ENABLED": "1",
            "DBI_ENVIRONMENT": environment,
        }):
            registered = any("/scientific-intake/private-manifest" in route.path
                             for route in get_api_router().routes)
            assert registered is present, (environment, registered)

    api_source = (ROOT / "apps/platform-web/backend/app/api/v1/__init__.py").read_text()
    assert 'os.environ.get("DBI_SCIENTIFIC_MANIFEST_ENABLED") == "1"' in api_source
    assert 'os.environ.get("DBI_ENVIRONMENT", "").strip().lower()' in api_source
    endpoint = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_manifest_private.py").read_text()
    assert "isinstance(provider, DBIS3ObjectStore)" in endpoint
    assert "session.commit(" not in endpoint
    assert "issue_temporary_access" not in endpoint
    assert "published=True" not in endpoint
    print("H14/2F OK: 13 huellas declaradas, manifiesto JSON privado verificable, MANAGE scoped, sin bytes ni publicación.")


if __name__ == "__main__":
    run()
