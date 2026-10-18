"""CI H14/2H-2D: private preparation tickets, no provider/upload/grants.

Synthetic Campaign/S3/SQL doubles for API; existing integration CI tests
migrations in ephemeral PostGIS. No Render or production data touched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-h14-session-preparation")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import (  # noqa: E402
    CAMPAIGN, FARM, ORG, PLOT, DATE, Reader, FakeSession, context, fake_test_store, sample, snapshot,
)
from ci_dbi_scientific_raster_reservations import (  # noqa: E402
    PAIRS, req, submit,
)
from ci_dbi_scientific_raster_sql_bindings import (  # noqa: E402
    BindingRepo, LockedRepo, SQLSessionDouble, bind,
)
from ci_dbi_scientific_raster_assets import AssetsDouble, call as register_asset  # noqa: E402
from app.api.v1.dbi_scientific_manifest_private import (  # noqa: E402
    PrivateScientificManifestSubmission, put_private_scientific_manifest,
)
from app.api.v1.dbi_scientific_raster_session_preparations import (  # noqa: E402
    ScientificSessionPreparationPayload, handle_scientific_session_preparation,
)
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.asset_multipart_contracts import DBIMultipartRoutingDecision  # noqa: E402
from app.dbi.models import DBIScientificRasterSessionPreparation  # noqa: E402
from app.dbi.scientific_raster_session_repository import (  # noqa: E402
    DBIScientificSessionPreparationRepository, ScientificSessionPreparationConflict,
    SessionPreparationRequest, SESSION_PREPARATION_TTL, _id, _same, _validate,
)
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402

MIB = 1024 * 1024
ID_KEY = "h14-session-idempotent-operator-2026"


def large_manifest(store):
    document = sample()
    for file in document["draft"]["files"]:
        if file["role"] in {"rgb", "scientific_cog"}:
            file["size_bytes"] = 128 * MIB
    response = Response()
    received = put_private_scientific_manifest(
        ORG, FARM, PLOT, CAMPAIGN,
        PrivateScientificManifestSubmission.model_validate(document),
        req(store), response, FakeSession(), context(),
    )
    assert response.status_code == 201
    return received


class PreparationsDouble:
    rows = {}

    def __init__(self, db):
        assert isinstance(db, SQLSessionDouble)

    def _evidence(self, value):
        if (value.raster.binding_id not in BindingRepo.rows
                or value.asset_id not in AssetsDouble.assets):
            raise ScientificSessionPreparationConflict("Falta Asset o Binding.")
        return _validate(value)

    def prepare(self, value, *, now):
        identity, plan = self._evidence(value)
        assert plan.decision is DBIMultipartRoutingDecision.MULTIPART
        key = value.asset_id
        stored = self.rows.get(key)
        created = stored is None
        if created:
            stored = SimpleNamespace(
                id=_id(key), asset_id=key, binding_id=value.raster.binding_id,
                tenant_ref=value.raster.tenant_ref,
                organization_ref=value.raster.organization_ref,
                farm_id=value.raster.farm_id, plot_id=value.raster.plot_id,
                campaign_id=value.raster.campaign_id,
                manifest_sha256=value.raster.manifest_sha256,
                reservation_sha256=value.raster.slot_sha256,
                declared_sha256=value.raster.declared_sha256,
                size_bytes=value.raster.declared_size_bytes,
                part_size_bytes=plan.part_size_bytes, part_count=plan.part_count,
                max_grants_per_window=plan.max_grants_per_window,
                max_client_concurrency=plan.max_client_concurrency,
                checksum_algorithm="SHA256", checksum_type="COMPOSITE",
                idempotency_key_hash=identity.key_hash,
                status="prepared_no_provider", created_by_ref=value.requested_by,
                created_at=now, updated_at=now,
                expires_at=now + SESSION_PREPARATION_TTL, cancelled_at=None,
            )
            self.rows[key] = stored
        if not _same(stored, value, identity.key_hash, plan):
            raise ScientificSessionPreparationConflict("Reintento divergente.")
        if stored.status != "prepared_no_provider" or now >= stored.expires_at:
            raise ScientificSessionPreparationConflict("Ticket cancelado o vencido.")
        return stored, created

    def inspect(self, value, *, now):
        identity, plan = self._evidence(value)
        stored = self.rows.get(value.asset_id)
        if stored is None or not _same(stored, value, identity.key_hash, plan):
            raise ScientificSessionPreparationConflict("Ticket inexistente.")
        return stored

    def cancel(self, value, *, now):
        row = self.inspect(value, now=now)
        changed = row.status == "prepared_no_provider"
        if changed:
            row.status = "cancelled_no_provider"
            row.cancelled_at = now
            row.updated_at = now
        return row, changed


def invoke(store, manifest, slot, role="rgb", index="_", operation="prepare",
           key=ID_KEY, ctx=None, db=None, digest=None):
    session = db or SQLSessionDouble()
    response = Response()
    result = handle_scientific_session_preparation(
        ORG, FARM, PLOT, CAMPAIGN, role, index, operation,
        ScientificSessionPreparationPayload(
            schema_version="dbi-h14-private-session-preparation-request.v1",
            manifest_sha256=digest or manifest.manifest_sha256,
            reservation_sha256=slot.reservation_sha256,
            idempotency_key=key,
        ),
        req(store), response, session, ctx or context(),
    )
    assert response.headers["Cache-Control"] == "no-store"
    return result, response, session


def denied(fn, code, db=None, rollback=True):
    try:
        fn()
    except HTTPException as error:
        assert error.status_code == code, (code, error.status_code, error.detail)
    else:
        raise AssertionError(f"Se admitió operación bloqueada (esperado {code}).")
    if db is not None:
        assert db.commits == 0 and db.rollbacks == (1 if rollback else 0)


def run_api():
    BindingRepo.rows = {}
    AssetsDouble.assets = {}
    PreparationsDouble.rows = {}
    store = DBIInMemoryObjectStore()
    flags = {
        "DBI_SCIENTIFIC_MANIFEST_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_SQL_BINDING_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_ASSET_REGISTRATION_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_SESSION_PREP_ENABLED": "1",
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
    ):
        dummy = SimpleNamespace(manifest_sha256="a" * 64)
        fake = SimpleNamespace(reservation_sha256="b" * 64)
        d = SQLSessionDouble()
        denied(lambda: invoke(store, dummy, fake, ctx=context(DBIPermission.READ), db=d), 404, d)
        d = SQLSessionDouble()
        denied(lambda: invoke(store, dummy, fake, ctx=context(tenant="outsider"), db=d), 404, d)
        d = SQLSessionDouble()
        denied(lambda: invoke(store, dummy, fake, db=d), 404, d)
        manifest = large_manifest(store)

        for role, index in PAIRS:
            slot, _ = submit(store, manifest.manifest_sha256, role, index)
            d = SQLSessionDouble()
            denied(lambda r=role, i=index, s=slot, db=d: invoke(store, manifest, s, r, i, db=db), 409, d)
            binding, _, _ = bind(store, manifest, slot, role=role, index=index)
            d = SQLSessionDouble()
            denied(lambda r=role, i=index, s=slot, db=d: invoke(store, manifest, s, r, i, db=db), 409, d)
            register_asset(store, manifest, slot, role=role, index=index)
            receipt, http, db = invoke(store, manifest, slot, role, index)
            assert http.status_code == 201 and receipt.created and receipt.changed
            assert db.commits == 1 and db.rollbacks == 0
            assert receipt.binding_id == binding.binding_id
            assert receipt.status == "prepared_no_provider"
            assert receipt.part_size_bytes == 64 * MIB and receipt.part_count == 2
            assert receipt.expires_at > datetime.now(timezone.utc)
            assert not any((
                receipt.ready_for_upload, receipt.provider_started, receipt.session_started,
                receipt.grants_issued, receipt.file_received, receipt.content_verified,
                receipt.institutional_approved, receipt.published, receipt.expired,
            ))
            repeated, http, _ = invoke(store, manifest, slot, role, index)
            assert http.status_code == 200 and not repeated.created and not repeated.changed
            assert repeated.preparation_id == receipt.preparation_id
            observed, _, _ = invoke(store, manifest, slot, role, index, "inspect")
            assert observed.status == "prepared_no_provider" and not observed.changed
            d = SQLSessionDouble()
            denied(lambda s=slot, r=role, i=index, db=d: invoke(
                store, manifest, s, r, i, key="different-idempotency-token-2026", db=db
            ), 409, d)
            d = SQLSessionDouble()
            denied(lambda s=slot, r=role, i=index, db=d: invoke(
                store, manifest, s, r, i, ctx=context(actor="not-the-reserver"), db=db
            ), 409, d)
        assert len(PreparationsDouble.rows) == 7

        last_role, last_index = PAIRS[-1]
        final_slot, _ = submit(store, manifest.manifest_sha256, last_role, last_index)
        cancelled, http, _ = invoke(store, manifest, final_slot, last_role, last_index, "cancel")
        assert http.status_code == 200 and cancelled.changed
        assert cancelled.status == "cancelled_no_provider"
        again, _, _ = invoke(store, manifest, final_slot, last_role, last_index, "cancel")
        assert not again.changed
        d = SQLSessionDouble()
        denied(lambda: invoke(store, manifest, final_slot, last_role, last_index,
                              "prepare", db=d), 409, d)
        inspection, _, _ = invoke(store, manifest, final_slot, last_role, last_index, "inspect")
        assert inspection.status == "cancelled_no_provider"
        for changes in (
            {"analysis_type": "density"}, {"status": "APPROVED"},
            {"status": "PUBLISHED"}, {"approved_at": DATE},
            {"published_at": DATE}, {"organization_ref": "foreign"},
        ):
            Reader.current = snapshot(**changes)
            for op in ("prepare", "inspect", "cancel"):
                d = SQLSessionDouble()
                denied(lambda operation=op, db=d: invoke(
                    store, manifest, final_slot, last_role, last_index,
                    operation, db=db,
                ), 404, d)
        Reader.current = snapshot()

        d = SQLSessionDouble()
        denied(lambda: invoke(None, manifest, final_slot, last_role, last_index,
                              "inspect", db=d), 503, d)
        d = SQLSessionDouble()
        denied(lambda: invoke(store, manifest, final_slot, last_role, last_index,
                              "inspect", digest="f" * 64, db=d), 409, d)

        from app.api.v1 import get_api_router
        fragment = "/scientific-intake/private-raster-session-preparations/"
        for env, available in (("production", False), ("staging", False),
                                ("", False), ("test", True), ("development", True)):
            with patch.dict(os.environ, {
                "DBI_SCIENTIFIC_RASTER_SESSION_PREP_ENABLED": "1", "DBI_ENVIRONMENT": env,
            }):
                found = any(fragment in r.path for r in get_api_router().routes)
                assert found is available, (env, found)
                if not available:
                    d = SQLSessionDouble()
                    denied(lambda db=d: invoke(
                        store, manifest, final_slot, last_role, last_index, "inspect", db=db,
                    ), 404, d, rollback=False)
        with patch.dict(os.environ, {"DBI_SCIENTIFIC_RASTER_SESSION_PREP_ENABLED": "0"}):
            d = SQLSessionDouble()
            denied(lambda: invoke(store, manifest, final_slot, last_role,
                                  last_index, "inspect", db=d), 404, d, rollback=False)


def run_contract():
    from app.dbi.scientific_raster_binding_repository import ScientificRasterBindingIntent
    intent = next(iter(BindingRepo.rows.values()))
    request = SessionPreparationRequest(intent, ID_KEY, intent.created_by_ref)
    identity, plan = _validate(request)
    assert plan.decision is DBIMultipartRoutingDecision.MULTIPART
    assert identity.key_hash == sha256(("dalgoro:dbi:multipart:key:v1\0" + ID_KEY).encode()).hexdigest()
    assert len(PreparationsDouble.rows) == 7
    stored = PreparationsDouble.rows[request.asset_id]
    assert _same(stored, request, identity.key_hash, plan)
    stored.idempotency_key_hash = "f" * 64
    assert not _same(stored, request, identity.key_hash, plan)
    stored.idempotency_key_hash = identity.key_hash
    stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    try:
        PreparationsDouble(SQLSessionDouble()).prepare(request, now=datetime.now(timezone.utc))
    except (ScientificSessionPreparationConflict, AssertionError):
        pass  # Database repository below validates the same contract under locks.
    else:
        raise AssertionError("Se aceptó ticket expirado.")
    stored.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    db = Session()
    from sqlalchemy import select
    from app.dbi.models import DBIScientificRasterInputAsset, DBIScientificRasterBinding
    from app.dbi.scientific_raster_session_repository import _id
    sql = str(
        select(DBIScientificRasterSessionPreparation).where(
            DBIScientificRasterSessionPreparation.asset_id == request.asset_id,
        ).with_for_update().compile(dialect=postgresql.dialect())
    )
    assert "FOR UPDATE" in sql and "asset_id" in sql
    db.close()
    constraints = {x.name for x in DBIScientificRasterSessionPreparation.__table__.constraints}
    assert "fk_dbi_scientific_raster_preparation_asset_binding" in constraints
    assert "uq_dbi_scientific_raster_preparation_asset" in constraints
    assert "ck_dbi_scientific_raster_preparation_state" in constraints
    assert "ck_dbi_scientific_raster_preparation_plan" in constraints
    migration = (ROOT / "apps/platform-web/backend/dbi_alembic/versions/20261018_32_scientific_raster_session_preparations.py").read_text()
    assert 'down_revision: str | None = "dbi_0031_raster_asset"' in migration
    assert "cancelled_no_provider" in migration
    source = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_session_preparations.py").read_text()
    assert source.index("_locked_campaign(") < source.index("_verified_intent(")
    assert source.index("repository.prepare(") < source.index("session.commit()")
    for forbidden in ("presigned", "issue_part_access", "provider_upload_ref", "published=True"):
        assert forbidden not in source
    print("H14/2H-2D OK: 7 tickets idempotentes, cancellable, scoped, no-provider.")


if __name__ == "__main__":
    run_api()
    run_contract()
