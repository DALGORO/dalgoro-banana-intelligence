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
from app.dbi.delivery.contracts import (  # noqa: E402
    DeliveryMessageStatus,
    DeliveryPersistenceConflict,
    DeliveryStream,
)
from app.dbi.delivery.repository import DBIDeliveryRepository  # noqa: E402
from app.dbi.delivery.service import DBIAnalysisDeliveryService  # noqa: E402
from app.dbi.jobs.service_contracts import contract_sha256  # noqa: E402
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt  # noqa: E402
from app.dbi.models.delivery import DBIDeliveryMessage  # noqa: E402
from app.schemas.dbi_analysis_jobs import (  # noqa: E402
    AnalysisJobCommand,
    AnalysisJobInputs,
    AnalysisJobResult,
)

HOST = "127.0.0.1"
PORT = 5432
DATABASE = "dbi_test"
ADMIN_ROLE = "postgres"
API_ROLE = "dbi_test_delivery_api"
ORGANIZATION = "organization-ci-delivery"
TENANT = "tenant-ci-delivery"
FARM_ID = UUID("91000000-0000-4000-8000-000000000001")
PLOT_ID = UUID("92000000-0000-4000-8000-000000000001")
JOB_1 = UUID("93000000-0000-4000-8000-000000000001")
JOB_2 = UUID("93000000-0000-4000-8000-000000000002")
JOB_3 = UUID("93000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 9, 2, 21, 0, tzinfo=timezone.utc)


def _require_ci_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración durable solo corre en GitHub Actions.")
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL heredada no está permitida.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración durable exige DBI_ENVIRONMENT=test.")
    if os.environ.get("DBI_DELIVERY_RUN_INTEGRATION") != "1":
        raise RuntimeError("La integración durable no fue habilitada.")
    config = load_dbi_database_config()
    identity = (
        config.database_name,
        config.url.username,
        config.url.host,
        config.url.port,
    )
    if identity != (DATABASE, API_ROLE, HOST, PORT):
        raise RuntimeError("DBI_DATABASE_URL no apunta al fixture durable.")


def _admin_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=ADMIN_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _command(job_id: UUID, request_id: str, correlation_id: str) -> AnalysisJobCommand:
    return AnalysisJobCommand(
        request_id=request_id,
        correlation_id=correlation_id,
        job_id=str(job_id),
        tenant_id=TENANT,
        farm_id=str(FARM_ID),
        lot_id=str(PLOT_ID),
        inputs=AnalysisJobInputs(
            orthophoto_asset_id="94000000-0000-4000-8000-000000000001",
            boundary_asset_id="95000000-0000-4000-8000-000000000001",
            exclusions_asset_id=None,
        ),
        model_version_id="model-ci-delivery-v1",
        pipeline_config_version="pipeline-ci-delivery-v1",
        requested_by="principal-ci-delivery",
    )


def _job_row(job_id: UUID, suffix: str) -> tuple:
    request_id = f"request-ci-delivery-{suffix}"
    correlation_id = f"correlation-ci-delivery-{suffix}"
    command = _command(job_id, request_id, correlation_id)
    return (
        job_id,
        TENANT,
        request_id,
        correlation_id,
        FARM_ID,
        PLOT_ID,
        str(command.inputs.orthophoto_asset_id),
        str(command.inputs.boundary_asset_id),
        command.model_version_id,
        command.pipeline_config_version,
        command.requested_by,
        contract_sha256(command),
        NOW,
        NOW,
        NOW,
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
                sql.SQL("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA dbi FROM {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(API_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT ON TABLE dbi.dbi_analysis_jobs, "
                    "dbi.dbi_analysis_job_attempts, dbi.dbi_delivery_messages TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT INSERT ON TABLE dbi.dbi_analysis_job_attempts, "
                    "dbi.dbi_delivery_messages TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, updated_at) ON TABLE "
                    "dbi.dbi_analysis_jobs TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (updated_at) ON TABLE "
                    "dbi.dbi_analysis_job_attempts TO {}"
                ).format(sql.Identifier(API_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, delivery_count, available_at, lease_ref, "
                    "lease_expires_at, last_lease_ref, last_error_code, delivered_at, "
                    "updated_at) ON TABLE dbi.dbi_delivery_messages TO {}"
                ).format(sql.Identifier(API_ROLE))
            )

            cursor.execute(
                """
                INSERT INTO dbi.dbi_farms
                    (id, organization_ref, code, name, status, created_at, updated_at)
                VALUES (%s, %s, 'CI-DELIVERY-FARM', 'CI Delivery Farm',
                        'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (FARM_ID, ORGANIZATION, NOW, NOW),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_plots
                    (id, farm_id, code, name, area_hectares, boundary,
                     status, created_at, updated_at)
                VALUES (%s, %s, 'CI-DELIVERY-PLOT', 'CI Delivery Plot',
                        1.0, NULL, 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (PLOT_ID, FARM_ID, NOW, NOW),
            )
            cursor.executemany(
                """
                INSERT INTO dbi.dbi_analysis_jobs
                    (id, tenant_ref, request_id, correlation_id, farm_id, plot_id,
                     campaign_id, orthophoto_asset_ref, boundary_asset_ref,
                     exclusions_asset_ref, model_version_ref, pipeline_config_version,
                     requested_by_ref, command_sha256, status, accepted_at,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s, NULL,
                        %s, %s, %s, %s, 'accepted', %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _job_row(JOB_1, "one"),
                    _job_row(JOB_2, "two"),
                    _job_row(JOB_3, "three"),
                ),
            )


def _factory():
    engine = create_dbi_engine(load_dbi_database_config())
    return engine, create_dbi_session_factory(engine)


def _enqueue(factory, job_id: UUID, *, retry: bool = False, max_deliveries: int = 5):
    session = factory()
    try:
        evidence = DBIAnalysisDeliveryService(session).enqueue_analysis_command(
            tenant_ref=TENANT,
            farm_id=FARM_ID,
            job_id=job_id,
            queued_at=NOW,
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


def _claim(factory, stream: DeliveryStream, claimed_at: datetime, lease_seconds: int = 30):
    session = factory()
    try:
        lease = DBIDeliveryRepository(session).claim_one(
            stream=stream,
            claimed_at=claimed_at,
            lease_seconds=lease_seconds,
        )
        session.commit()
        return lease
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def validate_enqueue_concurrency(factory) -> tuple[UUID, UUID]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_enqueue, factory, JOB_1) for _ in range(2)]
        evidence = [future.result() for future in futures]

    assert sum(item.created for item in evidence) == 1
    assert len({item.attempt_id for item in evidence}) == 1
    assert len({item.message.message_id for item in evidence}) == 1
    attempt_id = evidence[0].attempt_id
    message_id = evidence[0].message.message_id

    session = factory()
    try:
        assert session.scalar(
            select(func.count()).select_from(AnalysisJobAttempt).where(
                AnalysisJobAttempt.job_id == JOB_1
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(DBIDeliveryMessage).where(
                DBIDeliveryMessage.job_id == JOB_1,
                DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_COMMAND.value,
            )
        ) == 1
        job = session.get(AnalysisJob, JOB_1)
        assert job is not None and job.status == "queued"
    finally:
        session.close()
    return attempt_id, message_id


def validate_claim_and_ack(factory, message_id: UUID) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_claim, factory, DeliveryStream.ANALYSIS_COMMAND, NOW)
            for _ in range(2)
        ]
        leases = [future.result() for future in futures]
    claimed = [lease for lease in leases if lease is not None]
    assert len(claimed) == 1
    lease = claimed[0]
    assert lease.envelope.message_id == message_id
    assert lease.envelope.delivery_count == 1

    session = factory()
    try:
        repository = DBIDeliveryRepository(session)
        try:
            repository.ack(
                message_id=message_id,
                lease_ref=uuid4(),
                delivered_at=NOW + timedelta(seconds=1),
            )
        except DeliveryPersistenceConflict:
            session.rollback()
        else:
            raise AssertionError("Un lease incorrecto no debe hacer ack.")
    finally:
        session.close()

    session = factory()
    try:
        repository = DBIDeliveryRepository(session)
        first = repository.ack(
            message_id=message_id,
            lease_ref=lease.lease_ref,
            delivered_at=NOW + timedelta(seconds=1),
        )
        session.commit()
        assert first.changed is True
        assert first.status is DeliveryMessageStatus.DELIVERED
    finally:
        session.close()

    session = factory()
    try:
        replay = DBIDeliveryRepository(session).ack(
            message_id=message_id,
            lease_ref=lease.lease_ref,
            delivered_at=NOW + timedelta(seconds=2),
        )
        session.commit()
        assert replay.changed is False
        assert replay.status is DeliveryMessageStatus.DELIVERED
    finally:
        session.close()


