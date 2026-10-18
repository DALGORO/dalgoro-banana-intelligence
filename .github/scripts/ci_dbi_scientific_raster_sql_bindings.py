"""CI offline H14/2H-2B: Campaign bloqueada, SQL scoped, sin permisos de carga."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-only-h14-sql-binding")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from ci_dbi_scientific_manifest_private import (  # noqa: E402
    CAMPAIGN, FARM, ORG, PLOT, DATE, Reader, context,
    fake_test_store, snapshot, denied,
)
from ci_dbi_scientific_raster_reservations import (  # noqa: E402
    req, make_manifest, submit,
)
from app.api.v1.dbi_scientific_raster_sql_bindings import (  # noqa: E402
    ScientificRasterBindingRequest, bind_private_raster_sql,
)
from app.dbi.authorization import DBIPermission  # noqa: E402
from app.dbi.models import DBIScientificRasterBinding  # noqa: E402
from app.dbi.scientific_raster_binding_repository import (  # noqa: E402
    DBIScientificRasterBindingRepository, ScientificRasterBindingConflict,
    ScientificRasterBindingIntent, _canonical, _same,
)
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402

FLAGS = {
    "DBI_SCIENTIFIC_MANIFEST_ENABLED": "1",
    "DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED": "1",
    "DBI_SCIENTIFIC_RASTER_SQL_BINDING_ENABLED": "1",
    "DBI_ENVIRONMENT": "test",
}


class SQLSessionDouble:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class LockedRepo:
    calls = 0

    def __init__(self, session):
        assert isinstance(session, SQLSessionDouble)

    def get_campaign_for_update(self, **kw):
        LockedRepo.calls += 1
        assert kw == {
            "campaign_id": CAMPAIGN, "tenant_ref": kw["tenant_ref"],
            "organization_ref": ORG, "farm_id": FARM, "plot_id": PLOT,
        }
        obj = Reader.current
        return SimpleNamespace(
            id=obj.campaign_id, tenant_ref=obj.tenant_ref,
            organization_ref=obj.organization_ref,
            farm_id=obj.farm_id, plot_id=obj.plot_id,
            analysis_type=obj.analysis_type,
            status=obj.status, approved_at=obj.approved_at,
            published_at=obj.published_at,
        )


class BindingRepo:
    rows = {}
    calls = 0

    def __init__(self, session):
        assert isinstance(session, SQLSessionDouble)

    def persist_binding(self, intent):
        BindingRepo.calls += 1
        _canonical(intent)
        key = intent.binding_id
        if key in self.rows:
            if self.rows[key] != intent:
                raise ScientificRasterBindingConflict("El vínculo existente diverge.")
            return SimpleNamespace(id=key), False
        self.rows[key] = intent
        return SimpleNamespace(id=key), True


def bind(store, manifest, slot, *, role="rgb", index="_", ctx=None, session=None,
         digest=None, slot_digest=None):
    db = session or SQLSessionDouble()
    response = Response()
    receipt = bind_private_raster_sql(
        ORG, FARM, PLOT, CAMPAIGN, role, index,
        ScientificRasterBindingRequest(
            schema_version="dbi-h14-sql-raster-binding-request.v1",
            manifest_sha256=digest or manifest.manifest_sha256,
            reservation_sha256=slot_digest or slot.reservation_sha256,
        ),
        req(store), response, db, ctx or context(),
    )
    assert response.headers["Cache-Control"] == "no-store"
    return receipt, db, response


def deny_bind(call, code, db=None):
    try:
        call()
    except HTTPException as err:
        assert err.status_code == code, (code, err.status_code, err.detail)
    else:
        raise AssertionError("Ruta SQL aceptó operación no autorizada.")
    if db is not None:
        assert db.commits == 0 and db.rollbacks == 1


def run_synthetic_route():
    store = DBIInMemoryObjectStore()
    with patch.dict(os.environ, FLAGS), patch(
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
    ):
        before = LockedRepo.calls
        dummy = SimpleNamespace(manifest_sha256="a" * 64)
        slot = SimpleNamespace(reservation_sha256="b" * 64)
        db = SQLSessionDouble()
        deny_bind(
            lambda: bind(store, dummy, slot, ctx=context(DBIPermission.READ), session=db),
            404, db,
        )
        assert LockedRepo.calls == before
        db = SQLSessionDouble()
        deny_bind(
            lambda: bind(store, dummy, slot, ctx=context(tenant="other"), session=db),
            404, db,
        )
        assert LockedRepo.calls == before
        # Sin manifiesto, no se admite el enlace transaccional.
        db = SQLSessionDouble()
        deny_bind(lambda: bind(store, dummy, slot, session=db), 404, db)
        assert BindingRepo.calls == 0
        manifest = make_manifest(store)
        slot, _ = submit(store, manifest.manifest_sha256)
        receipt, db, http = bind(store, manifest, slot)
        assert http.status_code == 201 and db.commits == 1 and db.rollbacks == 0
        assert receipt.created and receipt.state == "reserved_no_asset"
        assert receipt.binding_id in BindingRepo.rows
        assert receipt.manifest_sha256 == manifest.manifest_sha256
        assert receipt.reservation_sha256 == slot.reservation_sha256
        assert receipt.target_object_id == slot.reservation.target_object_id
        assert not any((
            receipt.asset_registered, receipt.session_initiated,
            receipt.grants_issued, receipt.file_received,
            receipt.content_verified, receipt.institutional_approved,
            receipt.published,
        ))
        repeated, db, http = bind(store, manifest, slot)
        assert http.status_code == 200 and db.commits == 1
        assert repeated.binding_id == receipt.binding_id and not repeated.created
        assert BindingRepo.calls == 2

        for changes in (
            {"analysis_type": "density"}, {"status": "APPROVED"},
            {"status": "PUBLISHED"}, {"approved_at": DATE},
            {"published_at": DATE}, {"organization_ref": "other"},
            {"campaign_id": UUID("91000000-0000-4000-8000-000000000099")},
        ):
            Reader.current = snapshot(**changes)
            db = SQLSessionDouble()
            deny_bind(lambda: bind(store, manifest, slot, session=db), 404, db)
        Reader.current = snapshot()

        for digests in (
            {"digest": "a" * 64}, {"slot_digest": "b" * 64},
        ):
            db = SQLSessionDouble()
            deny_bind(
                lambda d=digests, s=db: bind(store, manifest, slot, session=s, **d),
                409, db,
            )
        db = SQLSessionDouble()
        deny_bind(
            lambda: bind(store, manifest, slot, role="scientific_cog", index="_", session=db),
            422, db,
        )
        db = SQLSessionDouble()
        deny_bind(
            lambda: bind(store, manifest, slot, ctx=context(actor="second-operator"), session=db),
            409, db,
        )
        db = SQLSessionDouble()
        deny_bind(
            lambda: bind(store, manifest, slot, role="scientific_cog", index="ndvi",
                         session=db),
            404, db,
        )
        db = SQLSessionDouble()
        deny_bind(lambda: bind(None, manifest, slot, session=db), 503, db)
        assert len(BindingRepo.rows) == 1

    from app.api.v1 import get_api_router
    fragment = "/scientific-intake/private-raster-sql-bindings/"
    for environment, available in (("production", False), ("staging", False),
                                    ("", False), ("test", True)):
        with patch.dict(os.environ, {
            "DBI_SCIENTIFIC_RASTER_SQL_BINDING_ENABLED": "1",
            "DBI_ENVIRONMENT": environment,
        }):
            assert any(fragment in route.path for route in get_api_router().routes) is available
            if not available:
                db = SQLSessionDouble()
                deny_bind(lambda: bind(store, manifest, slot, session=db), 404, db)
    with patch.dict(os.environ, {"DBI_SCIENTIFIC_RASTER_SQL_BINDING_ENABLED": "0"}):
        db = SQLSessionDouble()
        deny_bind(lambda: bind(store, manifest, slot, session=db), 404, db)


def run_repository_contract():
    value = next(iter(BindingRepo.rows.values()))
    assert isinstance(value, ScientificRasterBindingIntent)
    assert _canonical(value) == value
    fake = SimpleNamespace(
        id=value.binding_id, **asdict(value),
        analysis_type="multispectral",
        asset_id=None, status="reserved_no_asset",
    )
    assert _same(fake, value)
    fake.status = "uploading"
    assert not _same(fake, value)
    fake.status = "reserved_no_asset"

    # Compilar las operaciones reales PostgreSQL, pero NO abrir una conexión.
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert
    statement = insert(DBIScientificRasterBinding).values(
        id=value.binding_id, tenant_ref=value.tenant_ref,
    ).on_conflict_do_nothing().returning(DBIScientificRasterBinding.id)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT DO NOTHING" in sql
    locked = str(
        select(DBIScientificRasterBinding).where(
            DBIScientificRasterBinding.tenant_ref == value.tenant_ref,
        ).with_for_update().compile(dialect=postgresql.dialect())
    )
    assert "FOR UPDATE" in locked and "tenant_ref" in locked
    constraints = DBIScientificRasterBinding.__table__.constraints
    names = {x.name for x in constraints}
    assert "uq_dbi_scientific_raster_binding_slot" in names
    assert "fk_dbi_scientific_raster_binding_campaign_scope" in names
    assert "ck_dbi_scientific_raster_binding_not_ready" in names
    for drift in (
        {"role": "qml_style"}, {"index_ref": "ndvi"},
        {"declared_sha256": "f" * 63},
        {"declared_size_bytes": 11 * 1024**3},
    ):
        mismatched = ScientificRasterBindingIntent(**{**asdict(value), **drift})
        try:
            _canonical(mismatched)
        except ScientificRasterBindingConflict:
            pass
        else:
            raise AssertionError("La validación SQL admitió un intento divergente.")

    # Una sesión real de SQLAlchemy no requiere base de datos para probar
    # insert -> SELECT FOR UPDATE -> comprobación inmutable.
    real_session = Session()
    rows = []

    def execute(stmt, *args, **kwargs):
        rows.append(str(stmt.compile(dialect=postgresql.dialect())))
        return SimpleNamespace(
            scalar_one_or_none=lambda: (
                value.binding_id if len(rows) % 2 == 1 else fake
            ),
        )

    with patch.object(real_session, "execute", execute):
        created, is_new = DBIScientificRasterBindingRepository(real_session).persist_binding(value)
        assert is_new and created.id == value.binding_id
        assert "ON CONFLICT DO NOTHING" in rows[0]
        assert "FOR UPDATE" in rows[1]
        assert "campaign_id" in rows[1]
        assert "index_ref" in rows[1]
    real_session.close()

    migration_path = ROOT / "apps/platform-web/backend/dbi_alembic/versions/20261018_30_scientific_raster_bindings.py"
    migration = migration_path.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "dbi_0029_staff_approval_guard"' in migration
    assert "fk_dbi_scientific_raster_binding_campaign_scope" in migration
    assert "uq_dbi_scientific_raster_binding_slot" in migration
    assert "asset_id IS NULL" in migration

    source = (ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_raster_sql_bindings.py").read_text()
    assert "get_campaign_for_update(" in source
    assert source.index("_locked_campaign(") < source.index("_manifest(")
    assert source.index("persist_binding(intent)") < source.index("session.commit()")
    assert "issue_part_access" not in source
    assert "presigned" not in source
    assert "published=True" not in source


def main():
    run_synthetic_route()
    run_repository_contract()
    print("H14/2H-2B OK: Campaign FOR UPDATE + binding SQL idempotente; Asset/Session no permitidos.")


if __name__ == "__main__":
    main()
