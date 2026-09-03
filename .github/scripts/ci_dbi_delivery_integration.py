"""Integración real de DBI-QUEUE-001 sobre PostgreSQL/PostGIS efímero."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import load_dbi_database_config  # noqa: E402
from app.db.dbi_session import create_dbi_engine, create_dbi_session_factory  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.delivery.contracts import (  # noqa: E402
    DeliveryMessageStatus,
    DeliveryPersistenceConflict,
    DeliveryStream,
)
from app.dbi.delivery.repository import DBIDeliveryRepository  # noqa: E402
from app.dbi.delivery.service import DBIAnalysisDeliveryService  # noqa: E402
from app.dbi.jobs.persistence_contracts import AnalysisJobResourceUnavailable  # noqa: E402
from app.dbi.jobs.service_contracts import contract_sha256  # noqa: E402
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt  # noqa: E402
from app.dbi.models.delivery import DBIDeliveryMessage  # noqa: E402
from app.schemas.dbi_analysis_jobs import AnalysisJobCommand, AnalysisJobInputs  # noqa: E402

HOST = "127.0.0.1"
PORT = 5432
DATABASE = "dbi_test"
ADMIN_ROLE = "postgres"
API_ROLE = "dbi_test_delivery_api"
ORGANIZATION = "organization-ci-delivery"
TENANT_A = "tenant-ci-delivery-a"
TENANT_B = "tenant-ci-delivery-b"
FARM_ID = UUID("91000000-0000-4000-8000-000000000001")
PLOT_ID = UUID("92000000-0000-4000-8000-000000000001")
JOB_PUBLISH = UUID("93000000-0000-4000-8000-000000000001")
JOB_LEASE = UUID("93000000-0000-4000-8000-000000000002")
JOB_DEAD = UUID("93000000-0000-4000-8000-000000000003")
JOB_RETRY = UUID("93000000-0000-4000-8000-000000000004")
JOB_TENANT_B = UUID("93000000-0000-4000-8000-000000000005")
FAILED_ATTEMPT = UUID("94000000-0000-4000-8000-000000000001")
ORTHO_REF = UUID("95000000-0000-4000-8000-000000000001")
BOUNDARY_REF = UUID("96000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 9, 2, 23, 0, tzinfo=timezone.utc)


def _require_ci_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración de entrega sólo corre en GitHub Actions.")
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL heredada no está permitida.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración de entrega exige DBI_ENVIRONMENT=test.")
    if os.environ.get("DBI_DELIVERY_RUN_INTEGRATION") != "1":
        raise RuntimeError("La integración de entrega no fue habilitada.")
    config = load_dbi_database_config()
    identity = (
        config.database_name,
        config.url.username,
        config.url.host,
        config.url.port,
    )
    if identity != (DATABASE, API_ROLE, HOST, PORT):
        raise RuntimeError("DBI_DATABASE_URL no apunta al fixture de entrega.")


def _admin_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=ADMIN_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _command(job_id: UUID, tenant_ref: str, request_id: str, correlation_id: str):
    return AnalysisJobCommand(
        request_id=request_id,
        correlation_id=correlation_id,
        job_id=str(job_id),
        tenant_id=tenant_ref,
        farm_id=str(FARM_ID),
        lot_id=str(PLOT_ID),
        inputs=AnalysisJobInputs(
            orthophoto_asset_id=str(ORTHO_REF),
            boundary_asset_id=str(BOUNDARY_REF),
            exclusions_asset_id=None,
        ),
        model_version_id="banana-density-ci-champion",
        pipeline_config_version="pipeline-ci-v1",
        requested_by="principal-ci-delivery",
    )


def _insert_job(cursor, job_id: UUID, tenant_ref: str, status: str, suffix: str) -> None:
    request_id = f"request-ci-delivery-{suffix}"
    correlation_id = f"correlation-ci-delivery-{suffix}"
    command = _command(job_id, tenant_ref, request_id, correlation_id)
    cursor.execute(
        """
        INSERT INTO dbi.dbi_analysis_jobs
            (id, tenant_ref, request_id, correlation_id, farm_id, plot_id,
             campaign_id, orthophoto_asset_ref, boundary_asset_ref,
             exclusions_asset_ref, model_version_ref, pipeline_config_version,
             requested_by_ref, command_sha256, status, accepted_at,
             created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s, NULL, %s, %s, %s,
                %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            job_id,
            tenant_ref,
            request_id,
            correlation_id,
            FARM_ID,
            PLOT_ID,
            str(ORTHO_REF),
            str(BOUNDARY_REF),
            "banana-density-ci-champion",
            "pipeline-ci-v1",
            "principal-ci-delivery",
            contract_sha256(command),
            status,
            NOW,
            NOW,
            NOW,
        ),
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
                sql.SQL("REVOKE ALL ON SCHEMA dbi FROM {}").format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA dbi FROM {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT ON TABLE dbi.dbi_analysis_jobs, "
                    "dbi.dbi_analysis_job_attempts, dbi.dbi_delivery_messages TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, updated_at) ON TABLE "
                    "dbi.dbi_analysis_jobs TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL("GRANT INSERT ON TABLE dbi.dbi_analysis_job_attempts TO {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT INSERT, UPDATE ON TABLE dbi.dbi_delivery_messages TO {}"
                ).format(sql.Identifier(API_ROLE))
            )

            cursor.execute(
                """
                INSERT INTO dbi.dbi_farms
                    (id, organization_ref, code, name, status, created_at, updated_at)
                VALUES (%s, %s, 'CI-DELIVERY-FARM', 'CI Delivery Farm', 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (FARM_ID, ORGANIZATION, NOW, NOW),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_plots
                    (id, farm_id, code, name, area_hectares, boundary,
                     status, created_at, updated_at)
                VALUES (%s, %s, 'CI-DELIVERY-PLOT', 'CI Delivery Plot', 1.0, NULL,
                        'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (PLOT_ID, FARM_ID, NOW, NOW),
            )

            _insert_job(cursor, JOB_PUBLISH, TENANT_A, "accepted", "publish")
            _insert_job(cursor, JOB_LEASE, TENANT_A, "accepted", "lease")
            _insert_job(cursor, JOB_DEAD, TENANT_A, "accepted", "dead")
            _insert_job(cursor, JOB_RETRY, TENANT_A, "failed", "retry")
            _insert_job(cursor, JOB_TENANT_B, TENANT_B, "accepted", "tenant-b")
            cursor.execute(
                """
                INSERT INTO dbi.dbi_analysis_job_attempts
                    (id, job_id, attempt_number, status, failure_code, queued_at,
                     started_at, finished_at, created_at, updated_at)
                VALUES (%s, %s, 1, 'failed', 'CI_FAILURE', %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    FAILED_ATTEMPT,
                    JOB_RETRY,
                    NOW - timedelta(minutes=5),
                    NOW - timedelta(minutes=4),
                    NOW - timedelta(minutes=3),
                    NOW - timedelta(minutes=5),
                    NOW - timedelta(minutes=3),
                ),
            )


