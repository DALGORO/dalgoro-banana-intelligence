"""Integración PostgreSQL/PostGIS de DBI-SAMPLING-001."""

from __future__ import annotations

import inspect
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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

from app.dbi.models.sampling import (  # noqa: E402
    DBISamplingPlanRecord,
    DBISamplingPointRecord,
)
from app.dbi.sampling import (  # noqa: E402
    DBISamplingConflict,
    DBISamplingPlanService,
    DBISamplingProfile,
    DBISamplingUnavailable,
)
from app.dbi.sampling.field import DBISamplingFieldService  # noqa: E402
from app.dbi.sampling.repository import point_coordinates  # noqa: E402
from app.dbi.spatial import GeoJSONMultiPolygon  # noqa: E402

HOST = "127.0.0.1"
PORT = 5432
DATABASE = "dbi_test"
ADMIN_ROLE = "postgres"
SAMPLING_ROLE = "dbi_test_sampling"
TENANT = "tenant-sampling-ci"
ORGANIZATION = "organization-sampling-ci"
FARM_ID = UUID("10000000-0000-4000-8000-000000000078")
PLOT_ID = UUID("20000000-0000-4000-8000-000000000078")
BOUNDARY_WKT = (
    "MULTIPOLYGON((("
    "-79.8100 -3.3000,"
    "-79.8000 -3.3000,"
    "-79.8000 -3.2920,"
    "-79.8100 -3.2920,"
    "-79.8100 -3.3000"
    ")))"
)


def _multipolygon(min_lon, min_lat, max_lon, max_lat) -> GeoJSONMultiPolygon:
    return GeoJSONMultiPolygon.model_validate(
        {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [min_lon, min_lat],
                        [max_lon, min_lat],
                        [max_lon, max_lat],
                        [min_lon, max_lat],
                        [min_lon, min_lat],
                    ]
                ]
            ],
        }
    )


EXCLUSION = _multipolygon(-79.8060, -3.2975, -79.8045, -3.2940)
CROSSING_EXCLUSION = _multipolygon(-79.8120, -3.2980, -79.8050, -3.2940)


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración Sampling sólo corre en GitHub Actions.")
    if os.environ.get("DBI_SAMPLING_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta habilitar DBI_SAMPLING_RUN_INTEGRATION.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración Sampling exige DBI_ENVIRONMENT=test.")
    url = os.environ.get("DBI_DATABASE_URL", "")
    if SAMPLING_ROLE not in url or HOST not in url or DATABASE not in url:
        raise RuntimeError("DBI_DATABASE_URL no apunta al rol Sampling autorizado.")


def _admin_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=ADMIN_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _url() -> str:
    return f"postgresql+psycopg://{SAMPLING_ROLE}@{HOST}:{PORT}/{DATABASE}"


