"""H14/2G: CI offline de conciliación 6 QML con manifiesto privado H14/2F."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-only-h14-qml-reconciliation")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import (  # noqa: E402
    CAMPAIGN, FARM, ORG, PLOT, TENANT, DATE, INDEXES, Reader, FakeSession,
    context, fake_test_store, sample, snapshot, denied,
)
from app.api.v1.dbi_scientific_manifest_private import (  # noqa: E402
    PrivateScientificManifestSubmission, put_private_scientific_manifest,
    _address as manifest_address,
)
from app.api.v1.dbi_scientific_qml_reconciliation import (  # noqa: E402
    _qml_address, _store, get_private_qml_reconciliation,
)
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.storage_contracts import DBIStoragePurpose, DBIStorageWriteRequest  # noqa: E402
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402

# Un solo contenido sintético por índice; nunca se toca material del usuario.
SAMPLES = {index: ("<qgis index='" + index + "'/>").encode() for index in INDEXES}


def fixture_payload():
    data = sample()
    for file in data["draft"]["files"]:
        if file["role"] == "qml_style":
            file["size_bytes"] = len(SAMPLES[file["index"]])
    for digest in data["declared_hashes"]:
        if digest["role"] == "qml_style":
            digest["declared_sha256"] = sha256(SAMPLES[digest["index"]]).hexdigest()
    return PrivateScientificManifestSubmission.model_validate(data)


def req(store):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        dbi_object_store=store,
    )))


def make_manifest(store, payload=None):
    response = Response()
    result = put_private_scientific_manifest(
        ORG, FARM, PLOT, CAMPAIGN,
        payload or fixture_payload(), req(store), response,
        FakeSession(), context(),
    )
    assert response.status_code in (200, 201)
    return result


def report(store, ctx=None):
    response = Response()
    result = get_private_qml_reconciliation(
        ORG, FARM, PLOT, CAMPAIGN, req(store), response,
        FakeSession(), ctx or context(),
    )
    assert response.headers["Cache-Control"] == "no-store"
    return result


def upload_qml(store, index, content):
    address = _qml_address(context(), ORG, FARM, PLOT, CAMPAIGN, index)
    metadata = DBIStoragePolicy.build_metadata(
        address=address, content_type="application/octet-stream",
        size_bytes=len(content), sha256_hex=sha256(content).hexdigest(),
    )
    result = store.put(
        DBIStorageWriteRequest(metadata=metadata), BytesIO(content),
    )
    assert result.created
    return address


def check_states(report_value, *, matched, missing, mismatch):
    assert len(report_value.qml_results) == 6
    assert len({item.index for item in report_value.qml_results}) == 6
    assert report_value.matched_count == matched
    assert report_value.missing_count == missing
    assert report_value.mismatch_count == mismatch
    assert report_value.all_six_qml_match_manifest is (matched == 6)
    assert not any((
        report_value.all_thirteen_files_received,
        report_value.scientific_validated,
        report_value.institutional_approved, report_value.published,
    ))
    assert all(item.relative_path.startswith("MULTI/") for item in report_value.qml_results)


def run_tests():
    store = DBIInMemoryObjectStore()
    denied(lambda: _store(req(store)), 503)
    denied(lambda: _store(req(None)), 503)

    # Mismo espacio UUIDv5/objeto S3 que H14/2E, sin importar router pendiente.
    expected_id = uuid5(
        NAMESPACE_URL,
        "dalgoro-dbi:h14:private-original-qml:v1:"
        + "|".join((TENANT, ORG, str(FARM), str(PLOT), str(CAMPAIGN), "ndvi")),
    )
    assert _qml_address(context(), ORG, FARM, PLOT, CAMPAIGN, "ndvi").object_id == expected_id
    assert _qml_address(context(), ORG, FARM, PLOT, CAMPAIGN, "ndvi").purpose == DBIStoragePurpose.ANALYSIS_INPUT
    assert _qml_address(context(), ORG, FARM, PLOT, CAMPAIGN, "ndvi") != manifest_address(
        context(), ORG, FARM, PLOT, CAMPAIGN,
    )

    with patch.dict(os.environ, {
        "DBI_SCIENTIFIC_MANIFEST_ENABLED": "1",
        "DBI_SCIENTIFIC_QML_RECONCILIATION_ENABLED": "1",
        "DBI_ENVIRONMENT": "test",
    }), patch(
        "app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader,
    ), patch(
        "app.api.v1.dbi_scientific_manifest_private._store", fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_qml_reconciliation._store", fake_test_store,
    ):
        # No manifesto no es un resultado completo "faltan seis".
        denied(lambda: report(store), 404)
        first = make_manifest(store)
        assert first.submitted_by == "operator-ci"

        empty = report(store)
        check_states(empty, matched=0, missing=6, mismatch=0)
        assert all(item.observed_size_bytes is None for item in empty.qml_results)
        assert all(item.verified_sha256 is None for item in empty.qml_results)

        upload_qml(store, "ndvi", SAMPLES["ndvi"])
        upload_qml(store, "ndre", b"x" * len(SAMPLES["ndre"]))
        upload_qml(store, "gndvi", b"y" * (len(SAMPLES["gndvi"]) + 1))
        partial = report(store)
        check_states(partial, matched=1, missing=3, mismatch=2)
        states = {x.index: x.state for x in partial.qml_results}
        assert states["ndvi"] == "matched"
        assert states["ndre"] == "sha256_mismatch"
        assert states["gndvi"] == "size_mismatch"
        assert states["evi2"] == "missing"
        assert partial.manifest_sha256 == first.manifest_sha256

        # READ y tenant ajeno jamás entran al almacén: MANAGE precede I/O.
        calls = Reader.calls
        denied(lambda: report(store, context(DBIPermission.READ)), 404)
        assert Reader.calls == calls
        denied(lambda: report(store, context(tenant="another")), 404)

        for changes in (
            {"analysis_type": "density"}, {"status": "APPROVED"},
            {"status": "PUBLISHED"}, {"approved_at": DATE},
            {"published_at": DATE}, {"organization_ref": "other"},
        ):
            Reader.current = snapshot(**changes)
            denied(lambda: report(store), 404)
        Reader.current = snapshot()

        denied(lambda: report(None), 503)
        # Segundo experimento independiente: seis bytes QML exactos, sin aprobar.
        all_store = DBIInMemoryObjectStore()
        make_manifest(all_store)
        for index in INDEXES:
            upload_qml(all_store, index, SAMPLES[index])
        full = report(all_store)
        check_states(full, matched=6, missing=0, mismatch=0)
        assert all(item.declared_sha256 == item.verified_sha256 for item in full.qml_results)

        # Objeto inalterado en HEAD pero lectura corrupta: NUNCA declarar matched.
        original_read = all_store.open_read
        expected = _qml_address(context(), ORG, FARM, PLOT, CAMPAIGN, "ndvi")

        @contextmanager
        def tampered_read(address):
            if address == expected:
                with BytesIO(b"tampered") as stream:
                    yield stream
            else:
                with original_read(address) as stream:
                    yield stream

        with patch.object(all_store, "open_read", tampered_read):
            denied(lambda: report(all_store), 503)

        # Metadatos fuera de cuota o MIME erróneo: error, no "mismatch" benigno.
        original_stat = all_store.stat

        def tampered_stat(address):
            record = original_stat(address)
            if address == expected:
                meta = replace(record.metadata, content_type="application/xml")
                return replace(record, metadata=meta)
            return record

        with patch.object(all_store, "stat", tampered_stat):
            denied(lambda: report(all_store), 503)

    with patch.dict(os.environ, {
        "DBI_SCIENTIFIC_QML_RECONCILIATION_ENABLED": "0",
        "DBI_ENVIRONMENT": "test",
    }), patch(
        "app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader,
    ):
        denied(lambda: report(store), 404)

    # Flag solo NO abre la conciliación en production o staging.
    with patch("app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader):
        for environment in ("production", "staging", ""):
            with patch.dict(os.environ, {
                "DBI_SCIENTIFIC_QML_RECONCILIATION_ENABLED": "1",
                "DBI_ENVIRONMENT": environment,
            }):
                denied(lambda: report(store), 404)

    from app.api.v1 import get_api_router
    route_fragment = "/scientific-intake/private-qml-reconciliation"
    for environment, enabled in (("production", False), ("staging", False), ("test", True)):
        with patch.dict(os.environ, {
            "DBI_SCIENTIFIC_QML_RECONCILIATION_ENABLED": "1",
            "DBI_ENVIRONMENT": environment,
        }):
            found = any(route_fragment in item.path for item in get_api_router().routes)
            assert found is enabled, (environment, found)

    source = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_qml_reconciliation.py").read_text()
    assert "issue_temporary_access" not in source
    assert "session.commit(" not in source
    assert "published=True" not in source
    assert "store.open_read(address)" in source
    assert "isinstance(store, DBIS3ObjectStore)" in source

    print("H14/2G OK: conciliación exacta de seis QML privada y read-only; no aprobación ni publicación.")


if __name__ == "__main__":
    run_tests()
