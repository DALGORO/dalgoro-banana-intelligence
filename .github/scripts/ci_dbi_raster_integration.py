"""Integración PostgreSQL/PostGIS de DBI-RASTER-001 con Storage privado."""

from __future__ import annotations

import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.models.raster_products import DBIRasterProduct  # noqa: E402
from app.dbi.raster.contracts import (  # noqa: E402
    DBIRasterConflict,
    DBIRasterProductCandidate,
    DBIRasterProductKind,
    DBIRasterSourceKind,
    raster_product_id,
)
from app.dbi.raster.service import (  # noqa: E402
    DBIRasterProductService,
    DBIRasterUnavailable,
)
from app.dbi.storage_contracts import (  # noqa: E402
    DBIStoragePurpose,
    DBIStorageWriteRequest,
)
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from ci_dbi_worker_integration import (  # noqa: E402
    ADMIN_ROLE,
    DATABASE,
    FARM_ID,
    HOST,
    ORTHO_ID,
    ORTHO_PAYLOAD,
    PLOT_ID,
    PORT,
    TENANT,
    _admin_connect,
    _object_store,
    _provision_role_and_shared_fixture,
)

RASTER_ROLE = "dbi_test_raster"
COG_PAYLOAD = (b"dbi-cog-raster-ci-v1" * 4096) + b"EOF"
COG_SHA = hashlib.sha256(COG_PAYLOAD).hexdigest()
SOURCE_SHA = hashlib.sha256(ORTHO_PAYLOAD).hexdigest()


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración Raster sólo corre en GitHub Actions.")
    if os.environ.get("DBI_RASTER_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta habilitar DBI_RASTER_RUN_INTEGRATION.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración Raster exige DBI_ENVIRONMENT=test.")
    url = os.environ.get("DBI_DATABASE_URL", "")
    if RASTER_ROLE not in url or HOST not in url or DATABASE not in url:
        raise RuntimeError("DBI_DATABASE_URL no apunta al rol Raster autorizado.")


def _url(role: str) -> str:
    return f"postgresql+psycopg://{role}@{HOST}:{PORT}/{DATABASE}"


def _factory(role: str):
    engine = create_engine(_url(role), poolclass=NullPool, future=True)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _provision_raster_role() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RASTER_ROLE,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(RASTER_ROLE))
                )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DATABASE), sql.Identifier(RASTER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(RASTER_ROLE)
                )
            )
            for table_name in (
                "dbi_analysis_input_assets",
                "dbi_analysis_artifacts",
                "dbi_analysis_jobs",
                "dbi_raster_products",
            ):
                cursor.execute(
                    sql.SQL("GRANT SELECT ON dbi.{} TO {}").format(
                        sql.Identifier(table_name), sql.Identifier(RASTER_ROLE)
                    )
                )
            cursor.execute(
                sql.SQL("GRANT INSERT ON dbi.dbi_raster_products TO {}").format(
                    sql.Identifier(RASTER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(RASTER_ROLE)
                )
            )


def _raster_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=RASTER_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _assert_denied(statement: str) -> None:
    with _raster_connect() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(statement)
            except psycopg.errors.InsufficientPrivilege:
                return
    raise AssertionError("el rol Raster obtuvo una mutación no autorizada.")


def validate_acl() -> None:
    _assert_denied("UPDATE dbi.dbi_analysis_jobs SET status = status")
    _assert_denied("UPDATE dbi.dbi_analysis_results SET status = status")
    _assert_denied("UPDATE dbi.dbi_farms SET name = name")
    _assert_denied("UPDATE dbi.dbi_raster_products SET status = status")
    _assert_denied("DELETE FROM dbi.dbi_raster_products")


def _candidate(profile: str = "cog_v1") -> DBIRasterProductCandidate:
    product_id = raster_product_id(
        source_kind=DBIRasterSourceKind.INPUT_ASSET,
        source_ref=ORTHO_ID,
        source_sha256=SOURCE_SHA,
        product_kind=DBIRasterProductKind.RGB_VISUAL,
        profile_version=profile,
    )
    return DBIRasterProductCandidate(
        source_kind=DBIRasterSourceKind.INPUT_ASSET,
        source_ref=ORTHO_ID,
        source_sha256=SOURCE_SHA,
        product_kind=DBIRasterProductKind.RGB_VISUAL,
        profile_version=profile,
        generator_version="raster-ci-v1",
        object_id=product_id,
        content_type="image/tiff",
        size_bytes=len(COG_PAYLOAD),
        sha256=COG_SHA,
        crs="EPSG:32717",
        width=4096,
        height=3072,
        band_count=3,
        dtype="uint8",
        transform=(0.03, 0.0, 620000.0, 0.0, -0.03, 9640000.0),
        bounds=(620000.0, 9639907.84, 620122.88, 9640000.0),
        nodata=(None, None, None),
        scales=(1.0, 1.0, 1.0),
        offsets=(0.0, 0.0, 0.0),
        block_width=512,
        block_height=512,
        compression="deflate",
        overview_levels=(2, 4, 8),
    )


def _put_cog(store, candidate: DBIRasterProductCandidate) -> None:
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref=TENANT,
            purpose=DBIStoragePurpose.RASTER_PRODUCT,
            object_id=candidate.object_id,
        ),
        content_type=candidate.content_type,
        size_bytes=candidate.size_bytes,
        sha256_hex=candidate.sha256,
    )
    store.put(DBIStorageWriteRequest(metadata=metadata), BytesIO(COG_PAYLOAD))