def validate_nack_dead_letter(factory) -> None:
    evidence = _enqueue(factory, JOB_2, max_deliveries=2)
    message_id = evidence.message.message_id

    first_lease = _claim(factory, DeliveryStream.ANALYSIS_COMMAND, NOW)
    assert first_lease is not None and first_lease.envelope.message_id == message_id
    session = factory()
    try:
        first = DBIDeliveryRepository(session).nack(
            message_id=message_id,
            lease_ref=first_lease.lease_ref,
            changed_at=NOW + timedelta(seconds=1),
            available_at=NOW + timedelta(seconds=1),
            error_code="WORKER_UNAVAILABLE",
        )
        session.commit()
        assert first.status is DeliveryMessageStatus.PENDING
    finally:
        session.close()

    second_lease = _claim(
        factory,
        DeliveryStream.ANALYSIS_COMMAND,
        NOW + timedelta(seconds=2),
    )
    assert second_lease is not None and second_lease.envelope.message_id == message_id
    session = factory()
    try:
        second = DBIDeliveryRepository(session).nack(
            message_id=message_id,
            lease_ref=second_lease.lease_ref,
            changed_at=NOW + timedelta(seconds=3),
            available_at=NOW + timedelta(seconds=3),
            error_code="WORKER_UNAVAILABLE",
        )
        session.commit()
        assert second.status is DeliveryMessageStatus.DEAD_LETTER
        replay = DBIDeliveryRepository(session).nack(
            message_id=message_id,
            lease_ref=second_lease.lease_ref,
            changed_at=NOW + timedelta(seconds=4),
            available_at=NOW + timedelta(seconds=4),
            error_code="WORKER_UNAVAILABLE",
        )
        session.commit()
        assert replay.changed is False
        assert replay.status is DeliveryMessageStatus.DEAD_LETTER
    finally:
        session.close()