def _context(tenant_ref: str) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref=f"principal-{tenant_ref}",
        tenant_ref=tenant_ref,
        organization_refs=frozenset({ORGANIZATION}),
        farm_scopes=frozenset({DBIFarmScope(organization_ref=ORGANIZATION, farm_id=FARM_ID)}),
        plot_scopes=frozenset(
            {DBIPlotScope(organization_ref=ORGANIZATION, farm_id=FARM_ID, plot_id=PLOT_ID)}
        ),
        permissions=frozenset({DBIPermission.SUBMIT_ANALYSIS}),
    )


def _enqueue(factory, job_id: UUID, tenant_ref: str, at: datetime, *, retry=False, max_deliveries=5):
    session = factory()
    try:
        evidence = DBIAnalysisDeliveryService(session).enqueue_authorized_analysis_command(
            _context(tenant_ref),
            organization_ref=ORGANIZATION,
            farm_id=FARM_ID,
            job_id=job_id,
            queued_at=at,
            retry_authorized=retry,
            max_deliveries=max_deliveries,
        )
        session.commit()
        return evidence
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _claim(factory, at: datetime, *, lease_seconds: int = 30):
    session = factory()
    try:
        lease = DBIDeliveryRepository(session).claim_one(
            stream=DeliveryStream.ANALYSIS_COMMAND,
            claimed_at=at,
            lease_seconds=lease_seconds,
        )
        session.commit()
        return lease
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _ack(factory, message_id: UUID, lease_ref: UUID, at: datetime):
    session = factory()
    try:
        evidence = DBIDeliveryRepository(session).ack(
            message_id=message_id,
            lease_ref=lease_ref,
            delivered_at=at,
        )
        session.commit()
        return evidence
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _nack(factory, message_id: UUID, lease_ref: UUID, at: datetime, *, error_code: str):
    session = factory()
    try:
        evidence = DBIDeliveryRepository(session).nack(
            message_id=message_id,
            lease_ref=lease_ref,
            changed_at=at,
            available_at=at,
            error_code=error_code,
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
        # Dos publicadores sobre el mismo job deben converger en un solo attempt/mensaje.
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(_enqueue, factory, JOB_PUBLISH, TENANT_A, NOW),
                executor.submit(
                    _enqueue,
                    factory,
                    JOB_PUBLISH,
                    TENANT_A,
                    NOW + timedelta(milliseconds=1),
                ),
            ]
            published = [future.result(timeout=20) for future in futures]
        assert {item.attempt_id for item in published}.__len__() == 1
        assert {item.message.message_id for item in published}.__len__() == 1
        assert sorted(item.created for item in published) == [False, True]

        session = factory()
        try:
            assert session.scalar(
                select(func.count(AnalysisJobAttempt.id)).where(
                    AnalysisJobAttempt.job_id == JOB_PUBLISH
                )
            ) == 1
            assert session.scalar(
                select(func.count(DBIDeliveryMessage.id)).where(
                    DBIDeliveryMessage.job_id == JOB_PUBLISH,
                    DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_COMMAND.value,
                )
            ) == 1
        finally:
            session.close()

        # Dos consumidores simultáneos no pueden obtener el mismo mensaje.
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(_claim, factory, NOW + timedelta(seconds=1)),
                executor.submit(_claim, factory, NOW + timedelta(seconds=1)),
            ]
            claims = [future.result(timeout=20) for future in futures]
        leases = [item for item in claims if item is not None]
        assert len(leases) == 1
        lease = leases[0]

        try:
            _ack(
                factory,
                lease.envelope.message_id,
                uuid4(),
                NOW + timedelta(seconds=2),
            )
        except DeliveryPersistenceConflict:
            pass
        else:
            raise AssertionError("un lease ajeno no debe confirmar el mensaje.")
        acked = _ack(
            factory,
            lease.envelope.message_id,
            lease.lease_ref,
            NOW + timedelta(seconds=2),
        )
        repeated_ack = _ack(
            factory,
            lease.envelope.message_id,
            lease.lease_ref,
            NOW + timedelta(seconds=3),
        )
        assert acked.changed is True and repeated_ack.changed is False

        # Un lease expirado se puede recuperar sin duplicar el mensaje.
        lease_job = _enqueue(
            factory,
            JOB_LEASE,
            TENANT_A,
            NOW + timedelta(minutes=1),
            max_deliveries=3,
        )
        first_lease = _claim(factory, NOW + timedelta(minutes=1, seconds=1), lease_seconds=10)
        assert first_lease is not None and first_lease.envelope.message_id == lease_job.message.message_id
        recovered = _claim(factory, NOW + timedelta(minutes=1, seconds=12), lease_seconds=10)
        assert recovered is not None
        assert recovered.envelope.message_id == first_lease.envelope.message_id
        assert recovered.lease_ref != first_lease.lease_ref
        nacked = _nack(
            factory,
            recovered.envelope.message_id,
            recovered.lease_ref,
            NOW + timedelta(minutes=1, seconds=13),
            error_code="WORKER_RETRY",
        )
        repeated_nack = _nack(
            factory,
            recovered.envelope.message_id,
            recovered.lease_ref,
            NOW + timedelta(minutes=1, seconds=14),
            error_code="WORKER_RETRY",
        )
        assert nacked.status is DeliveryMessageStatus.PENDING and repeated_nack.changed is False
        final_lease = _claim(factory, NOW + timedelta(minutes=1, seconds=15), lease_seconds=10)
        assert final_lease is not None and final_lease.envelope.message_id == recovered.envelope.message_id
        _ack(
            factory,
            final_lease.envelope.message_id,
            final_lease.lease_ref,
            NOW + timedelta(minutes=1, seconds=16),
        )

        # Nack acotado termina en dead-letter conservando el mismo mensaje.
        dead_job = _enqueue(
            factory,
            JOB_DEAD,
            TENANT_A,
            NOW + timedelta(minutes=2),
            max_deliveries=2,
        )
        dead_lease_1 = _claim(factory, NOW + timedelta(minutes=2, seconds=1))
        assert dead_lease_1 is not None and dead_lease_1.envelope.message_id == dead_job.message.message_id
        first_nack = _nack(
            factory,
            dead_lease_1.envelope.message_id,
            dead_lease_1.lease_ref,
            NOW + timedelta(minutes=2, seconds=2),
            error_code="TRANSIENT_FAILURE",
        )
        assert first_nack.status is DeliveryMessageStatus.PENDING
        dead_lease_2 = _claim(factory, NOW + timedelta(minutes=2, seconds=3))
        assert dead_lease_2 is not None and dead_lease_2.envelope.message_id == dead_job.message.message_id
        dead = _nack(
            factory,
            dead_lease_2.envelope.message_id,
            dead_lease_2.lease_ref,
            NOW + timedelta(minutes=2, seconds=4),
            error_code="TRANSIENT_FAILURE",
        )
        assert dead.status is DeliveryMessageStatus.DEAD_LETTER

        # Un retry failed crea attempt_number+1 exactamente una vez bajo carrera.
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _enqueue,
                    factory,
                    JOB_RETRY,
                    TENANT_A,
                    NOW + timedelta(minutes=3),
                    retry=True,
                ),
                executor.submit(
                    _enqueue,
                    factory,
                    JOB_RETRY,
                    TENANT_A,
                    NOW + timedelta(minutes=3, milliseconds=1),
                    retry=True,
                ),
            ]
            retried = [future.result(timeout=20) for future in futures]
        assert {item.attempt_number for item in retried} == {2}
        assert {item.attempt_id for item in retried}.__len__() == 1
        assert sorted(item.created for item in retried) == [False, True]

        # El tenant equivocado no puede descubrir ni encolar un trabajo ajeno.
        try:
            _enqueue(factory, JOB_TENANT_B, TENANT_A, NOW + timedelta(minutes=4))
        except AnalysisJobResourceUnavailable:
            pass
        else:
            raise AssertionError("tenant A no debe encolar trabajo de tenant B.")
        tenant_b = _enqueue(factory, JOB_TENANT_B, TENANT_B, NOW + timedelta(minutes=4))
        assert tenant_b.created is True

        session = factory()
        try:
            retry_attempts = session.scalars(
                select(AnalysisJobAttempt)
                .where(AnalysisJobAttempt.job_id == JOB_RETRY)
                .order_by(AnalysisJobAttempt.attempt_number)
            ).all()
            assert [item.attempt_number for item in retry_attempts] == [1, 2]
            retry_messages = session.scalar(
                select(func.count(DBIDeliveryMessage.id)).where(
                    DBIDeliveryMessage.job_id == JOB_RETRY,
                    DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_COMMAND.value,
                )
            )
            assert retry_messages == 1
            assert session.scalar(
                select(AnalysisJob.status).where(AnalysisJob.id == JOB_RETRY)
            ) == "queued"
        finally:
            session.close()
    finally:
        engine.dispose()

    print(
        "DBI-QUEUE-001 PostgreSQL aprobado: publicación/claim concurrentes, "
        "lease, ack/nack, dead-letter, retry e aislamiento."
    )


if __name__ == "__main__":
    main()
