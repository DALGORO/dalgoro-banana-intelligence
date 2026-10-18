"""CI H14/2H-2A: siete reservas de TIFF sintéticas, inmutables y privadas."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-only-h14-slot-reservations")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import (  # noqa: E402
    CAMPAIGN, FARM, ORG, PLOT, DATE, Reader, FakeSession, context,
    fake_test_store, sample, snapshot, denied,
)
from app.api.v1.dbi_scientific_manifest_private import (  # noqa: E402
    PrivateScientificManifestSubmission, put_private_scientific_manifest,
)
from app.api.v1.dbi_scientific_raster_reservations import (  # noqa: E402
    PrivateRasterSlotRequest, _slot_address,
    read_private_raster_slot, reserve_private_raster_slot,
)
from app.api.v1.dbi_scientific_raster_preflight import _raster_address  # noqa: E402
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.storage_contracts import DBIStorageWriteRequest  # noqa: E402
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402

PAIRS = [
    ("rgb", "_"), ("scientific_cog", "ndvi"), ("scientific_cog", "ndre"),
    ("scientific_cog", "gndvi"), ("scientific_cog", "evi2"),
    ("scientific_cog", "ci_red_edge"), ("scientific_cog", "ci_green"),
]


def req(store):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        dbi_object_store=store,
    )))


def make_manifest(store):
    response = Response()
    result = put_private_scientific_manifest(
        ORG, FARM, PLOT, CAMPAIGN,
        PrivateScientificManifestSubmission.model_validate(sample()),
        req(store), response, FakeSession(), context(),
    )
    assert response.status_code == 201
    return result


def submit(store, digest, role="rgb", index="_", ctx=None):
    response = Response()
    result = reserve_private_raster_slot(
        ORG, FARM, PLOT, CAMPAIGN, role, index,
        PrivateRasterSlotRequest(
            schema_version="dbi-h14-raster-slot-request.v1",
            manifest_sha256=digest,
        ),
        req(store), response, FakeSession(), ctx or context(),
    )
    assert response.headers["Cache-Control"] == "no-store"
    return result, response


def read(store, role="rgb", index="_", ctx=None):
    response = Response()
    result = read_private_raster_slot(
        ORG, FARM, PLOT, CAMPAIGN, role, index,
        req(store), response, FakeSession(), ctx or context(),
    )
    assert response.headers["Cache-Control"] == "no-store"
    return result


def run_tests():
    store = DBIInMemoryObjectStore()
    with patch.dict(os.environ, {
        "DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED": "1",
        "DBI_SCIENTIFIC_MANIFEST_ENABLED": "1",
        "DBI_ENVIRONMENT": "test",
    }), patch(
        "app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader,
    ), patch(
        "app.api.v1.dbi_scientific_manifest_private._store", fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_reservations._private_store", fake_test_store,
    ):
        # Sin manifiesto, ni READ ni tenant ajeno pueden reservar.
        denied(lambda: read(store), 404)
        denied(lambda: submit(store, "a" * 64), 404)
        before = Reader.calls
        denied(lambda: submit(store, "a" * 64, ctx=context(DBIPermission.READ)), 404)
        assert Reader.calls == before
        denied(lambda: read(store, ctx=context(DBIPermission.READ)), 404)
        assert Reader.calls == before
        denied(lambda: submit(store, "a" * 64, ctx=context(tenant="another")), 404)
        manifest = make_manifest(store)
        digest = manifest.manifest_sha256
        assert len(digest) == 64

        denied(lambda: submit(store, "a" * 64), 409)
        denied(lambda: submit(store, digest, role="rgb", index="ndvi"), 422)
        denied(lambda: submit(store, digest, role="scientific_cog", index="_"), 422)
        denied(lambda: submit(store, digest, role="scientific_cog", index="invalid"), 422)
        denied(lambda: read(store, role="rgb", index="ndvi"), 422)

        for changes in (
            {"analysis_type": "density"}, {"status": "APPROVED"},
            {"status": "PUBLISHED"}, {"approved_at": DATE},
            {"published_at": DATE}, {"organization_ref": "another"},
            {"campaign_id": UUID("91000000-0000-4000-8000-000000000099")},
        ):
            Reader.current = snapshot(**changes)
            denied(lambda: submit(store, digest), 404)
            denied(lambda: read(store), 404)
        Reader.current = snapshot()

        saved = {}
        for role, index in PAIRS:
            receipt, http = submit(store, digest, role, index)
            assert http.status_code == 201
            assert receipt.created is True
            data = receipt.reservation
            assert data.state == "metadata_reserved_no_upload"
            assert data.manifest_sha256 == digest
            assert data.manifest_object_id == manifest.object_id
            assert data.reserved_by == "operator-ci"
            assert data.campaign_id == CAMPAIGN
            assert not any((
                data.asset_registered, data.session_initiated, data.grants_issued,
                data.raster_bytes_received, data.content_verified,
                data.institutional_approved, data.published,
            ))
            idx = None if index == "_" else index
            target = _raster_address(context(), ORG, FARM, PLOT, CAMPAIGN, role, idx)
            slot = _slot_address(context(), ORG, FARM, PLOT, CAMPAIGN, role, idx)
            assert slot.object_id != target.object_id
            assert data.target_object_id == target.object_id
            assert data.declared_sha256 == next(
                h.declared_sha256 for h in manifest.submission.declared_hashes
                if (h.role, h.index) == (role, idx)
            )
            assert data.declared_size_bytes == next(
                f.size_bytes for f in manifest.submission.draft.files
                if (f.role, f.index) == (role, idx)
            )
            assert ORG not in slot.object_key
            assert slot.object_id == receipt.reservation_object_id
            assert len(receipt.reservation_sha256) == 64
            with store.open_read(slot) as stream:
                source = stream.read()
            assert receipt.reservation_sha256 == sha256(source).hexdigest()
            saved[(role, index)] = source
            again, repeat_http = submit(store, digest, role, index)
            assert repeat_http.status_code == 200
            assert not again.created
            assert again.reservation_sha256 == receipt.reservation_sha256
            other = read(store, role, index, ctx=context(actor="reviewer-ci"))
            assert other.created is False and other.reservation.reserved_by == "operator-ci"
            assert other.reservation_sha256 == receipt.reservation_sha256

        assert len(set(saved.values())) == 7
        # Operador diferente NO puede sobrescribir la evidencia del primero.
        denied(lambda: submit(store, digest, ctx=context(actor="different-operator")), 409)
        first_slot = _slot_address(context(), ORG, FARM, PLOT, CAMPAIGN, "rgb", None)
        with store.open_read(first_slot) as stream:
            assert stream.read() == saved[("rgb", "_")]

        # Si un TIFF aparece sin flujo explícito, no se reserva encima.
        target = _raster_address(context(), ORG, FARM, PLOT, CAMPAIGN, "rgb", None)
        raw = b"tiny synthetic raster marker"
        meta = DBIStoragePolicy.build_metadata(
            address=target, content_type="image/tiff",
            size_bytes=len(raw), sha256_hex=sha256(raw).hexdigest(),
        )
        store.put(DBIStorageWriteRequest(metadata=meta), BytesIO(raw))
        denied(lambda: submit(store, digest), 409)
        # Comprobar integridad: corrupción en JSON recibido siempre es error.
        real_open = store.open_read

        @contextmanager
        def corrupt(address):
            if address == first_slot:
                with BytesIO(b"tampered") as stream:
                    yield stream
            else:
                with real_open(address) as stream:
                    yield stream

        with patch.object(store, "open_read", corrupt):
            denied(lambda: read(store), 503)

        # Proveedor real ausente -> indisponible y no fallback local.
        denied(lambda: submit(None, digest), 503)
        denied(lambda: read(None), 503)

    from app.api.v1 import get_api_router
    fragment = "/scientific-intake/private-raster-slots/"
    for env, register in (
        ("production", False), ("staging", False), ("", False),
        ("test", True), ("development", True), ("local", True),
    ):
        with patch.dict(os.environ, {
            "DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED": "1",
            "DBI_ENVIRONMENT": env,
        }):
            included = any(fragment in route.path for route in get_api_router().routes)
            assert included is register, (env, included)
            if not register:
                denied(lambda: submit(store, digest), 404)
    with patch.dict(os.environ, {
        "DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED": "0",
        "DBI_ENVIRONMENT": "test",
    }):
        denied(lambda: read(store), 404)

    from app.api.v1.dbi_scientific_manifest_private import _store as production_store
    denied(lambda: production_store(req(store)), 503)
    text = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_reservations.py").read_text()
    assert "issue_temporary_access" not in text
    assert "issue_part_access" not in text
    assert "session.commit(" not in text
    assert "generate_presigned" not in text
    assert "published=True" not in text
    print("H14/2H-2A OK: siete reservas S3 inmutables; Campaign/manifest/actor scoped; cero sesiones/grants.")


if __name__ == "__main__":
    run_tests()
