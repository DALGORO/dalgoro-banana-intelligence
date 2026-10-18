"""CI H14/2H-2D/2: S3 loopback start/abort, no URL or grant."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-local-only")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import (
    CAMPAIGN, FARM, ORG, PLOT, DATE, Reader, context, fake_test_store, snapshot,
)
from ci_dbi_scientific_raster_reservations import PAIRS, req, submit
from ci_dbi_scientific_raster_sql_bindings import BindingRepo, LockedRepo, SQLSessionDouble, bind
from ci_dbi_scientific_raster_assets import AssetsDouble, call as register_asset
from ci_dbi_scientific_raster_session_preparations import (
    ID_KEY, PreparationsDouble, large_manifest, invoke as prepare,
)
from app.api.v1.dbi_scientific_raster_local_provider import (
    _provider as production_provider, scientific_local_provider_lifecycle,
)
from app.api.v1.dbi_scientific_raster_session_preparations import ScientificSessionPreparationPayload
from app.dbi.asset_multipart_provider import (
    DBIMultipartProviderAbortConfirmation, DBIMultipartProviderUpload,
)
from app.dbi.models import DBIScientificRasterProviderStart
from app.dbi.storage_memory import DBIInMemoryObjectStore


class Provider:
    def __init__(self):
        self.remote = {}
        self.starts = 0
        self.aborts = 0

    def initiate(self, contract):
        self.starts += 1
        ref = f"local-multipart-ref-{self.starts:04d}"
        result = DBIMultipartProviderUpload(
            provider_upload_ref=ref, session_id=contract.session_id,
            metadata=contract.metadata, plan=contract.plan,
            initiated_at=contract.initiated_at,
        )
        self.remote[ref] = result
        return result

    def abort(self, request):
        self.aborts += 1
        assert request.provider_upload_ref in self.remote
        self.remote.pop(request.provider_upload_ref)
        return DBIMultipartProviderAbortConfirmation(
            session_id=request.session_id, aborted_at=request.requested_at,
            provider_uploads_aborted=1, cleanup_confirmed=True,
        )


class Ledger:
    rows = {}

    def __init__(self, db):
        assert isinstance(db, SQLSessionDouble)

    def get(self, value):
        return self.rows.get(value.asset_id)

    def record_start(self, value, upload, *, now):
        assert value.asset_id not in self.rows
        row = SimpleNamespace(
            id=upload.session_id, preparation_id=upload.session_id,
            asset_id=value.asset_id, binding_id=value.raster.binding_id,
            tenant_ref=value.raster.tenant_ref,
            campaign_id=value.raster.campaign_id,
            provider_upload_ref=upload.provider_upload_ref,
            status="initiated_no_grants", created_at=now, aborted_at=None,
        )
        self.rows[value.asset_id] = row
        return row

    def mark_aborted(self, value, *, now):
        row = self.rows[value.asset_id]
        changed = row.status == "initiated_no_grants"
        if changed:
            row.status = "aborted_no_grants"
            row.aborted_at = now
        return row, changed


class FailingCommit(SQLSessionDouble):
    def commit(self):
        self.commits += 1
        raise SQLAlchemyError("ci induced commit rollback")


def call(store, manifest, slot, role, index, operation="start", db=None, actor=None):
    db = db or SQLSessionDouble()
    resp = Response()
    value = scientific_local_provider_lifecycle(
        ORG, FARM, PLOT, CAMPAIGN, role, index, operation,
        ScientificSessionPreparationPayload(
            schema_version="dbi-h14-private-session-preparation-request.v1",
            manifest_sha256=manifest.manifest_sha256,
            reservation_sha256=slot.reservation_sha256, idempotency_key=ID_KEY,
        ), req(store), resp, db, actor or context(),
    )
    assert resp.headers["Cache-Control"] == "no-store"
    return value, resp, db


def denied(fn, status):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == status, (status, exc.status_code, exc.detail)
    else:
        raise AssertionError("Se admitió operación no autorizada.")


def run():
    store = DBIInMemoryObjectStore()
    provider = Provider()
    BindingRepo.rows = {}
    AssetsDouble.assets = {}
    PreparationsDouble.rows = {}
    Ledger.rows = {}
    env = {
        "DBI_SCIENTIFIC_MANIFEST_ENABLED":"1",
        "DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED":"1",
        "DBI_SCIENTIFIC_RASTER_SQL_BINDING_ENABLED":"1",
        "DBI_SCIENTIFIC_RASTER_ASSET_REGISTRATION_ENABLED":"1",
        "DBI_SCIENTIFIC_RASTER_SESSION_PREP_ENABLED":"1",
        "DBI_SCIENTIFIC_RASTER_PROVIDER_START_ENABLED":"1",
        "DBI_ENVIRONMENT":"test",
    }
    with patch.dict(os.environ, env), patch(
        "app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader,
    ), patch("app.api.v1.dbi_scientific_manifest_private._store", fake_test_store), patch(
        "app.api.v1.dbi_scientific_raster_reservations._private_store", fake_test_store,
    ), patch("app.api.v1.dbi_scientific_raster_sql_bindings.DBICampaignRepository", LockedRepo), patch(
        "app.api.v1.dbi_scientific_raster_sql_bindings.DBIScientificRasterBindingRepository", BindingRepo,
    ), patch("app.api.v1.dbi_scientific_raster_assets.DBIScientificRasterAssetRepository", AssetsDouble), patch(
        "app.api.v1.dbi_scientific_raster_session_preparations.DBIScientificSessionPreparationRepository", PreparationsDouble,
    ), patch("app.api.v1.dbi_scientific_raster_local_provider.DBIScientificSessionPreparationRepository", PreparationsDouble), patch(
        "app.api.v1.dbi_scientific_raster_local_provider.DBIScientificProviderStartRepository", Ledger,
    ), patch("app.api.v1.dbi_scientific_raster_local_provider._provider", lambda request: provider):
        manifest = large_manifest(store)
        assets = []
        for role, index in PAIRS:
            slot, _ = submit(store, manifest.manifest_sha256, role, index)
            bind(store, manifest, slot, role=role, index=index)
            register_asset(store, manifest, slot, role=role, index=index)
            denied(lambda r=role, i=index, s=slot: call(store, manifest, s, r, i), 409)
            prepare(store, manifest, slot, role, index)
            result, response, _ = call(store, manifest, slot, role, index)
            assert response.status_code == 201 and result.created
            assert result.provider_started and result.state == "initiated_no_grants"
            assert not any((result.ready_for_upload, result.grants_issued,
                            result.parts_received, result.file_received,
                            result.content_verified, result.institutional_approved,
                            result.published))
            again, response, _ = call(store, manifest, slot, role, index)
            assert response.status_code == 200 and not again.created
            assets.append((role, index, slot))
        assert len(provider.remote) == 7 and provider.starts == 7
        role, index, slot = assets[0]
        for change in ({"status":"APPROVED"}, {"status":"PUBLISHED"},
                       {"approved_at": DATE}, {"published_at": DATE},
                       {"analysis_type":"density"}):
            Reader.current = snapshot(**change)
            denied(lambda: call(store, manifest, slot, role, index, "abort"), 404)
        Reader.current = snapshot()
        denied(lambda: call(store, manifest, slot, role, index,
                            actor=context(actor="other")), 409)
        result, _, _ = call(store, manifest, slot, role, index, "abort")
        assert result.provider_aborted and result.state == "aborted_no_grants"
        assert provider.aborts == 1 and len(provider.remote) == 6
        result, _, _ = call(store, manifest, slot, role, index, "abort")
        assert not result.changed
        denied(lambda: call(store, manifest, slot, role, index), 409)
        from app.api.v1 import get_api_router
        fragment = "/scientific-intake/private-raster-local-provider/"
        for env, allowed in (("production",False),("staging",False),("",False),
                             ("test",True),("local",True)):
            with patch.dict(os.environ, {"DBI_SCIENTIFIC_RASTER_PROVIDER_START_ENABLED":"1",
                                         "DBI_ENVIRONMENT":env}):
                assert any(fragment in r.path for r in get_api_router().routes) is allowed
                if not allowed:
                    denied(lambda: call(store, manifest, slot, role, index, "inspect"), 404)
    denied(lambda: production_provider(req(store)), 503)
    assert "fk_dbi_raster_provider_start_preparation" in {
        item.name for item in DBIScientificRasterProviderStart.__table__.constraints
    }
    sql = str(select(DBIScientificRasterProviderStart).with_for_update().compile(
        dialect=postgresql.dialect()
    ))
    assert "FOR UPDATE" in sql
    migration = (ROOT / "apps/platform-web/backend/dbi_alembic/versions/20261018_33_scientific_raster_provider_starts.py").read_text()
    assert 'down_revision: str | None = "dbi_0032_raster_session_prep"' in migration
    print("H14/2H-2D/2 OK: starts and aborts loopback, no grants.")


if __name__ == "__main__":
    run()
