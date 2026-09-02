"""Integración real de DBI-JOB-003 sobre PostgreSQL/PostGIS efímero."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import func, select, update

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import load_dbi_database_config  # noqa: E402
from app.db.dbi_session import (  # noqa: E402
    create_dbi_engine,
    create_dbi_session_factory,
)
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.jobs.persistence_contracts import (  # noqa: E402
    AnalysisJobPersistenceConflict,
    AnalysisJobResourceUnavailable,
)
from app.dbi.jobs.repository import DBIAnalysisJobRepository  # noqa: E402
from app.dbi.jobs.service import DBIAnalysisJobService  # noqa: E402
from app.dbi.jobs.service_contracts import (  # noqa: E402
    AnalysisJobCreateRequest,
    AnalysisProfileResolutionContext,
    ApprovedAnalysisProfile,
)
from app.dbi.jobs.state_machine import (  # noqa: E402
    AnalysisJobStatus,
    InvalidAnalysisJobTransition,
)
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt  # noqa: E402
from app.dbi.models.assets import AnalysisInputAsset  # noqa: E402

HOST = "127.0.0.1"
PORT = 5432
DATABASE = "dbi_test"
ADMIN_ROLE = "postgres"
API_ROLE = "dbi_test_analysis_job_api"
ORGANIZATION = "organization-ci-job"
TENANT_A = "tenant-ci-job-a"
TENANT_B = "tenant-ci-job-b"
FARM_ID = UUID("81000000-0000-4000-8000-000000000001")
PLOT_ID = UUID("82000000-0000-4000-8000-000000000001")
CAMPAIGN_ID = UUID("83000000-0000-4000-8000-000000000001")
ORTHO_A = UUID("84000000-0000-4000-8000-000000000001")
ORTHO_A_ALT = UUID("84000000-0000-4000-8000-000000000002")
BOUNDARY_A = UUID("85000000-0000-4000-8000-000000000001")
EXCLUSIONS_A = UUID("86000000-0000-4000-8000-000000000001")
ORTHO_B = UUID("84000000-0000-4000-8000-000000000003")
BOUNDARY_B = UUID("85000000-0000-4000-8000-000000000002")
EXCLUSIONS_B = UUID("86000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 8, 4, 23, 0, tzinfo=timezone.utc)
REQUEST_ID = "request-ci-job-concurrent"


def _require_ci_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración de trabajos solo corre en GitHub Actions.")
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL heredada no está permitida.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración de trabajos exige DBI_ENVIRONMENT=test.")
    if os.environ.get("DBI_ANALYSIS_JOB_RUN_INTEGRATION") != "1":
        raise RuntimeError("La integración de trabajos no fue habilitada.")
    config = load_dbi_database_config()
    identity = (
        config.database_name,
        config.url.username,
        config.url.host,
        config.url.port,
    )
    if identity != (DATABASE, API_ROLE, HOST, PORT):
        raise RuntimeError("DBI_DATABASE_URL no apunta al fixture de trabajos.")


def _admin_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=ADMIN_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _provision_role_and_fixture() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (API_ROLE,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(API_ROLE))
                )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DATABASE), sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON SCHEMA dbi FROM {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA dbi FROM {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT ON TABLE dbi.dbi_farms, dbi.dbi_plots, "
                    "dbi.dbi_campaigns, dbi.dbi_analysis_input_assets, "
                    "dbi.dbi_analysis_jobs, dbi.dbi_analysis_job_attempts TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL("GRANT INSERT ON TABLE dbi.dbi_analysis_jobs TO {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, updated_at) ON TABLE "
                    "dbi.dbi_analysis_jobs TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            # PostgreSQL exige algún UPDATE para SELECT ... FOR UPDATE. Se limita
            # a updated_at; el servicio de trabajos nunca escribe esas tablas.
            for table_name in (
                "dbi_farms",
                "dbi_plots",
                "dbi_campaigns",
                "dbi_analysis_input_assets",
            ):
                cursor.execute(
                    sql.SQL("GRANT UPDATE (updated_at) ON TABLE dbi.{} TO {}").format(
                        sql.Identifier(table_name),
                        sql.Identifier(API_ROLE),
                    )
                )

            cursor.execute(
                """
                INSERT INTO dbi.dbi_farms
                    (id, organization_ref, code, name, status, created_at, updated_at)
                VALUES (%s, %s, 'CI-JOB-FARM', 'CI Job Farm', 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (FARM_ID, ORGANIZATION, NOW, NOW),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_plots
                    (id, farm_id, code, name, area_hectares, boundary,
                     status, created_at, updated_at)
                VALUES (%s, %s, 'CI-JOB-PLOT', 'CI Job Plot', 1.0, NULL,
                        'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (PLOT_ID, FARM_ID, NOW, NOW),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_campaigns
                    (id, farm_id, code, name, starts_at, ends_at,
                     status, created_at, updated_at)
                VALUES (%s, %s, 'CI-JOB-CAMPAIGN', 'CI Job Campaign', %s, NULL,
                        'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (CAMPAIGN_ID, FARM_ID, NOW, NOW, NOW),
            )

            assets = (
                (ORTHO_A, TENANT_A, "orthophoto", "ci/job/a/orthophoto.tif", "a" * 64),
                (ORTHO_A_ALT, TENANT_A, "orthophoto", "ci/job/a/orthophoto-alt.tif", "b" * 64),
                (BOUNDARY_A, TENANT_A, "boundary", "ci/job/a/boundary.geojson", "c" * 64),
                (EXCLUSIONS_A, TENANT_A, "exclusions", "ci/job/a/exclusions.geojson", "d" * 64),
                (ORTHO_B, TENANT_B, "orthophoto", "ci/job/b/orthophoto.tif", "e" * 64),
                (BOUNDARY_B, TENANT_B, "boundary", "ci/job/b/boundary.geojson", "f" * 64),
                (EXCLUSIONS_B, TENANT_B, "exclusions", "ci/job/b/exclusions.geojson", "1" * 64),
            )
            cursor.executemany(
                """
                INSERT INTO dbi.dbi_analysis_input_assets
                    (id, tenant_ref, farm_id, plot_id, asset_kind, status,
                     object_key, content_type, size_bytes, sha256, crs,
                     created_by_ref, verified_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'verified', %s, %s, 1024, %s,
                        'EPSG:32717', 'principal-ci-job', %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                tuple(
                    (
                        asset_id,
                        tenant_ref,
                        FARM_ID,
                        PLOT_ID,
                        asset_kind,
                        object_key,
                        "image/tiff" if asset_kind == "orthophoto" else "application/geo+json",
                        digest,
                        NOW,
                        NOW,
                        NOW,
                    )
                    for asset_id, tenant_ref, asset_kind, object_key, digest in assets
                ),
            )


def _context(tenant_ref: str) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref=f"principal-{tenant_ref}",
        tenant_ref=tenant_ref,
        organization_refs=frozenset({ORGANIZATION}),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref=ORGANIZATION, farm_id=FARM_ID)}
        ),
        plot_scopes=frozenset(
            {
                DBIPlotScope(
                    organization_ref=ORGANIZATION,
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                )
            }
        ),
        permissions=frozenset({DBIPermission.SUBMIT_ANALYSIS}),
    )


class _StaticProfilePolicy:
    def resolve(
        self,
        *,
        context: AnalysisProfileResolutionContext,
    ) -> ApprovedAnalysisProfile:
        if context.farm_id != FARM_ID or context.plot_id != PLOT_ID:
            raise AssertionError("La política recibió un ámbito inesperado.")
        return ApprovedAnalysisProfile(
            model_version_id="banana-density-ci-champion",
            pipeline_config_version="pipeline-ci-v1",
            policy_ref="policy-ci-v1",
        )


def _request(tenant_ref: str, *, orthophoto_id: UUID | None = None):
    if tenant_ref == TENANT_A:
        return AnalysisJobCreateRequest(
            request_id=REQUEST_ID,
            campaign_id=CAMPAIGN_ID,
            orthophoto_asset_id=orthophoto_id or ORTHO_A,
            boundary_asset_id=BOUNDARY_A,
            exclusions_asset_id=EXCLUSIONS_A,
        )
    return AnalysisJobCreateRequest(
        request_id=REQUEST_ID,
        campaign_id=CAMPAIGN_ID,
        orthophoto_asset_id=ORTHO_B,
        boundary_asset_id=BOUNDARY_B,
        exclusions_asset_id=EXCLUSIONS_B,
    )


def _submit(factory, tenant_ref: str, accepted_at: datetime):
    session = factory()
    try:
        evidence = DBIAnalysisJobService(DBIAnalysisJobRepository(session)).create(
            _context(tenant_ref),
            organization_ref=ORGANIZATION,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            request=_request(tenant_ref),
            profile_policy=_StaticProfilePolicy(),
            accepted_at=accepted_at,
        )
        session.commit()
        return evidence
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _cancel(factory, job_id: UUID):
    session = factory()
    try:
        evidence = DBIAnalysisJobService(DBIAnalysisJobRepository(session)).cancel(
            _context(TENANT_A),
            organization_ref=ORGANIZATION,
            farm_id=FARM_ID,
            job_id=job_id,
            changed_at=NOW + timedelta(minutes=10),
        )
        session.commit()
        return evidence
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _retry(factory, job_id: UUID):
    session = factory()
    try:
        evidence = DBIAnalysisJobService(DBIAnalysisJobRepository(session)).retry(
            _context(TENANT_A),
            organization_ref=ORGANIZATION,
            farm_id=FARM_ID,
            job_id=job_id,
            changed_at=NOW + timedelta(minutes=20),
        )
        session.commit()
        return evidence
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    _require_ci_scope()
    _provision_role_and_fixture()
    config = load_dbi_database_config()
    engine = create_dbi_engine(config)
    factory = create_dbi_session_factory(engine)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(_submit, factory, TENANT_A, NOW),
                executor.submit(
                    _submit,
                    factory,
                    TENANT_A,
                    NOW + timedelta(milliseconds=1),
                ),
            ]
            exact = [future.result(timeout=20) for future in futures]

        job_ids = {item.snapshot.job_id for item in exact}
        assert len(job_ids) == 1
        assert sorted(item.created for item in exact) == [False, True]
        job_id = next(iter(job_ids))

        session = factory()
        try:
            count_a = session.scalar(
                select(func.count(AnalysisJob.id)).where(
                    AnalysisJob.tenant_ref == TENANT_A,
                    AnalysisJob.request_id == REQUEST_ID,
                )
            )
            assert count_a == 1
        finally:
            session.close()

        divergent_session = factory()
        try:
            try:
                DBIAnalysisJobService(
                    DBIAnalysisJobRepository(divergent_session)
                ).create(
                    _context(TENANT_A),
                    organization_ref=ORGANIZATION,
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                    request=_request(TENANT_A, orthophoto_id=ORTHO_A_ALT),
                    profile_policy=_StaticProfilePolicy(),
                    accepted_at=NOW + timedelta(seconds=1),
                )
            except AnalysisJobPersistenceConflict:
                divergent_session.rollback()
            else:
                raise AssertionError("El reintento divergente debía fallar.")
        finally:
            divergent_session.close()

        tenant_b = _submit(factory, TENANT_B, NOW + timedelta(seconds=2))
        assert tenant_b.created is True
        assert tenant_b.snapshot.job_id != job_id

        isolation_session = factory()
        try:
            try:
                DBIAnalysisJobService(
                    DBIAnalysisJobRepository(isolation_session)
                ).cancel(
                    _context(TENANT_B),
                    organization_ref=ORGANIZATION,
                    farm_id=FARM_ID,
                    job_id=job_id,
                    changed_at=NOW + timedelta(minutes=3),
                )
            except AnalysisJobResourceUnavailable:
                isolation_session.rollback()
            else:
                raise AssertionError("Otro tenant observó un trabajo ajeno.")
        finally:
            isolation_session.close()

        admin_session = factory()
        try:
            admin_session.execute(
                update(AnalysisJob)
                .where(AnalysisJob.id == job_id)
                .values(status=AnalysisJobStatus.QUEUED.value)
            )
            admin_session.commit()
        finally:
            admin_session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            cancels = [
                future.result(timeout=20)
                for future in (
                    executor.submit(_cancel, factory, job_id),
                    executor.submit(_cancel, factory, job_id),
                )
            ]
        assert sorted(item.changed for item in cancels) == [False, True]
        assert {item.snapshot.status for item in cancels} == {
            AnalysisJobStatus.CANCEL_REQUESTED
        }

        state_session = factory()
        try:
            state_session.execute(
                update(AnalysisJob)
                .where(AnalysisJob.id == job_id)
                .values(status=AnalysisJobStatus.FAILED.value)
            )
            state_session.commit()
        finally:
            state_session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            retries = [
                future.result(timeout=20)
                for future in (
                    executor.submit(_retry, factory, job_id),
                    executor.submit(_retry, factory, job_id),
                )
            ]
        assert sorted(item.changed for item in retries) == [False, True]
        assert {item.snapshot.status for item in retries} == {
            AnalysisJobStatus.QUEUED
        }

        invalid_session = factory()
        try:
            invalid_session.execute(
                update(AnalysisJob)
                .where(AnalysisJob.id == job_id)
                .values(status=AnalysisJobStatus.ACCEPTED.value)
            )
            invalid_session.commit()
            try:
                DBIAnalysisJobService(
                    DBIAnalysisJobRepository(invalid_session)
                ).cancel(
                    _context(TENANT_A),
                    organization_ref=ORGANIZATION,
                    farm_id=FARM_ID,
                    job_id=job_id,
                    changed_at=NOW + timedelta(minutes=30),
                )
            except InvalidAnalysisJobTransition:
                invalid_session.rollback()
            else:
                raise AssertionError("accepted no debe cancelar directamente.")
        finally:
            invalid_session.close()

        audit_session = factory()
        try:
            attempts = audit_session.scalar(select(func.count(AnalysisJobAttempt.id)))
            assets_not_verified = audit_session.scalar(
                select(func.count(AnalysisInputAsset.id)).where(
                    AnalysisInputAsset.id.in_(
                        [ORTHO_A, BOUNDARY_A, EXCLUSIONS_A]
                    ),
                    AnalysisInputAsset.status != "verified",
                )
            )
            assert attempts == 0
            assert assets_not_verified == 0
        finally:
            audit_session.close()

        print(
            "DBI-JOB-003 PostgreSQL aprobado: "
            "1 alta concurrente, 1 reuse, aislamiento, cancelación y retry idempotentes."
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