def _register(factory, store, candidate: DBIRasterProductCandidate):
    session = factory()
    try:
        evidence = DBIRasterProductService(session, store).register_ready(
            candidate,
            tenant_ref=TENANT,
        )
        session.commit()
        return evidence
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def validate_success_replay_and_conflicts(factory) -> None:
    store = _object_store()
    candidate = _candidate()
    _put_cog(store, candidate)

    first = _register(factory, store, candidate)
    assert first.created is True
    replay = _register(factory, store, candidate)
    assert replay.created is False
    assert replay.product_id == first.product_id

    session = factory()
    try:
        assert session.scalar(
            select(func.count()).select_from(DBIRasterProduct).where(
                DBIRasterProduct.id == candidate.object_id
            )
        ) == 1
    finally:
        session.close()

    divergent = replace(candidate, sha256="c" * 64)
    session = factory()
    try:
        try:
            DBIRasterProductService(session, store).register_ready(
                divergent,
                tenant_ref=TENANT,
            )
        except DBIRasterConflict:
            session.rollback()
        else:
            raise AssertionError("Storage divergente no fue rechazado.")
    finally:
        session.close()

    missing = _candidate("cog_missing_v1")
    session = factory()
    try:
        try:
            DBIRasterProductService(session, store).register_ready(
                missing,
                tenant_ref=TENANT,
            )
        except DBIRasterUnavailable:
            session.rollback()
        else:
            raise AssertionError("COG ausente no fue rechazado.")
    finally:
        session.close()

    session = factory()
    try:
        try:
            DBIRasterProductService(session, store).register_ready(
                candidate,
                tenant_ref="tenant-ci-raster-foreign",
            )
        except DBIRasterUnavailable:
            session.rollback()
        else:
            raise AssertionError("Tenant ajeno pudo resolver la ortofoto.")
    finally:
        session.close()


def validate_concurrency(factory) -> None:
    store = _object_store()
    candidate = _candidate("cog_concurrent_v1")
    _put_cog(store, candidate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(lambda _: _register(factory, store, candidate), range(2))
        )
    assert sorted(evidence.created for evidence in outcomes) == [False, True]
    assert len({evidence.product_id for evidence in outcomes}) == 1

    session = factory()
    try:
        assert session.scalar(
            select(func.count()).select_from(DBIRasterProduct).where(
                DBIRasterProduct.id == candidate.object_id
            )
        ) == 1
    finally:
        session.close()


def main() -> None:
    _require_scope()
    _provision_role_and_shared_fixture()
    _provision_raster_role()
    engine, factory = _factory(RASTER_ROLE)
    try:
        validate_success_replay_and_conflicts(factory)
        validate_concurrency(factory)
        validate_acl()
    finally:
        engine.dispose()
    print(
        "DBI-RASTER-001 PostGIS aprobado: COG privado, replay, concurrencia, tenant y ACL."
    )


if __name__ == "__main__":
    main()