def validate_lease_expiry(factory) -> None:
    evidence = _enqueue(factory, JOB_3, max_deliveries=3)
    message_id = evidence.message.message_id
    first = _claim(factory, DeliveryStream.ANALYSIS_COMMAND, NOW, lease_seconds=1)
    assert first is not None and first.envelope.message_id == message_id
    second = _claim(
        factory,
        DeliveryStream.ANALYSIS_COMMAND,
        NOW + timedelta(seconds=2),
        lease_seconds=30,
    )
    assert second is not None
    assert second.envelope.message_id == message_id
    assert second.lease_ref != first.lease_ref
    assert second.envelope.delivery_count == 2

    session = factory()
    try:
        repository = DBIDeliveryRepository(session)
        try:
            repository.ack(
                message_id=message_id,
                lease_ref=first.lease_ref,
                delivered_at=NOW + timedelta(seconds=3),
            )
        except DeliveryPersistenceConflict:
            session.rollback()
        else:
            raise AssertionError("Un lease expirado no debe confirmar la reentrega.")
        final = repository.ack(
            message_id=message_id,
            lease_ref=second.lease_ref,
            delivered_at=NOW + timedelta(seconds=3),
        )
        session.commit()
        assert final.status is DeliveryMessageStatus.DELIVERED
    finally:
        session.close()


