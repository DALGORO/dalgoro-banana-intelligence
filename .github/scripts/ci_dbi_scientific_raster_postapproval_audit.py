"""CI H14/2H-2D/3C: postapproval S3 residue audit, never a cleanup endpoint."""
from __future__ import annotations

from pathlib import Path
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-postapproval-only")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import (  # noqa: E402
    CAMPAIGN, FARM, ORG, PLOT, DATE, Reader, context, fake_test_store, snapshot,
)
from ci_dbi_scientific_raster_reservations import req, submit  # noqa: E402
from ci_dbi_scientific_raster_sql_bindings import (  # noqa: E402
    BindingRepo, LockedRepo, SQLSessionDouble, bind,
)
from ci_dbi_scientific_raster_assets import AssetsDouble, call as register_asset  # noqa: E402
from ci_dbi_scientific_raster_session_preparations import (  # noqa: E402
    ID_KEY, PreparationsDouble, large_manifest, invoke as prepare,
)
from ci_dbi_scientific_raster_local_provider import (  # noqa: E402
    Ledger, call as local_start,
)
from ci_dbi_scientific_raster_reconciliation import ListingProvider, attempt as preaudit  # noqa: E402
from app.api.v1.dbi_scientific_raster_postapproval_audit import (  # noqa: E402
    audit_postapproval_incomplete_raster_uploads,
)
from app.api.v1.dbi_scientific_raster_session_preparations import (  # noqa: E402
    ScientificSessionPreparationPayload,
)
from app.api.v1.dbi_scientific_raster_local_provider import _upload_contract  # noqa: E402
from app.dbi.asset_multipart_provider import DBIMultipartProviderError  # noqa: E402
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.scientific_raster_session_repository import SessionPreparationRequest  # noqa: E402
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402


class ApprovedCampaignRepo:
    calls = 0

    def __init__(self, session):
        assert isinstance(session, SQLSessionDouble)

    def get_campaign_for_update(self, **kwargs):
        self.__class__.calls += 1
        row = Reader.current
        return SimpleNamespace(
            id=row.campaign_id, tenant_ref=row.tenant_ref,
            organization_ref=row.organization_ref,
            farm_id=row.farm_id, plot_id=row.plot_id,
            analysis_type=row.analysis_type,
            status=row.status, approved_at=row.approved_at,
            published_at=row.published_at,
        )