def _factory():
    engine = create_engine(_url(), poolclass=NullPool, future=True)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _provision_role_and_fixture() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (SAMPLING_ROLE,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(SAMPLING_ROLE))
                )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DATABASE), sql.Identifier(SAMPLING_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(SAMPLING_ROLE)
                )
            )
            for table_name in (
                "dbi_farms",
                "dbi_plots",
                "dbi_sampling_plans",
                "dbi_sampling_points",
            ):
                cursor.execute(
                    sql.SQL("GRANT SELECT ON dbi.{} TO {}").format(
                        sql.Identifier(table_name), sql.Identifier(SAMPLING_ROLE)
                    )
                )
            cursor.execute(
                sql.SQL("GRANT INSERT ON dbi.dbi_sampling_plans TO {}").format(
                    sql.Identifier(SAMPLING_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT INSERT ON dbi.dbi_sampling_points TO {}").format(
                    sql.Identifier(SAMPLING_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, updated_at) ON dbi.dbi_sampling_plans TO {}"
                ).format(sql.Identifier(SAMPLING_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, rejection_reason, observed_point, observed_at, updated_at) "
                    "ON dbi.dbi_sampling_points TO {}"
                ).format(sql.Identifier(SAMPLING_ROLE))
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(SAMPLING_ROLE)
                )
            )

            cursor.execute(
                """
                INSERT INTO dbi.dbi_farms
                    (id, organization_ref, code, name, status, created_at, updated_at)
                VALUES (%s, %s, 'CI-SAMPLING-FARM', 'Finca Sampling CI', 'active',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    organization_ref = EXCLUDED.organization_ref,
                    status = 'active',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (FARM_ID, ORGANIZATION),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_plots
                    (id, farm_id, code, name, area_hectares, boundary, status,
                     created_at, updated_at)
                VALUES (%s, %s, 'CI-SAMPLING-PLOT', 'Lote Sampling CI', 80.0,
                        ST_GeomFromText(%s, 4326), 'active',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    boundary = EXCLUDED.boundary,
                    status = 'active',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (PLOT_ID, FARM_ID, BOUNDARY_WKT),
            )


def _profile(version: str) -> DBISamplingProfile:
    return DBISamplingProfile(
        profile_version=version,
        field_budget_minutes=120.0,
        sample_minutes=3.0,
        travel_minutes_per_sample=1.5,
        fixed_overhead_minutes=0,
        edge_buffer_m=8.0,
        min_spacing_m=25.0,
        search_radius_m=12.0,
        candidate_multiplier=24,
        reserve_ratio=0.35,
        min_primary_target=20,
        max_primary_points=35,
        max_reserve_points=12,
        seed=17,
    )


def _create(factory, *, version: str, exclusions=(EXCLUSION,), actor="sampling-ci"):
    session = factory()
    try:
        evidence = DBISamplingPlanService(session).create_plan(
            tenant_ref=TENANT,
            organization_ref=ORGANIZATION,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            profile=_profile(version),
            created_by_ref=actor,
            exclusions=tuple(exclusions),
        )
        session.commit()
        return evidence
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def validate_authority_and_replay(factory) -> None:
    signature = inspect.signature(DBISamplingPlanService.create_plan)
    assert "boundary" not in signature.parameters

    first = _create(factory, version="sampling-postgis-v1", actor="actor-first")
    replay = _create(factory, version="sampling-postgis-v1", actor="actor-replay")
    assert first.created is True
    assert replay.created is False
    assert replay.plan_id == first.plan_id
    assert first.primary_count == 26
    assert first.reserve_count == 10

    session = factory()
    try:
        assert session.scalar(
            select(func.count()).select_from(DBISamplingPlanRecord).where(
                DBISamplingPlanRecord.id == first.plan_id
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(DBISamplingPointRecord).where(
                DBISamplingPointRecord.plan_id == first.plan_id
            )
        ) == 36
    finally:
        session.close()

    session = factory()
    try:
        try:
            DBISamplingPlanService(session).create_plan(
                tenant_ref=TENANT,
                organization_ref="organization-sampling-foreign",
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                profile=_profile("sampling-foreign-v1"),
                created_by_ref="actor-foreign",
            )
        except DBISamplingUnavailable:
            session.rollback()
        else:
            raise AssertionError("Una organización ajena resolvió el lote Sampling.")
    finally:
        session.close()


def validate_concurrency(factory) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda index: _create(
                    factory,
                    version="sampling-concurrent-v1",
                    actor=f"actor-concurrent-{index}",
                ),
                range(2),
            )
        )
    assert sorted(item.created for item in outcomes) == [False, True]
    assert len({item.plan_id for item in outcomes}) == 1

    session = factory()
    try:
        plan_id = outcomes[0].plan_id
        assert session.scalar(
            select(func.count()).select_from(DBISamplingPlanRecord).where(
                DBISamplingPlanRecord.id == plan_id
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(DBISamplingPointRecord).where(
                DBISamplingPointRecord.plan_id == plan_id
            )
        ) == 36
    finally:
        session.close()


def validate_exclusion_clipping(factory) -> None:
    evidence = _create(
        factory,
        version="sampling-clipped-exclusion-v1",
        exclusions=(CROSSING_EXCLUSION,),
    )
    session = factory()
    try:
        row = session.get(DBISamplingPlanRecord, evidence.plan_id)
        assert row is not None and row.exclusions_snapshot is not None
        assert session.scalar(
            select(
                func.ST_CoveredBy(
                    DBISamplingPlanRecord.exclusions_snapshot,
                    DBISamplingPlanRecord.boundary_snapshot,
                )
            ).where(DBISamplingPlanRecord.id == evidence.plan_id)
        ) is True
        assert session.scalar(
            select(func.count()).select_from(DBISamplingPointRecord).where(
                DBISamplingPointRecord.plan_id == evidence.plan_id,
                func.ST_Covers(
                    row.exclusions_snapshot,
                    DBISamplingPointRecord.planned_point,
                ),
            )
        ) == 0
    finally:
        session.close()


def validate_field_lifecycle(factory) -> None:
    evidence = _create(factory, version="sampling-field-v1", exclusions=())
    observed_at = datetime.now(timezone.utc)

    session = factory()
    try:
        points = session.execute(
            select(DBISamplingPointRecord)
            .where(DBISamplingPointRecord.plan_id == evidence.plan_id)
            .order_by(DBISamplingPointRecord.role, DBISamplingPointRecord.sequence)
        ).scalars().all()
        primaries = [point for point in points if point.role == "primary"]
        reserves = [point for point in points if point.role == "reserve"]
        primary = primaries[0]
        longitude, latitude = point_coordinates(primary.planned_point)
        mutation = DBISamplingFieldService(session).validate_point(
            plan_id=evidence.plan_id,
            point_id=primary.id,
            tenant_ref=TENANT,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            longitude=longitude,
            latitude=latitude,
            observed_at=observed_at,
        )
        assert mutation.changed is True and mutation.status == "validated"
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        replay = DBISamplingFieldService(session).validate_point(
            plan_id=evidence.plan_id,
            point_id=primary.id,
            tenant_ref=TENANT,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            longitude=longitude,
            latitude=latitude,
            observed_at=observed_at,
        )
        assert replay.changed is False
        session.commit()
    finally:
        session.close()

    reserve = next(
        item for item in reserves if item.reserve_for_sequence != primary.sequence
    )
    parent = next(
        item for item in primaries if item.sequence == reserve.reserve_for_sequence
    )
    reserve_lon, reserve_lat = point_coordinates(reserve.planned_point)
    substitution_at = datetime.now(timezone.utc)
    session = factory()
    try:
        substitution = DBISamplingFieldService(session).substitute_point(
            plan_id=evidence.plan_id,
            primary_point_id=parent.id,
            reserve_point_id=reserve.id,
            tenant_ref=TENANT,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            rejection_reason="missing_plant",
            longitude=reserve_lon,
            latitude=reserve_lat,
            observed_at=substitution_at,
        )
        assert substitution.changed is True
        assert substitution.status == "substituted"
        assert substitution.reserve_point_id == reserve.id
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        replay = DBISamplingFieldService(session).substitute_point(
            plan_id=evidence.plan_id,
            primary_point_id=parent.id,
            reserve_point_id=reserve.id,
            tenant_ref=TENANT,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            rejection_reason="missing_plant",
            longitude=reserve_lon,
            latitude=reserve_lat,
            observed_at=substitution_at,
        )
        assert replay.changed is False
        session.commit()
    finally:
        session.close()

    rejected = next(
        item
        for item in primaries
        if item.id not in {primary.id, parent.id}
    )
    reject_at = datetime.now(timezone.utc)
    session = factory()
    try:
        rejection = DBISamplingFieldService(session).reject_point(
            plan_id=evidence.plan_id,
            point_id=rejected.id,
            tenant_ref=TENANT,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            rejection_reason="unsafe",
            observed_at=reject_at,
        )
        assert rejection.changed is True and rejection.status == "rejected"
        session.commit()
    finally:
        session.close()

    candidate = next(
        item
        for item in primaries
        if item.id not in {primary.id, parent.id, rejected.id}
    )
    candidate_lon, candidate_lat = point_coordinates(candidate.planned_point)
    session = factory()
    try:
        try:
            DBISamplingFieldService(session).validate_point(
                plan_id=evidence.plan_id,
                point_id=candidate.id,
                tenant_ref=TENANT,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                longitude=candidate_lon + 0.001,
                latitude=candidate_lat,
                observed_at=datetime.now(timezone.utc),
            )
        except DBISamplingConflict:
            session.rollback()
        else:
            raise AssertionError("Una observación fuera del radio GPS debía fallar.")
    finally:
        session.close()

    session = factory()
    try:
        try:
            DBISamplingFieldService(session).complete_plan(
                plan_id=evidence.plan_id,
                tenant_ref=TENANT,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            )
        except DBISamplingConflict:
            session.rollback()
        else:
            raise AssertionError("No se debe completar un plan con primarias pendientes.")
    finally:
        session.close()

    session = factory()
    try:
        plan = session.get(DBISamplingPlanRecord, evidence.plan_id)
        assert plan is not None and plan.status == "in_field"
        persisted_primary = session.get(DBISamplingPointRecord, primary.id)
        persisted_parent = session.get(DBISamplingPointRecord, parent.id)
        persisted_reserve = session.get(DBISamplingPointRecord, reserve.id)
        assert persisted_primary is not None and persisted_primary.status == "validated"
        assert persisted_parent is not None and persisted_parent.status == "substituted"
        assert persisted_reserve is not None and persisted_reserve.status == "validated"
    finally:
        session.close()


def _sampling_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=SAMPLING_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _assert_denied(statement: str) -> None:
    with _sampling_connect() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(statement)
            except psycopg.errors.InsufficientPrivilege:
                return
    raise AssertionError("El rol Sampling obtuvo una mutación no autorizada.")


def validate_acl() -> None:
    _assert_denied("UPDATE dbi.dbi_analysis_jobs SET status = status")
    _assert_denied("DELETE FROM dbi.dbi_sampling_plans")
    _assert_denied("UPDATE dbi.dbi_sampling_plans SET profile_json = profile_json")
    _assert_denied("UPDATE dbi.dbi_sampling_points SET planned_point = planned_point")
    _assert_denied("UPDATE dbi.dbi_farms SET name = name")


def main() -> None:
    _require_scope()
    _provision_role_and_fixture()
    engine, factory = _factory()
    try:
        validate_authority_and_replay(factory)
        validate_concurrency(factory)
        validate_exclusion_clipping(factory)
        validate_field_lifecycle(factory)
        validate_acl()
    finally:
        engine.dispose()
    print(
        "DBI-SAMPLING-001 PostGIS aprobado: authority, replay, concurrencia, campo, exclusiones y ACL."
    )


if __name__ == "__main__":
    main()
