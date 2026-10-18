"""CI H14/2H-2D/3A: reconcilia sesiones S3/SQL sin grants ni escrituras."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi import HTTPException, Response

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-h14-readonly-reconciliation")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import (  # noqa: E402
    CAMPAIGN, FARM, ORG, PLOT, DATE, Reader, context, fake_test_store, snapshot,
)
from ci_dbi_scientific_raster_reservations import PAIRS, req, submit  # noqa: E402
from ci_dbi_scientific_raster_sql_bindings import (  # noqa: E402
    BindingRepo, LockedRepo, SQLSessionDouble, bind,
)
from ci_dbi_scientific_raster_assets import AssetsDouble, call as register_asset  # noqa: E402
from ci_dbi_scientific_raster_session_preparations import (  # noqa: E402
    ID_KEY, PreparationsDouble, large_manifest, invoke as prepare,
)
from ci_dbi_scientific_raster_local_provider import (  # noqa: E402
    Ledger, Provider, call as local_start,
)
from app.api.v1.dbi_scientific_raster_reconciliation import (  # noqa: E402
    classify_inventory, reconcile_private_raster_s3,
)
from app.api.v1.dbi_scientific_raster_session_preparations import (  # noqa: E402
    ScientificSessionPreparationPayload,
)
from app.api.v1.dbi_scientific_raster_local_provider import _upload_contract  # noqa: E402
from app.dbi.asset_multipart_provider import DBIMultipartProviderError  # noqa: E402
from app.dbi.asset_multipart_s3 import (  # noqa: E402
    DBIS3IncompleteUploadInventory, DBIS3MultipartAdapter,
)
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.scientific_raster_session_repository import SessionPreparationRequest  # noqa: E402
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402


class ListingProvider(Provider):
    def __init__(self):
        super().__init__()
        self.listings = 0

    def inspect_incomplete_uploads(self, contract, *, expected_upload_ref):
        self.listings += 1
        found = tuple(
            ref for ref, remote in self.remote.items()
            if remote.metadata.address.object_key == contract.metadata.address.object_key
        )
        matched = expected_upload_ref is not None and expected_upload_ref in found
        return DBIS3IncompleteUploadInventory(
            incomplete_count=len(found),
            expected_present=matched,
            unexpected_count=len(found) - int(matched),
        )


def attempt(store, manifest, slot, role, index, *, actor=None, db=None):
    response = Response()
    db = db or SQLSessionDouble()
    result = reconcile_private_raster_s3(
        ORG, FARM, PLOT, CAMPAIGN, role, index,
        ScientificSessionPreparationPayload(
            schema_version="dbi-h14-private-session-preparation-request.v1",
            manifest_sha256=manifest.manifest_sha256,
            reservation_sha256=slot.reservation_sha256,
            idempotency_key=ID_KEY,
        ), req(store), response, db, actor or context(),
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert db.commits == 0 and db.rollbacks == 1
    return result


def denied(callback, code):
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == code, (code, exc.status_code, exc.detail)
    else:
        raise AssertionError("Conciliación debió rechazar este escenario.")


def assert_status(store, manifest, slot, role, index, provider, expected):
    before = provider.starts, provider.aborts
    result = attempt(store, manifest, slot, role, index)
    assert result.status == expected, (result.status, expected)
    assert (provider.starts, provider.aborts) == before
    assert not any((
        result.ready_for_upload, result.grants_issued,
        result.parts_received, result.file_received,
        result.content_verified, result.institutional_approved, result.published,
    ))
    assert "local-multipart-ref" not in result.model_dump_json()
    assert "upload_ref" not in result.model_dump_json()
    return result


def test_adapter_inventory(contract):
    adapter = object.__new__(DBIS3MultipartAdapter)
    with patch.object(adapter, "_list_exact_upload_refs", return_value=(
        "local-multipart-ref-0001", "local-multipart-ref-0002",
    )) as listing:
        evidence = adapter.inspect_incomplete_uploads(
            contract, expected_upload_ref="local-multipart-ref-0001",
        )
    listing.assert_called_once_with(contract.metadata.address.object_key)
    assert evidence == DBIS3IncompleteUploadInventory(2, True, 1)
    with patch.object(adapter, "_list_exact_upload_refs", return_value=(
        "local-multipart-ref-0001", "local-multipart-ref-0001",
    )):
        try:
            adapter.inspect_incomplete_uploads(
                contract, expected_upload_ref="local-multipart-ref-0001",
            )
        except DBIMultipartProviderError:
            pass
        else:
            raise AssertionError("Duplicated provider UploadId not rejected.")


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
        "app.api.v1.dbi_scientific_raster_reconciliation.DBIScientificSessionPreparationRepository", PreparationsDouble,
    ), patch(
        "app.api.v1.dbi_scientific_raster_local_provider.DBIScientificProviderStartRepository", Ledger,
    ), patch(
        "app.api.v1.dbi_scientific_raster_reconciliation.DBIScientificProviderStartRepository", Ledger,
    ), patch(
        "app.api.v1.dbi_scientific_raster_local_provider._provider", lambda request: provider,
    ), patch(
        "app.api.v1.dbi_scientific_raster_reconciliation._provider", lambda request: provider,
    ):
        manifest = large_manifest(store)
        roles = []
        for role, index in PAIRS:
            slot, _ = submit(store, manifest.manifest_sha256, role, index)
            bind(store, manifest, slot, role=role, index=index)
            register_asset(store, manifest, slot, role=role, index=index)
            prepare(store, manifest, slot, role, index)
            roles.append((role, index, slot))
        role, index, slot = roles[0]
        no_sql = assert_status(store, manifest, slot, role, index,
                               provider, "no_remote_no_sql")
        assert not no_sql.manual_review_required
        intent = next(v for v in BindingRepo.rows.values() if v.role == role)
        session = SessionPreparationRequest(intent, ID_KEY, intent.created_by_ref)
        ticket = PreparationsDouble.rows[session.asset_id]
        contract = _upload_contract(session, now=ticket.created_at)
        test_adapter_inventory(contract)
        orphan = provider.initiate(contract)
        result = assert_status(store, manifest, slot, role, index,
                               provider, "remote_orphan_without_sql")
        assert result.manual_review_required and result.incomplete_upload_count == 1
        provider.remote.pop(orphan.provider_upload_ref)
        started, _, _ = local_start(store, manifest, slot, role, index)
        assert started.provider_started
        current = assert_status(store, manifest, slot, role, index,
                                provider, "active_exact_single_upload")
        assert not current.manual_review_required
        extra = provider.initiate(contract)
        result = assert_status(store, manifest, slot, role, index,
                               provider, "sql_active_remote_extra")
        assert result.unexpected_upload_count == 1
        provider.remote.pop(extra.provider_upload_ref)
        saved = Ledger.rows[session.asset_id].provider_upload_ref
        provider.remote.pop(saved)
        assert_status(store, manifest, slot, role, index,
                      provider, "sql_active_remote_missing")
        replacement = provider.initiate(contract)
        assert_status(store, manifest, slot, role, index,
                      provider, "sql_active_remote_replaced")
        provider.remote.pop(replacement.provider_upload_ref)
        provider.remote[saved] = ProviderUploadForTest(contract, saved)
        aborted, _, _ = local_start(store, manifest, slot, role, index, "abort")
        assert aborted.provider_aborted
        result = assert_status(store, manifest, slot, role, index,
                               provider, "sql_aborted_no_remote")
        assert not result.manual_review_required
        resurrected = provider.initiate(contract)
        assert_status(store, manifest, slot, role, index,
                      provider, "sql_aborted_remote_remains")
        provider.remote.pop(resurrected.provider_upload_ref)

        for change in (
            {"status": "APPROVED"}, {"status": "PUBLISHED"},
            {"approved_at": DATE}, {"published_at": DATE},
            {"analysis_type": "density"},
        ):
            Reader.current = snapshot(**change)
            denied(lambda: attempt(store, manifest, slot, role, index), 404)
        Reader.current = snapshot()
        denied(lambda: attempt(store, manifest, slot, role, index,
                               actor=context(DBIPermission.READ)), 404)
        denied(lambda: attempt(store, manifest, slot, role, index,
                               actor=context(actor="another")), 409)
        denied(lambda: attempt(store, manifest, slot, role, index,
                               actor=context(tenant="external")), 404)

        with patch.object(provider, "inspect_incomplete_uploads",
                          side_effect=DBIMultipartProviderError("S3 unavailable")):
            denied(lambda: attempt(store, manifest, slot, role, index), 503)

        from app.api.v1 import get_api_router
        fragment = "/scientific-intake/private-raster-local-reconciliation/"
        for env, enabled in (
            ("production", False), ("staging", False), ("", False),
            ("test", True), ("development", True), ("local", True),
        ):
            with patch.dict(os.environ, {
                "DBI_SCIENTIFIC_RASTER_RECONCILIATION_ENABLED": "1",
                "DBI_ENVIRONMENT": env,
            }):
                found = any(fragment in r.path for r in get_api_router().routes)
                assert found is enabled
                if not enabled:
                    denied(lambda: attempt(store, manifest, slot, role, index), 404)
        with patch.dict(os.environ, {"DBI_SCIENTIFIC_RASTER_RECONCILIATION_ENABLED": "0"}):
            denied(lambda: attempt(store, manifest, slot, role, index), 404)
    print("H14/2H-2D/3A OK: orphan, mismatch, missing, clean; never grant or mutate.")


class ProviderUploadForTest:
    """Minimal remote fixture with exact object locator."""
    def __init__(self, contract, ref):
        self.metadata = contract.metadata
        self.provider_upload_ref = ref


if __name__ == "__main__":
    run()