def audit(store, manifest, slot, role="rgb", index="_", *, ctx=None):
    db, response = SQLSessionDouble(), Response()
    value = audit_postapproval_incomplete_raster_uploads(
        ORG, FARM, PLOT, CAMPAIGN, role, index,
        ScientificSessionPreparationPayload(
            schema_version="dbi-h14-private-session-preparation-request.v1",
            manifest_sha256=manifest.manifest_sha256,
            reservation_sha256=slot.reservation_sha256,
            idempotency_key=ID_KEY,
        ),
        req(store), response, db, ctx or context(),
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert db.commits == 0 and db.rollbacks == 1
    assert value.ready_for_upload is False
    assert value.grants_issued is False
    assert value.parts_received is False
    assert value.file_received is False
    assert value.content_verified is False
    assert value.cleanup_performed is False
    assert value.asset_institutionally_approved is False
    assert value.asset_published is False
    assert "upload_ref" not in value.model_dump_json()
    assert "object_key" not in value.model_dump_json()
    return value


def denied(fn, code):
    try:
        fn()
    except HTTPException as error:
        assert error.status_code == code, (code, error.status_code, error.detail)
    else:
        raise AssertionError("Se permitió auditoría prohibida.")


def run():
    store = DBIInMemoryObjectStore()
    provider = ListingProvider()
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
        "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED": "1",
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
        "app.api.v1.dbi_scientific_raster_sql_bindings.DBIScientificRasterBindingRepository", BindingRepo,
    ), patch(
        "app.api.v1.dbi_scientific_raster_assets.DBIScientificRasterAssetRepository", AssetsDouble,
    ), patch(
        "app.api.v1.dbi_scientific_raster_session_preparations.DBIScientificSessionPreparationRepository", PreparationsDouble,
    ), patch(
        "app.api.v1.dbi_scientific_raster_local_provider.DBIScientificSessionPreparationRepository", PreparationsDouble,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_audit.DBIScientificSessionPreparationRepository", PreparationsDouble,
    ), patch(
        "app.api.v1.dbi_scientific_raster_local_provider.DBIScientificProviderStartRepository", Ledger,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_audit.DBIScientificProviderStartRepository", Ledger,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_audit.DBICampaignRepository", ApprovedCampaignRepo,
    ), patch(
        "app.api.v1.dbi_scientific_raster_local_provider._provider", lambda request: provider,
    ), patch(
        "app.api.v1.dbi_scientific_raster_postapproval_audit._provider", lambda request: provider,
    ):
        manifest = large_manifest(store)
        slot, _ = submit(store, manifest.manifest_sha256, "rgb", "_")
        bind(store, manifest, slot)
        register_asset(store, manifest, slot)
        prepare(store, manifest, slot)

        # PREAPPROVAL audit deliberately unavailable on draft Campaign.
        denied(lambda: audit(store, manifest, slot), 404)
        # Construct a remote orphan BEFORE approval (no SQL provider ledger).
        raster = next(row for row in BindingRepo.rows.values() if row.role == "rgb")
        evidence = SessionPreparationRequest(raster, ID_KEY, raster.created_by_ref)
        ticket = PreparationsDouble.rows[evidence.asset_id]
        upload_contract = _upload_contract(evidence, now=ticket.created_at)
        orphan = provider.initiate(upload_contract)
        Reader.current = snapshot(status="APPROVED", approved_at=DATE)
        before = provider.starts, provider.aborts
        report = audit(store, manifest, slot)
        assert report.campaign_status == "APPROVED"
        assert report.reconciliation_status == "remote_orphan_without_sql"
        assert report.remote_cleanup_required and report.manual_review_required
        assert report.incomplete_upload_count == 1
        assert (provider.starts, provider.aborts) == before
        denied(lambda: local_start(store, manifest, slot, "rgb", "_"), 404)
        provider.remote.pop(orphan.provider_upload_ref)
        report = audit(store, manifest, slot)
        assert report.reconciliation_status == "no_remote_no_sql"
        assert not report.remote_cleanup_required and not report.manual_review_required

        # No provider changes during audit, whether remote matches or diverges.
        Reader.current = snapshot()
        started, _, _ = local_start(store, manifest, slot, "rgb", "_")
        assert started.provider_started
        Reader.current = snapshot(status="APPROVED", approved_at=DATE)
        report = audit(store, manifest, slot)
        assert report.reconciliation_status == "active_exact_single_upload"
        assert report.remote_cleanup_required and report.manual_review_required
        assert provider.aborts == 0
        denied(lambda: local_start(store, manifest, slot, "rgb", "_", "abort"), 404)
        Reader.current = snapshot(status="PUBLISHED", approved_at=DATE, published_at=DATE)
        report = audit(store, manifest, slot)
        assert report.campaign_status == "PUBLISHED" and report.manual_review_required

        # Missing or inconsistent approval timestamps deny inspection.
        for changes in (
            {"status": "APPROVED", "approved_at": None},
            {"status": "APPROVED", "approved_at": DATE, "published_at": DATE},
            {"status": "PUBLISHED", "approved_at": DATE, "published_at": None},
            {"status": "DRAFT", "approved_at": DATE},
            {"status": "PUBLISHED", "approved_at": DATE, "published_at": DATE,
             "organization_ref": "different"},
            {"status": "PUBLISHED", "approved_at": DATE, "published_at": DATE,
             "analysis_type": "density"},
        ):
            Reader.current = snapshot(**changes)
            denied(lambda: audit(store, manifest, slot), 404)
        Reader.current = snapshot(status="APPROVED", approved_at=DATE)
        denied(lambda: audit(store, manifest, slot, ctx=context(DBIPermission.READ)), 404)
        denied(lambda: audit(store, manifest, slot, ctx=context(actor="someone-else")), 409)
        denied(lambda: audit(store, manifest, slot, ctx=context(tenant="alien")), 404)
        with patch.object(provider, "inspect_incomplete_uploads",
                          side_effect=DBIMultipartProviderError("Unavailable")):
            denied(lambda: audit(store, manifest, slot), 503)

        from app.api.v1 import get_api_router
        fragment = "/scientific-intake/private-raster-postapproval-audit/"
        for env, available in (
            ("production", False), ("staging", False), ("", False),
            ("test", True), ("development", True), ("local", True),
        ):
            with patch.dict(os.environ, {
                "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED": "1",
                "DBI_ENVIRONMENT": env,
            }):
                routes = get_api_router().routes
                assert any(fragment in item.path for item in routes) is available
                if not available:
                    denied(lambda: audit(store, manifest, slot), 404)
        with patch.dict(os.environ, {"DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED": "0"}):
            denied(lambda: audit(store, manifest, slot), 404)

    source = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_postapproval_audit.py").read_text()
    endpoint = source.split("def audit_postapproval_incomplete_raster_uploads(", 1)[1]
    assert endpoint.index("_locked_approved_campaign(") < endpoint.index("_verified_intent(")
    assert "session.rollback()" in source
    for forbidden in ("provider.abort(", "provider.initiate(", "issue_part_access(", "session.commit(", "presigned"):
        assert forbidden not in source
    print("H14/2H-2D/3C OK: postapproval orphan/active audit, no S3 changes or grants.")


if __name__ == "__main__":
    run()
