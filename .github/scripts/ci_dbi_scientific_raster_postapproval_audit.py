"""H14/2H-2D/3C: postapproval institutional audit; no writes, grants or cleanup."""
from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from sqlalchemy.dialects import postgresql

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-h14-postapproval-audit")
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
from ci_dbi_scientific_raster_reconciliation import ListingProvider  # noqa: E402
from app.api.v1.dbi_scientific_raster_postapproval_audit import (  # noqa: E402
    AuditRequest, audit_approved_raster,
)
from app.api.v1.dbi_scientific_raster_local_provider import _upload_contract  # noqa: E402
from app.api.v1.dbi_scientific_raster_preflight import _raster_address  # noqa: E402
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.asset_multipart_provider import DBIMultipartProviderError  # noqa: E402
from app.dbi.models.scientific_raster_assets import DBIScientificRasterInputAsset  # noqa: E402
from app.dbi.models.scientific_raster_bindings import DBIScientificRasterBinding  # noqa: E402
from app.dbi.models.scientific_raster_session_preparations import DBIScientificRasterSessionPreparation  # noqa: E402
from app.dbi.models.scientific_raster_provider_starts import DBIScientificRasterProviderStart  # noqa: E402
from app.dbi.scientific_raster_asset_repository import scientific_asset_id  # noqa: E402
from app.dbi.scientific_raster_session_repository import SessionPreparationRequest, _id  # noqa: E402
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402
from app.dbi.storage_contracts import DBIStorageWriteRequest  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402


def auditor():
    return replace(
        context(actor="approver-ci"),
        permissions=frozenset({DBIPermission.MANAGE, DBIPermission.APPROVE_AGRONOMIC}),
    )


class ReadOnlySQL(SQLSessionDouble):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows
        self.queries = []

    def execute(self, stmt):
        descriptions = stmt.column_descriptions
        model = descriptions[0]["entity"]
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" in sql
        assert "tenant_ref" in sql and "campaign_id" in sql
        self.queries.append(model)
        return SimpleNamespace(scalar_one_or_none=lambda: self.rows.get(model))


def rows_for(intent, ticket, provider_ref=None):
    aid = scientific_asset_id(intent)
    b = SimpleNamespace(**{
        **asdict(intent), "id": intent.binding_id,
        "analysis_type": "multispectral", "status": "asset_registered_pending_bytes",
        "created_at": DATE,
        "asset_id": aid,
    })
    a = SimpleNamespace(
        id=aid, binding_id=intent.binding_id,
        **{k: getattr(intent, k) for k in (
            "tenant_ref", "organization_ref", "farm_id", "plot_id",
            "campaign_id", "role", "index_ref", "target_object_id",
            "declared_size_bytes", "declared_sha256", "created_by_ref",
        )},
        asset_kind="orthophoto_rgb" if intent.role == "rgb" else "scientific_cog",
        content_type="image/tiff", status="registered_pending_bytes",
        file_received=False, content_verified=False, session_started=False,
        institutional_approved=False, published=False,
    )
    provider_row = None
    if provider_ref is not None:
        provider_row = SimpleNamespace(
            id=_id(aid), preparation_id=_id(aid),
            asset_id=aid, binding_id=intent.binding_id,
            tenant_ref=intent.tenant_ref, organization_ref=intent.organization_ref,
            farm_id=intent.farm_id, plot_id=intent.plot_id,
            campaign_id=intent.campaign_id, target_object_id=intent.target_object_id,
            declared_sha256=intent.declared_sha256, size_bytes=intent.declared_size_bytes,
            created_by_ref=intent.created_by_ref,
            provider_upload_ref=provider_ref, status="initiated_no_grants",
        )
    return {
        DBIScientificRasterBinding: b,
        DBIScientificRasterInputAsset: a,
        DBIScientificRasterSessionPreparation: ticket,
        DBIScientificRasterProviderStart: provider_row,
    }


def perform(store, manifest, slot, rows, *, actor=None, sha=None, index="_"):
    db = ReadOnlySQL(rows)
    response = Response()
    result = audit_approved_raster(
        ORG, FARM, PLOT, CAMPAIGN, "rgb", index,
        AuditRequest(
            schema_version="dbi-h14-postapproval-audit-request.v1",
            manifest_sha256=sha or manifest.manifest_sha256,
            reservation_sha256=slot.reservation_sha256,
        ),
        req(store), response, db, actor or auditor(),
    )
    assert db.commits == 0 and db.rollbacks == 1
    assert response.headers["Cache-Control"] == "no-store"
    assert len(db.queries) == 4
    return result


def denied(fn, status):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == status, (status, exc.status_code, exc.detail)
    else:
        raise AssertionError(f"Esperaba HTTP {status}.")


def validate(receipt, status, review):
    assert receipt.status == status
    assert receipt.manual_review_required is review
    assert not any((
        receipt.automatic_cleanup_performed, receipt.ready_for_upload,
        receipt.grants_issued, receipt.file_received,
        receipt.content_verified, receipt.published_by_this_audit,
    ))
    wire = receipt.model_dump_json()
    assert "provider_upload_ref" not in wire and "local-multipart-ref" not in wire
    assert "idempotency_key" not in wire


