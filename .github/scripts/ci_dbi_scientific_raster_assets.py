"""CI H14/2H-2C: registrar 1 RGB + 6 COG sin bytes ni grants.

Cubre API con S3/DB dobles inyectados; repositorio real por compilación de
sentencias SQL. Migraciones en PostgreSQL efímero las comprueba el pipeline.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-h14-asset-only")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import (  # noqa: E402
    CAMPAIGN, FARM, ORG, PLOT, DATE, Reader, context, fake_test_store,
    snapshot,
)
from ci_dbi_scientific_raster_reservations import (  # noqa: E402
    PAIRS, req, make_manifest, submit,
)
from ci_dbi_scientific_raster_sql_bindings import (  # noqa: E402
    BindingRepo, LockedRepo, SQLSessionDouble, bind,
)
from app.api.v1.dbi_scientific_raster_assets import (  # noqa: E402
    ScientificRasterAssetRequest, register_private_raster_asset,
)
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.models import DBIScientificRasterInputAsset, DBIScientificRasterBinding  # noqa: E402
from app.dbi.scientific_raster_asset_repository import (  # noqa: E402
    DBIScientificRasterAssetRepository, ScientificRasterAssetConflict,
    scientific_asset_id, _asset_matches, _binding_matches,
)
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402


class AssetsDouble:
    assets = {}

    def __init__(self, db):
        assert isinstance(db, SQLSessionDouble)

    def register_asset(self, intent):
        assert intent.binding_id in BindingRepo.rows
        assert BindingRepo.rows[intent.binding_id] == intent
        asset_id = scientific_asset_id(intent)
        if asset_id in self.assets:
            return self.assets[asset_id], False
        asset = SimpleNamespace(
            id=asset_id, binding_id=intent.binding_id,
            asset_kind="orthophoto_rgb" if intent.role == "rgb" else "scientific_cog",
            target_object_id=intent.target_object_id,
            declared_size_bytes=intent.declared_size_bytes,
            declared_sha256=intent.declared_sha256,
        )
        self.assets[asset_id] = asset
        return asset, True


def call(store, manifest, slot, role="rgb", index="_", ctx=None, db=None,
         digest=None, slot_digest=None):
    db = db or SQLSessionDouble()
    response = Response()
    receipt = register_private_raster_asset(
        ORG, FARM, PLOT, CAMPAIGN, role, index,
        ScientificRasterAssetRequest(
            schema_version="dbi-h14-raster-asset-registration-request.v1",
            manifest_sha256=digest or manifest.manifest_sha256,
            reservation_sha256=slot_digest or slot.reservation_sha256,
        ),
        req(store), response, db, ctx or context(),
    )
    assert response.headers["Cache-Control"] == "no-store"
    return receipt, db, response


def denied(fn, code, db=None, rollback=True):
    try:
        fn()
    except HTTPException as error:
        assert error.status_code == code, (code, error.status_code, error.detail)
    else:
        raise AssertionError("Registro científico admitió un caso prohibido.")
    if db is not None:
        assert db.commits == 0
        assert db.rollbacks == (1 if rollback else 0)


def run_api():
    store = DBIInMemoryObjectStore()
    AssetsDouble.assets = {}
    BindingRepo.rows = {}
    with patch.dict(os.environ, {
        "DBI_SCIENTIFIC_MANIFEST_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_SQL_BINDING_ENABLED": "1",
        "DBI_SCIENTIFIC_RASTER_ASSET_REGISTRATION_ENABLED": "1",
        "DBI_ENVIRONMENT": "test",
    }), patch(
        "app.api.v1.dbi_scientific_manifest_private.DBICampaignReader", Reader,
    ), patch(
        "app.api.v1.dbi_scientific_manifest_private._store", fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_reservations._private_store", fake_test_store,
    ), patch(
        "app.api.v1.dbi_scientific_raster_sql_bindings.DBICampaignRepository", LockedRepo,
    ), patch(
        "app.api.v1.dbi_scientific_raster_sql_bindings.DBIScientificRasterBindingRepository",
        BindingRepo,
    ), patch(
        "app.api.v1.dbi_scientific_raster_assets.DBIScientificRasterAssetRepository",
        AssetsDouble,
    ):
        stub = SimpleNamespace(manifest_sha256="a" * 64)
        dummy = SimpleNamespace(reservation_sha256="b" * 64)
        db = SQLSessionDouble()
        denied(lambda: call(store, stub, dummy, db=db), 404, db)
        db = SQLSessionDouble()
        denied(lambda: call(store, stub, dummy, ctx=context(DBIPermission.READ), db=db), 404, db)
        db = SQLSessionDouble()
        denied(lambda: call(store, stub, dummy, ctx=context(tenant="alien"), db=db), 404, db)

        manifest = make_manifest(store)
        for role, index in PAIRS:
            slot, _ = submit(store, manifest.manifest_sha256, role, index)
            # Prior SQL binding is mandatory; reservation alone must be insufficient.
            db = SQLSessionDouble()
            denied(lambda s=db: call(store, manifest, slot, role, index, db=s), 409, db)
            b, _, _ = bind(store, manifest, slot, role=role, index=index)
            receipt, db, response = call(store, manifest, slot, role, index)
            assert response.status_code == 201 and db.commits == 1
            assert receipt.created is True and receipt.binding_id == b.binding_id
            assert receipt.asset_kind == ("orthophoto_rgb" if role == "rgb" else "scientific_cog")
            assert receipt.index == (None if index == "_" else index)
            assert receipt.declared_sha256 == slot.reservation.declared_sha256
            assert receipt.declared_size_bytes == slot.reservation.declared_size_bytes
            assert receipt.target_object_id == slot.reservation.target_object_id
            assert receipt.status == "registered_pending_bytes"
            assert not any((
                receipt.file_received, receipt.content_verified, receipt.session_started,
                receipt.grants_issued, receipt.institutional_approved, receipt.published,
            ))
            again, db, response = call(store, manifest, slot, role, index)
            assert response.status_code == 200 and not again.created and db.commits == 1
            assert again.asset_id == receipt.asset_id
            db = SQLSessionDouble()
            denied(lambda s=db: call(store, manifest, slot, role, index,
                                      ctx=context(actor="another"), db=s), 409, db)
            db = SQLSessionDouble()
            denied(lambda s=db: call(store, manifest, slot, role, index,
                                      digest="a" * 64, db=s), 409, db)
            db = SQLSessionDouble()
            denied(lambda s=db: call(store, manifest, slot, role, index,
                                      slot_digest="b" * 64, db=s), 409, db)
        assert len(AssetsDouble.assets) == 7

        for changes in ({"analysis_type": "density"}, {"status": "APPROVED"},
                        {"status": "PUBLISHED"}, {"approved_at": DATE},
                        {"published_at": DATE}, {"organization_ref": "other"}):
            Reader.current = snapshot(**changes)
            db = SQLSessionDouble()
            denied(lambda s=db: call(store, manifest, slot, "scientific_cog", "ci_green",
                                     db=s), 404, db)
        Reader.current = snapshot()
        db = SQLSessionDouble()
        denied(lambda: call(None, manifest, slot, "scientific_cog", "ci_green", db=db), 503, db)

    from app.api.v1 import get_api_router
    fragment = "/scientific-intake/private-raster-assets/"
    for env, enabled in (("production", False), ("staging", False),
                         ("", False), ("test", True), ("local", True)):
        with patch.dict(os.environ, {
            "DBI_SCIENTIFIC_RASTER_ASSET_REGISTRATION_ENABLED": "1",
            "DBI_ENVIRONMENT": env,
        }):
            assert any(fragment in route.path for route in get_api_router().routes) is enabled
            if not enabled:
                db = SQLSessionDouble()
                denied(lambda s=db: call(store, manifest, slot, "scientific_cog",
                                         "ci_green", db=s), 404, db, rollback=False)


def run_repository_contract():
    intent = next(iter(BindingRepo.rows.values()))
    aid = scientific_asset_id(intent)
    binding = SimpleNamespace(
        id=intent.binding_id, **asdict(intent), analysis_type="multispectral",
        status="reserved_no_asset", asset_id=None,
        created_at=datetime.now(timezone.utc),
    )
    # Avoid duplicate id from asdict; reconstruct as a normal record.
    fields = asdict(intent)
    fields.update(id=intent.binding_id, analysis_type="multispectral",
                  status="reserved_no_asset", asset_id=None,
                  created_at=datetime.now(timezone.utc))
    binding = SimpleNamespace(**fields)
    asset = SimpleNamespace(
        id=aid, binding_id=intent.binding_id, **{
            key: getattr(intent, key) for key in (
                "tenant_ref", "organization_ref", "farm_id", "plot_id",
                "campaign_id", "role", "index_ref", "target_object_id",
                "declared_size_bytes", "declared_sha256", "created_by_ref",
            )
        }, asset_kind="orthophoto_rgb" if intent.role == "rgb" else "scientific_cog",
        content_type="image/tiff", status="registered_pending_bytes",
        file_received=False, content_verified=False, session_started=False,
        institutional_approved=False, published=False,
    )
    assert _binding_matches(binding, intent, aid)
    assert _asset_matches(asset, intent, aid)
    asset.published = True
    assert not _asset_matches(asset, intent, aid)
    asset.published = False

    def exercise(replay=False):
        session = Session()
        statements = []
        if replay:
            binding.asset_id = aid
            binding.status = "asset_registered_pending_bytes"
        else:
            binding.asset_id = None
            binding.status = "reserved_no_asset"

        def execute(statement, *args, **kwargs):
            sql = str(statement.compile(dialect=postgresql.dialect()))
            statements.append(sql)
            idx = len(statements)
            result = binding if idx == 1 else (None if replay else aid) if idx == 2 else asset
            return SimpleNamespace(scalar_one_or_none=lambda: result)

        with patch.object(session, "execute", execute), patch.object(session, "flush"):
            returned, created = DBIScientificRasterAssetRepository(session).register_asset(intent)
        session.close()
        assert returned is asset and created is not replay
        assert len(statements) == 3
        assert all("FOR UPDATE" in sql for sql in (statements[0], statements[2]))
        assert "ON CONFLICT DO NOTHING" in statements[1]
        assert "campaign_id" in statements[0] and "tenant_ref" in statements[0]
        assert binding.asset_id == aid and binding.status == "asset_registered_pending_bytes"

    exercise(False)
    exercise(True)
    schema = DBIScientificRasterInputAsset.__table__
    names = {constraint.name for constraint in schema.constraints}
    assert {
        "fk_dbi_scientific_raster_asset_binding_scope",
        "uq_dbi_scientific_raster_asset_binding",
        "ck_dbi_scientific_raster_asset_kind_role",
        "ck_dbi_scientific_raster_asset_no_bytes",
    } <= names
    assert any(x.name == "fk_dbi_scientific_raster_binding_asset_exact"
               for x in DBIScientificRasterBinding.__table__.constraints)
    migration = (ROOT / "apps/platform-web/backend/dbi_alembic/versions/20261018_31_scientific_raster_assets.py").read_text()
    assert 'down_revision: str | None = "dbi_0030_raster_binding"' in migration
    assert "registered_pending_bytes" in migration
    assert "fk_dbi_scientific_raster_binding_asset_exact" in migration
    source = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_assets.py").read_text()
    assert source.index("_locked_campaign(") < source.index("_manifest(")
    assert source.index("register_asset(intent)") < source.index("session.commit()")
    for forbidden in ("issue_part_access", "session_initiated=True", "presigned", "published=True"):
        assert forbidden not in source


if __name__ == "__main__":
    run_api()
    run_repository_contract()
    print("H14/2H-2C OK: 7 activos registrados SQL, cero bytes/sesiones/grants.")