def validate_retry_and_result(factory, first_attempt_id: UUID) -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE dbi.dbi_analysis_jobs SET status = 'failed', updated_at = %s "
                "WHERE id = %s",
                (NOW + timedelta(minutes=1), JOB_1),
            )
            cursor.execute(
                "UPDATE dbi.dbi_analysis_job_attempts SET status = 'failed', "
                "started_at = %s, finished_at = %s, updated_at = %s "
                "WHERE id = %s AND job_id = %s",
                (
                    NOW,
                    NOW + timedelta(seconds=10),
                    NOW + timedelta(seconds=10),
                    first_attempt_id,
                    JOB_1,
                ),
            )

    retry_time = NOW + timedelta(minutes=2)

    def retry_once():
        session = factory()
        try:
            evidence = DBIAnalysisDeliveryService(session).enqueue_analysis_command(
                tenant_ref=TENANT,
                farm_id=FARM_ID,
                job_id=JOB_1,
                queued_at=retry_time,
                retry_authorized=True,
            )
            session.commit()
            return evidence
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        evidence = [future.result() for future in [executor.submit(retry_once) for _ in range(2)]]
    assert sum(item.created for item in evidence) == 1
    assert {item.attempt_number for item in evidence} == {2}
    assert len({item.attempt_id for item in evidence}) == 1
    retry_attempt = evidence[0].attempt_id

    result = AnalysisJobResult(
        correlation_id="correlation-ci-delivery-one",
        job_id=str(JOB_1),
        attempt_id=str(retry_attempt),
        status="failed",
        pipeline_build="worker-build-ci-001",
        started_at=retry_time,
        finished_at=retry_time + timedelta(seconds=30),
        errors=["pipeline-failed"],
    )
    session = factory()
    try:
        service = DBIAnalysisDeliveryService(session)
        first_message, first_created = service.publish_analysis_result(
            result,
            available_at=retry_time + timedelta(seconds=31),
        )
        second_message, second_created = service.publish_analysis_result(
            result,
            available_at=retry_time + timedelta(seconds=31),
        )
        session.commit()
        assert first_created is True
        assert second_created is False
        assert first_message.message_id == second_message.message_id
        assert first_message.stream is DeliveryStream.ANALYSIS_RESULT
    finally:
        session.close()

    result_lease = _claim(
        factory,
        DeliveryStream.ANALYSIS_RESULT,
        retry_time + timedelta(seconds=32),
    )
    assert result_lease is not None
    session = factory()
    try:
        ack = DBIDeliveryRepository(session).ack(
            message_id=result_lease.envelope.message_id,
            lease_ref=result_lease.lease_ref,
            delivered_at=retry_time + timedelta(seconds=33),
        )
        session.commit()
        assert ack.status is DeliveryMessageStatus.DELIVERED
    finally:
        session.close()


def main() -> None:
    _require_ci_scope()
    _provision_role_and_fixture()
    engine, factory = _factory()
    try:
        attempt_id, message_id = validate_enqueue_concurrency(factory)
        validate_claim_and_ack(factory, message_id)
        validate_nack_dead_letter(factory)
        validate_lease_expiry(factory)
        validate_retry_and_result(factory, attempt_id)

        session = factory()
        try:
            jobs = session.scalar(select(func.count()).select_from(AnalysisJob))
            attempts = session.scalar(select(func.count()).select_from(AnalysisJobAttempt))
            messages = session.scalar(select(func.count()).select_from(DBIDeliveryMessage))
        finally:
            session.close()
        print(
            "DBI-QUEUE-001 PostgreSQL aprobado: enqueue/claim concurrentes, "
            "ack idempotente, nack/dead-letter, lease expiry, retry y resultado durable. "
            f"jobs={jobs}, attempts={attempts}, messages={messages}."
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