def run():
    store = DBIInMemoryObjectStore()
    provider = ListingProvider()
    BindingRepo.rows = {}
    AssetsDouble.assets = {}
    PreparationsDouble.rows = {}
    flags = {
        "DBI_SCIENTIFIC_MANIFEST_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_SQL_BINDING_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_ASSET_REGISTRATION_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_SESSION_PREP_ENABLED": "1",
        "DBI_SCIENTIFIC_POSTAPPROVAL_AUDIT_ENABLED": "1",
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
        "app.api.v1.dbi_scientific_raster_postapproval_audit._provider", lambda request: provider,
    ):
        Reader.current = snapshot()
        manifest = large_manifest(store)
        slot, _ = submit(store, manifest.manifest_sha256)
        bind(store, manifest, slot)
        register_asset(store, manifest, slot)
        prepare(store, manifest, slot)
        intent = next(iter(BindingRepo.rows.values()))
        ticket = PreparationsDouble.rows[scientific_asset_id(intent)]
        rows = rows_for(intent, ticket)
        Reader.current = snapshot(status="APPROVED", approved_at=DATE)

        # Reviewer is not the operator; the reviewer has BOTH privileges.
        no_remote = perform(store, manifest, slot, rows)
        validate(no_remote, "no_remote_no_sql", False)
        assert no_remote.campaign_status == "APPROVED"
        assert no_remote.asset_id == scientific_asset_id(intent)
        assert not no_remote.target_tiff_object_present
        Reader.current = snapshot(status="APPROVED")
        assert perform(store, manifest, slot, rows).manual_review_required
        Reader.current = snapshot(status="PUBLISHED", approved_at=DATE)
        assert perform(store, manifest, slot, rows).manual_review_required
        Reader.current = snapshot(status="APPROVED", approved_at=DATE)

        for bad in (
            context(DBIPermission.MANAGE),
            context(DBIPermission.APPROVE_AGRONOMIC),
            context(DBIPermission.READ),
            replace(auditor(), tenant_ref="other-tenant"),
        ):
            denied(lambda actor=bad: perform(store, manifest, slot, rows, actor=actor), 404)
        denied(lambda: perform(store, manifest, slot, rows, sha="f"*64), 409)
        denied(lambda: perform(store, manifest, slot, rows, index="ndvi"), 422)

        contract = _upload_contract(
            SessionPreparationRequest(intent, ID_KEY, intent.created_by_ref),
            now=ticket.created_at,
        )
        remote = provider.initiate(contract)
        validate(perform(store, manifest, slot, rows), "remote_orphan_without_sql", True)
        rows = rows_for(intent, ticket, remote.provider_upload_ref)
        validate(perform(store, manifest, slot, rows), "active_exact_single_upload", True)
        second = provider.initiate(contract)
        validate(perform(store, manifest, slot, rows), "sql_active_remote_extra", True)
        provider.remote.pop(second.provider_upload_ref)
        provider.remote.pop(remote.provider_upload_ref)
        validate(perform(store, manifest, slot, rows), "sql_active_remote_missing", True)
        rows[DBIScientificRasterProviderStart].status = "aborted_no_grants"
        validate(perform(store, manifest, slot, rows), "sql_aborted_no_remote", False)
        rows[DBIScientificRasterProviderStart].status = "initiated_no_grants"

        # A destination object that appears after approval still needs review.
        payload = b"synthetic bytes: NOT a TIFF"
        addr = _raster_address(auditor(), ORG, FARM, PLOT, CAMPAIGN, "rgb", None)
        meta = DBIStoragePolicy.build_metadata(
            address=addr, content_type="image/tiff", size_bytes=len(payload),
            sha256_hex=sha256(payload).hexdigest(),
        )
        store.put(DBIStorageWriteRequest(metadata=meta), BytesIO(payload))
        result = perform(store, manifest, slot, rows_for(intent, ticket))
        assert result.target_tiff_object_present and result.manual_review_required

        # Postapproval auditor never mutates Campaign, SQL or remote S3.
        assert provider.starts == 2 and provider.aborts == 0
        for changes in ({"status": "DRAFT"}, {"analysis_type": "density"},
                        {"organization_ref": "outsider"}):
            Reader.current = snapshot(**changes)
            denied(lambda: perform(store, manifest, slot, rows), 404)
        Reader.current = snapshot(status="PUBLISHED", approved_at=DATE, published_at=DATE)
        assert perform(store, manifest, slot, rows).campaign_status == "PUBLISHED"
        with patch.object(provider, "inspect_incomplete_uploads",
                          side_effect=DBIMultipartProviderError("S3 down")):
            denied(lambda: perform(store, manifest, slot, rows), 503)

        from app.api.v1 import get_api_router
        needle = "/scientific-intake/private-raster-postapproval-audit/"
        for env, on in (("production", False), ("staging", False), ("", False),
                        ("test", True), ("local", True), ("development", True)):
            with patch.dict(os.environ, {
                "DBI_SCIENTIFIC_POSTAPPROVAL_AUDIT_ENABLED": "1",
                "DBI_ENVIRONMENT": env,
            }):
                assert any(needle in rt.path for rt in get_api_router().routes) is on
                if not on:
                    denied(lambda: perform(store, manifest, slot, rows), 404)
        with patch.dict(os.environ, {"DBI_SCIENTIFIC_POSTAPPROVAL_AUDIT_ENABLED": "0"}):
            denied(lambda: perform(store, manifest, slot, rows), 404)
    print("H14/2H-2D/3C OK: dual-authorized postapproval read-only audit, no grants or cleanup.")


if __name__ == "__main__":
    run()
