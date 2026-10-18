"""CI H14/2H: siete planes raster sin sesión, transferencia, grants ni S3 real."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
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
os.environ.setdefault("JWT_SECRET", "ci-only-h14-raster-preflight")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import (  # noqa: E402
    CAMPAIGN, FARM, ORG, PLOT, TENANT, DATE, Reader, FakeSession,
    context, fake_test_store, sample, snapshot, denied,
)
from app.api.v1.dbi_scientific_manifest_private import (  # noqa: E402
    PrivateScientificManifestSubmission, put_private_scientific_manifest,
)
from app.api.v1.dbi_scientific_raster_preflight import (  # noqa: E402
    _raster_address, get_private_raster_multipart_preflight,
)
from app.dbi.asset_multipart_contracts import (  # noqa: E402
    DBIMultipartChecksumAlgorithm, DBIMultipartChecksumType,
    DBIMultipartRoutingDecision,
)
from app.dbi.asset_multipart_policy import (  # noqa: E402
    DBI_MULTIPART_DEFAULT_LIMITS,
)
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402

MIB = 1024 * 1024


def request(store):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        dbi_object_store=store,
    )))


def upload_manifest(store, payload=None):
    response = Response()
    result = put_private_scientific_manifest(
        ORG, FARM, PLOT, CAMPAIGN,
        payload or PrivateScientificManifestSubmission.model_validate(sample()),
        request(store), response, FakeSession(), context(),
    )
    assert response.status_code == 201
    return result


def query(store, ctx=None):
    response = Response()
    result = get_private_raster_multipart_preflight(
        ORG, FARM, PLOT, CAMPAIGN,
        request(store), response, FakeSession(), ctx or context(),
    )
    assert response.headers["Cache-Control"] == "no-store"
    return result


def flags_off(result):
    assert result.raster_count == len(result.raster_plans) == 7
    assert len({(x.role, x.index) for x in result.raster_plans}) == 7
    assert not any((
        result.ready_for_upload, result.sessions_created, result.grants_issued,
        result.raster_bytes_received, result.raster_content_verified,
        result.scientific_validated, result.institutional_approved, result.published,
    ))
    for x in result.raster_plans:
        assert x.content_type == "image/tiff"
        assert x.transport_checksum_algorithm == DBIMultipartChecksumAlgorithm.SHA256
        assert x.transport_checksum_type == DBIMultipartChecksumType.COMPOSITE
        assert not x.transport_sha256_is_full_object_sha256
        assert not x.upload_initiated and not x.content_sha256_verified
        assert len(x.declared_sha256) == 64
        assert x.relative_path.startswith("GEO/" if x.role == "rgb" else "MULTI/")


def run_tests():
    base = DBIInMemoryObjectStore()
    with patch.dict(os.environ, {
        "DBI_SCIENTIFIC_MANIFEST_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_PREFLIGHT_ENABLED": "1",
        "DBI_ENVIRONMENT": "test",
    }), patch(
        "app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader,
    ), patch(
        "app.api.v1.dbi_scientific_manifest_private._store", fake_test_store,
    ):
        # Un manifiesto faltante no autoriza un upload especulativo.
        denied(lambda: query(base), 404)
        before = Reader.calls
        denied(lambda: query(base, context(DBIPermission.READ)), 404)
        assert Reader.calls == before
        denied(lambda: query(base, context(tenant="another")), 404)

        manifest_receipt = upload_manifest(base)
        # Toda lectura del preflight es inmutable: el primer PUT solo guardó el JSON.
        with patch.object(base, "put", side_effect=AssertionError("Se intentó escribir en S3.")):
            response = query(base)
        flags_off(response)
        assert response.manifest_sha256 == manifest_receipt.manifest_sha256
        assert response.manifest_object_id == manifest_receipt.object_id
        assert response.total_declared_raster_bytes == 123456 + 6 * 512
        assert [(x.role, x.index) for x in response.raster_plans] == [
            ("rgb", None), ("scientific_cog", "ndvi"),
            ("scientific_cog", "ndre"), ("scientific_cog", "gndvi"),
            ("scientific_cog", "evi2"), ("scientific_cog", "ci_red_edge"),
            ("scientific_cog", "ci_green"),
        ]
        assert all(x.routing == DBIMultipartRoutingDecision.SYNCHRONOUS for x in response.raster_plans)
        assert all(x.part_count == 0 and x.part_size_bytes is None for x in response.raster_plans)

        # Las identidades no contienen paths, nombres ni datos de la organización.
        keys = [_raster_address(
            context(), ORG, FARM, PLOT, CAMPAIGN, p.role, p.index,
        ) for p in response.raster_plans]
        assert len(set(k.object_id for k in keys)) == 7
        assert all(k.purpose.value == "analysis-inputs" for k in keys)
        assert all(ORG not in k.object_key and "ortho_RGB" not in k.object_key for k in keys)
        assert [k.object_id for k in keys] == [p.planned_object_id for p in response.raster_plans]
        assert _raster_address(context(), ORG, FARM, PLOT, CAMPAIGN, "rgb", None) == keys[0]
        for invalid_role in (("rgb", "ndvi"), ("scientific_cog", None), ("qml_style", "ndvi")):
            try:
                _raster_address(context(), ORG, FARM, PLOT, CAMPAIGN, *invalid_role)
            except ValueError:
                pass
            else:
                raise AssertionError("Rol ajeno fue admitido.")

        for changes in (
            {"analysis_type": "density"}, {"status": "APPROVED"},
            {"status": "PUBLISHED"}, {"approved_at": DATE},
            {"published_at": DATE}, {"organization_ref": "other"},
            {"campaign_id": UUID("91000000-0000-4000-8000-000000000099")},
        ):
            Reader.current = snapshot(**changes)
            denied(lambda: query(base), 404)
        Reader.current = snapshot()
        denied(lambda: query(None), 503)

        # Una lectura corrupta del manifiesto debe bloquearse, no crear sesiones.
        original_read = base.open_read

        @contextmanager
        def bad_read(address):
            with BytesIO(b"not a valid manifest") as stream:
                yield stream

        with patch.object(base, "open_read", bad_read):
            denied(lambda: query(base), 503)

        # Escenario realista: COG 200 MiB y 80 MiB, plan multipart de 64 MiB.
        altered = sample()
        changed = {
            ("scientific_cog", "ndvi"): 200 * MIB,
            ("scientific_cog", "ndre"): 80 * MIB,
        }
        for item in altered["draft"]["files"]:
            if (item["role"], item["index"]) in changed:
                item["size_bytes"] = changed[(item["role"], item["index"])]
        another = DBIInMemoryObjectStore()
        issued = upload_manifest(another, PrivateScientificManifestSubmission.model_validate(altered))
        with patch.object(another, "put", side_effect=AssertionError("El plan escribió bytes.")):
            plans = query(another)
        flags_off(plans)
        assert plans.manifest_sha256 == issued.manifest_sha256
        by_pair = {(x.role, x.index): x for x in plans.raster_plans}
        big = by_pair[("scientific_cog", "ndvi")]
        medium = by_pair[("scientific_cog", "ndre")]
        assert big.routing is DBIMultipartRoutingDecision.MULTIPART
        assert medium.routing is DBIMultipartRoutingDecision.MULTIPART
        assert big.part_size_bytes == medium.part_size_bytes == 64 * MIB
        assert big.part_count == 4 and medium.part_count == 2
        assert big.max_grants_per_window == DBI_MULTIPART_DEFAULT_LIMITS.max_grants_per_window
        assert big.max_client_concurrency == DBI_MULTIPART_DEFAULT_LIMITS.max_client_concurrency
        assert plans.total_declared_raster_bytes == 123456 + 4 * 512 + 200 * MIB + 80 * MIB
        assert all(not p.upload_initiated for p in plans.raster_plans)

    with patch.dict(os.environ, {
        "DBI_SCIENTIFIC_RASTER_PREFLIGHT_ENABLED": "0",
        "DBI_ENVIRONMENT": "test",
    }), patch("app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader):
        before = Reader.calls
        denied(lambda: query(base), 404)
        assert Reader.calls == before

    # No abrir un endpoint productivo con solo cambiar el flag.
    from app.api.v1 import get_api_router
    route_fragment = "/scientific-intake/private-raster-multipart-preflight"
    for environment, enabled in (("production", False), ("staging", False), ("", False), ("test", True)):
        with patch.dict(os.environ, {
            "DBI_SCIENTIFIC_RASTER_PREFLIGHT_ENABLED": "1",
            "DBI_ENVIRONMENT": environment,
        }):
            try:
                denied(lambda: query(base), 404) if not enabled else None
            except Exception:
                raise
            paths = [route.path for route in get_api_router().routes]
            assert any(route_fragment in path for path in paths) is enabled

    source = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_preflight.py").read_text()
    assert "issue_temporary_access" not in source
    assert "issue_part_access" not in source
    assert "session.commit(" not in source
    assert "put_object(" not in source
    assert "published=True" not in source
    assert "DBIMultipartPolicy.build_upload_plan" in source
    print("H14/2H/1 OK: siete planes raster scope/manifest; sin transferir ni aprobar.")


if __name__ == "__main__":
    run_tests()
