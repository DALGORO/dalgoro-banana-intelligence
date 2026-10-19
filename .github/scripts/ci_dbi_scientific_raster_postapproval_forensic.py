"""CI H14/2H-2D/3B: approved/published forensic inventory, never cleanup."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-h14-postapproval-forensic")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import (  # noqa: E402
    CAMPAIGN, FARM, ORG, PLOT, DATE, Reader, context, fake_test_store, snapshot,
)
from ci_dbi_scientific_raster_reservations import req, submit  # noqa: E402
from ci_dbi_scientific_raster_sql_bindings import (  # noqa: E402
    BindingRepo, LockedRepo, SQLSessionDouble, bind,
)
from ci_dbi_scientific_raster_assets import (  # noqa: E402
    AssetsDouble, call as register_asset,
)
from ci_dbi_scientific_raster_session_preparations import (  # noqa: E402
    ID_KEY, PreparationsDouble, large_manifest, invoke as prepare,
)
from ci_dbi_scientific_raster_local_provider import (  # noqa: E402
    Ledger, call as local_provider,
)
from ci_dbi_scientific_raster_reconciliation import ListingProvider  # noqa: E402
from app.api.v1.dbi_scientific_raster_postapproval_forensic import (  # noqa: E402
    inspect_postapproval_raster_orphans,
)
from app.api.v1.dbi_scientific_raster_session_preparations import (  # noqa: E402
    ScientificSessionPreparationPayload,
)
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402


def call(store, manifest, slot, *, context_override=None, session=None,
         role="rgb", index="_"):
    db = session or SQLSessionDouble()
    response = Response()
    value = inspect_postapproval_raster_orphans(
        ORG, FARM, PLOT, CAMPAIGN, role, index,
        ScientificSessionPreparationPayload(
            schema_version="dbi-h14-private-session-preparation-request.v1",
            manifest_sha256=manifest.manifest_sha256,
            reservation_sha256=slot.reservation_sha256,
            idempotency_key=ID_KEY,
        ),
        req(store), response, db, context_override or context(),
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert db.commits == 0 and db.rollbacks == 1
    assert value.cleanup_performed is False
    assert value.upload_access_blocked is True
    assert value.provider_started_by_this_request is False
    assert not any((
        value.ready_for_upload, value.grants_issued, value.parts_received,
        value.file_received, value.raster_scientifically_validated,
        value.raster_institutionally_approved, value.raster_published,
    ))
    assert "upload_ref" not in value.model_dump_json()
    return value


def denied(fn, status, db=None, *, early=False):
    try:
        fn()
    except HTTPException as error:
        assert error.status_code == status, (status, error.status_code, error.detail)
    else:
        raise AssertionError("Inventario administrativo aceptó acceso prohibido.")
    if db is not None:
        assert db.commits == 0
        assert db.rollbacks == (0 if early else 1)


def main():
    store = DBIInMemoryObjectStore()
    provider = ListingProvider()
    Reader.current = snapshot()
    BindingRepo.rows = {}
    AssetsDouble.assets = {}
    PreparationsDouble.rows = {}
    Ledger.rows = {}
    flags = {
        "DBI_SCIENTIFIC_MANIFEST_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_SQL_BINDING_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_ASSET_REGISTRATION_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_SESSION_PREP_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_PROVIDER_START_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_RECONCILIATION_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_INVENTORY_ENABLED": "1",
        "DBI_ENVIRONMENT": "test",
    }
    with patch.dict(os.environ, flags), patch(
        "app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader,
    ), patch(
        "app.api.v1.dbi_scientific_manifest_private._store", fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_reservations._private_store", fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_sql_bindings.DBICampaignRepository", LockedRepo,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_forensic.DBICampaignRepository", LockedRepo,
    ), patch(
        "app.api.v1.dbi_scientific_raster_sql_bindings.DBIScientificRasterBindingRepository", BindingRepo,
    ), patch(
        "app.api.v1.dbi_scientific_raster_assets.DBIScientificRasterAssetRepository", AssetsDouble,
    ), patch(
        "app.api.v1.dbi_scientific_raster_session_preparations.DBIScientificSessionPreparationRepository",
        PreparationsDouble,
    ), patch(
        "app.api.v1.dbi_scientific_raster_local_provider.DBIScientificSessionPreparationRepository",
        PreparationsDouble,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_forensic.DBIScientificSessionPreparationRepository",
        PreparationsDouble,
    ), patch(
        "app.api.v1.dbi_scientific_raster_local_provider.DBIScientificProviderStartRepository", Ledger,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_forensic.DBIScientificProviderStartRepository", Ledger,
    ), patch(
        "app.api.v1.dbi_scientific_raster_local_provider._provider", lambda request: provider,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_forensic._provider",
        lambda request: provider,
    ):
        manifest = large_manifest(store)
        slot, _ = submit(store, manifest.manifest_sha256)
        bind(store, manifest, slot)
        register_asset(store, manifest, slot)
        prepare(store, manifest, slot)

        # Preapproval inventory must NOT be accessible through the admin route.
        denied(lambda: call(store, manifest, slot), 404)
        Reader.current = snapshot(status="APPROVED", approved_at=DATE)
        baseline = call(store, manifest, slot)
        assert baseline.campaign_status == "APPROVED"
        assert baseline.inventory_status == "no_remote_no_sql"
        assert not baseline.manual_review_required
        assert provider.starts == provider.aborts == 0

        # An orphan upload without SQL is visible but never deleted.
        from app.dbi.scientific_raster_asset_repository import scientific_asset_id
        from app.dbi.scientific_raster_session_repository import SessionPreparationRequest
        from app.api.v1.dbi_scientific_raster_local_provider import _upload_contract
        intent = next(iter(BindingRepo.rows.values()))
        evidence = SessionPreparationRequest(intent, ID_KEY, intent.created_by_ref)
        contract = _upload_contract(
            evidence, now=PreparationsDouble.rows[scientific_asset_id(intent)].created_at,
        )
        orphan = provider.initiate(contract)
        out = call(store, manifest, slot)
        assert out.inventory_status == "remote_orphan_without_sql"
        assert out.manual_review_required and out.possible_incomplete_uploads_remaining
        assert provider.aborts == 0 and orphan.provider_upload_ref in provider.remote
        provider.remote.pop(orphan.provider_upload_ref)

        # Before approval, local start is permitted ONLY to establish test evidence.
        Reader.current = snapshot()
        started, _, _ = local_provider(store, manifest, slot, "rgb", "_", "start")
        assert started.provider_started
        Reader.current = snapshot(status="APPROVED", approved_at=DATE)
        exact = call(store, manifest, slot)
        assert exact.inventory_status == "active_exact_single_upload"
        # Even an exact SQL↔S3 match after approval requires review for cleanup.
        assert exact.manual_review_required
        assert exact.sql_start_recorded and exact.recorded_upload_present
        assert not exact.cleanup_performed
        denied(lambda: local_provider(store, manifest, slot, "rgb", "_", "start"), 404)
        denied(lambda: local_provider(store, manifest, slot, "rgb", "_", "abort"), 404)
        assert provider.aborts == 0

        # Missing and unexpected incomplete uploads remain strictly diagnostic.
        remote_ref = Ledger.rows[scientific_asset_id(intent)].provider_upload_ref
        stored_upload = provider.remote.pop(remote_ref)
        missing = call(store, manifest, slot)
        assert missing.inventory_status == "sql_active_remote_missing"
        provider.remote[remote_ref] = stored_upload
        extra = provider.initiate(contract)
        overlap = call(store, manifest, slot)
        assert overlap.inventory_status == "sql_active_remote_extra"
        assert overlap.incomplete_upload_count == 2
        assert overlap.unexpected_upload_count == 1
        provider.remote.pop(extra.provider_upload_ref)

        Reader.current = snapshot(
            status="PUBLISHED", approved_at=DATE, published_at=DATE,
        )
        published = call(store, manifest, slot)
        assert published.campaign_status == "PUBLISHED"
        assert published.inventory_status == "active_exact_single_upload"
        assert published.raster_published is False  # Campaign status != verified TIFF.

        for changed in (
            {"status": "DRAFT"},
            {"status": "TECHNICAL_REVIEW"},
            {"status": "APPROVED"},
            {"status": "PUBLISHED", "published_at": DATE},
            {"status": "APPROVED", "approved_at": DATE, "published_at": DATE},
            {"analysis_type": "density", "status": "APPROVED", "approved_at": DATE},
            {"organization_ref": "unrelated", "status": "APPROVED", "approved_at": DATE},
        ):
            Reader.current = snapshot(**changed)
            denied(lambda: call(store, manifest, slot), 404)
        Reader.current = snapshot(status="APPROVED", approved_at=DATE)
        denied(lambda: call(store, manifest, slot,
                            context_override=context(DBIPermission.READ)), 404)
        denied(lambda: call(store, manifest, slot,
                            context_override=context(tenant="unrelated")), 404)
        denied(lambda: call(store, manifest, slot,
                            context_override=context(actor="another")), 409)

        from app.api.v1 import get_api_router
        path_fragment = "/scientific-intake/private-raster-postapproval-forensic/"
        for env, open_route in (
            ("production", False), ("staging", False), ("", False),
            ("test", True), ("local", True), ("development", True),
        ):
            with patch.dict(os.environ, {
                "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_INVENTORY_ENABLED": "1",
                "DBI_ENVIRONMENT": env,
            }):
                assert any(path_fragment in r.path for r in get_api_router().routes) is open_route
                if not open_route:
                    db = SQLSessionDouble()
                    denied(lambda: call(store, manifest, slot, session=db), 404, db, early=True)
        with patch.dict(os.environ, {
            "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_INVENTORY_ENABLED": "0",
            "DBI_ENVIRONMENT": "test",
        }):
            denied(lambda: call(store, manifest, slot), 404)
        assert provider.aborts == 0  # This route never aborts anything.

    source = (
        ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_postapproval_forensic.py"
    ).read_text()
    endpoint = source.split("def inspect_postapproval_raster_orphans(", 1)[1]
    assert endpoint.index("_locked_postapproval_campaign(") < endpoint.index("_verified_intent(")
    assert endpoint.index("DBIScientificSessionPreparationRepository(") < endpoint.index(
        "provider.inspect_incomplete_uploads("
    )
    assert "session.commit(" not in source
    assert "provider.abort(" not in source
    assert "provider.initiate(" not in source
    assert "issue_part_access(" not in source
    print("H14/2H-2D/3B OK: forensic inventory post-approval; no cleanup or grants.")


if __name__ == "__main__":
    main()
