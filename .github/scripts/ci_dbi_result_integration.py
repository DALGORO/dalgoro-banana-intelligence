"""Integración PostgreSQL de Worker → Queue → Result con rol mínimo."""

from __future__ import annotations

import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.delivery.contracts import (  # noqa: E402
    DeliveryStream,
    prepare_delivery_payload,
)
from app.dbi.delivery.repository import DBIDeliveryRepository  # noqa: E402
from app.dbi.models.analysis_results import DBIAnalysisResult  # noqa: E402
from app.dbi.models.assets import AnalysisArtifact  # noqa: E402
from app.dbi.models.delivery import DBIDeliveryMessage  # noqa: E402
from app.dbi.results.consumer import DBIAnalysisResultConsumer  # noqa: E402
from app.dbi.results.contracts import DBIResultIngestionConflict  # noqa: E402
from app.dbi.results.service import DBIAnalysisResultIngestionService  # noqa: E402
from app.dbi.storage_contracts import DBIStorageObjectRecord  # noqa: E402
from app.dbi.worker.contracts import PipelineExecutionEvidence  # noqa: E402
from app.dbi.worker.service import DBIAnalysisWorkerService  # noqa: E402
from app.schemas.dbi_analysis_jobs import AnalysisJobResult  # noqa: E402
from ci_dbi_worker_integration import (  # noqa: E402
    ADMIN_ROLE,
    DATABASE,
    FakePipelineAdapter,
    HOST,
    NOW,
    PORT,
    TENANT,
    WORKER_ROLE,
    MutableClock,
    _admin_connect,
    _insert_job,
    _object_store,
    _provision_role_and_shared_fixture,
)

RESULT_ROLE = "dbi_test_result"

JOB_SUCCESS = UUID("a1000000-0000-4000-8000-000000000001")
ATTEMPT_SUCCESS = UUID("a2000000-0000-4000-8000-000000000001")
COMMAND_SUCCESS = UUID("a3000000-0000-4000-8000-000000000001")
JOB_REPLAY = UUID("a1000000-0000-4000-8000-000000000002")
ATTEMPT_REPLAY = UUID("a2000000-0000-4000-8000-000000000002")
COMMAND_REPLAY = UUID("a3000000-0000-4000-8000-000000000002")
JOB_TAMPER = UUID("a1000000-0000-4000-8000-000000000003")
ATTEMPT_TAMPER = UUID("a2000000-0000-4000-8000-000000000003")
COMMAND_TAMPER = UUID("a3000000-0000-4000-8000-000000000003")
JOB_CONCURRENT = UUID("a1000000-0000-4000-8000-000000000004")
ATTEMPT_CONCURRENT = UUID("a2000000-0000-4000-8000-000000000004")
COMMAND_CONCURRENT = UUID("a3000000-0000-4000-8000-000000000004")
JOB_CANCEL = UUID("a1000000-0000-4000-8000-000000000005")
ATTEMPT_CANCEL = UUID("a2000000-0000-4000-8000-000000000005")
COMMAND_CANCEL = UUID("a3000000-0000-4000-8000-000000000005")
JOB_FAILED = UUID("a1000000-0000-4000-8000-000000000006")
ATTEMPT_FAILED = UUID("a2000000-0000-4000-8000-000000000006")
COMMAND_FAILED = UUID("a3000000-0000-4000-8000-000000000006")


class FailedPipelineAdapter:
    def __init__(self) -> None:
        self.executions = 0

    def run(self, *, plan, workspace, heartbeat, cancel_requested):
        self.executions += 1
        heartbeat()
        return PipelineExecutionEvidence(status="failed", return_code=17)


class TamperedStatStore:
    """Mantiene dirección/MIME/tamaño pero altera SHA observable por Result."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def stat(self, address):
        record = self._delegate.stat(address)
        metadata = replace(record.metadata, sha256="0" * 64)
        return DBIStorageObjectRecord(
            metadata=metadata,
            state=record.state,
            created_at=record.created_at,
            retired_at=record.retired_at,
        )


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración Result sólo corre en GitHub Actions.")
    if os.environ.get("DBI_RESULT_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta habilitar DBI_RESULT_RUN_INTEGRATION.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración Result exige DBI_ENVIRONMENT=test.")
    url = os.environ.get("DBI_DATABASE_URL", "")
    if RESULT_ROLE not in url or HOST not in url or DATABASE not in url:
        raise RuntimeError("DBI_DATABASE_URL no apunta al rol Result autorizado.")


def _url(role: str) -> str:
    return f"postgresql+psycopg://{role}@{HOST}:{PORT}/{DATABASE}"


def _factory(role: str):
    engine = create_engine(_url(role), poolclass=NullPool, future=True)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _provision_result_role() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RESULT_ROLE,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(RESULT_ROLE))
                )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DATABASE), sql.Identifier(RESULT_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(RESULT_ROLE)
                )
            )
            for table_name in (
                "dbi_analysis_jobs",
                "dbi_analysis_job_attempts",
                "dbi_delivery_messages",
                "dbi_analysis_results",
                "dbi_analysis_artifacts",
            ):
                cursor.execute(
                    sql.SQL("GRANT SELECT ON dbi.{} TO {}").format(
                        sql.Identifier(table_name), sql.Identifier(RESULT_ROLE)
                    )
                )
            for table_name in ("dbi_analysis_results", "dbi_analysis_artifacts"):
                cursor.execute(
                    sql.SQL("GRANT INSERT ON dbi.{} TO {}").format(
                        sql.Identifier(table_name), sql.Identifier(RESULT_ROLE)
                    )
                )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, delivery_count, available_at, lease_ref, "
                    "lease_expires_at, last_lease_ref, last_error_code, delivered_at, "
                    "updated_at) ON dbi.dbi_delivery_messages TO {}"
                ).format(sql.Identifier(RESULT_ROLE))
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(RESULT_ROLE)
                )
            )


def _result_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=RESULT_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _assert_denied(statement: str, params: tuple = ()) -> None:
    with _result_connect() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(statement, params)
            except psycopg.errors.InsufficientPrivilege:
                return
    raise AssertionError("el rol Result obtuvo una mutación no autorizada.")


def validate_acl() -> None:
    _assert_denied("UPDATE dbi.dbi_analysis_jobs SET status = status")
    _assert_denied("UPDATE dbi.dbi_analysis_job_attempts SET status = status")
    _assert_denied("UPDATE dbi.dbi_farms SET name = name")
    _assert_denied("UPDATE dbi.dbi_analysis_results SET status = status")
    _assert_denied("DELETE FROM dbi.dbi_analysis_artifacts")


def _run_worker(
    worker_factory,
    store,
    temporary: str,
    *,
    job_id: UUID,
    attempt_id: UUID,
    command_id: UUID,
    suffix: str,
    at: datetime,
    status: str = "queued",
    pipeline=None,
):
    _insert_job(
        job_id,
        attempt_id,
        command_id,
        suffix,
        status=status,
        available_at=at,
    )
    adapter = pipeline or FakePipelineAdapter()
    evidence = DBIAnalysisWorkerService(
        worker_factory,
        store,
        workspace_root=temporary,
        worker_ref=f"worker-result-{suffix}",
        pipeline_adapter=adapter,
        clock=MutableClock(at),
        lease_seconds=60,
        heartbeat_seconds=10,
    ).process_one()
    assert evidence is not None
    return evidence, adapter


def _claim_result(factory, at: datetime, *, lease_seconds: int = 10):
    session = factory()
    try:
        lease = DBIDeliveryRepository(session).claim_one(
            stream=DeliveryStream.ANALYSIS_RESULT,
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


def _nack_result(factory, lease, at: datetime) -> None:
    session = factory()
    try:
        DBIDeliveryRepository(session).nack(
            message_id=lease.envelope.message_id,
            lease_ref=lease.lease_ref,
            changed_at=at,
            available_at=at,
            error_code="RESULT_CONFLICT",
        )
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _counts(factory, attempt_id: UUID) -> tuple[int, int]:
    session = factory()
    try:
        results = session.scalar(
            select(func.count(DBIAnalysisResult.id)).where(
                DBIAnalysisResult.attempt_id == attempt_id
            )
        )
        artifacts = session.scalar(
            select(func.count(AnalysisArtifact.id)).where(
                AnalysisArtifact.attempt_id == attempt_id
            )
        )
        return int(results or 0), int(artifacts or 0)
    finally:
        session.close()


def _result_payload(factory, attempt_id: UUID) -> AnalysisJobResult:
    session = factory()
    try:
        payload_json = session.scalar(
            select(DBIDeliveryMessage.payload_json).where(
                DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_RESULT.value,
                DBIDeliveryMessage.attempt_id == attempt_id,
            )
        )
        assert payload_json is not None
        return AnalysisJobResult.model_validate_json(payload_json)
    finally:
        session.close()


def validate_success(worker_factory, result_factory, store, temporary: str) -> None:
    at = NOW + timedelta(hours=1)
    worker_evidence, pipeline = _run_worker(
        worker_factory,
        store,
        temporary,
        job_id=JOB_SUCCESS,
        attempt_id=ATTEMPT_SUCCESS,
        command_id=COMMAND_SUCCESS,
        suffix="result-success",
        at=at,
    )
    assert worker_evidence.terminal_status == "succeeded"
    assert pipeline.executions == 1

    consumer = DBIAnalysisResultConsumer(
        result_factory,
        store,
        clock=MutableClock(at + timedelta(seconds=1)),
        lease_seconds=10,
        retry_delay_seconds=0,
    )
    evidence = consumer.process_one()
    assert evidence is not None
    assert evidence.status == "succeeded"
    assert evidence.created is True
    assert evidence.artifact_count == 9
    assert evidence.acknowledged is True
    assert _counts(result_factory, ATTEMPT_SUCCESS) == (1, 9)


def validate_storage_tamper(worker_factory, result_factory, store, temporary: str) -> None:
    at = NOW + timedelta(hours=2)
    _run_worker(
        worker_factory,
        store,
        temporary,
        job_id=JOB_TAMPER,
        attempt_id=ATTEMPT_TAMPER,
        command_id=COMMAND_TAMPER,
        suffix="result-tamper",
        at=at,
    )
    bad_consumer = DBIAnalysisResultConsumer(
        result_factory,
        TamperedStatStore(store),
        clock=MutableClock(at + timedelta(seconds=1)),
        lease_seconds=10,
        retry_delay_seconds=0,
    )
    try:
        bad_consumer.process_one()
    except DBIResultIngestionConflict:
        pass
    else:
        raise AssertionError("Storage divergente debía fallar cerrado.")
    assert _counts(result_factory, ATTEMPT_TAMPER) == (0, 0)

    good = DBIAnalysisResultConsumer(
        result_factory,
        store,
        clock=MutableClock(at + timedelta(seconds=2)),
        lease_seconds=10,
        retry_delay_seconds=0,
    ).process_one()
    assert good is not None and good.created is True
    assert _counts(result_factory, ATTEMPT_TAMPER) == (1, 9)


def validate_post_commit_replay(worker_factory, result_factory, store, temporary: str) -> None:
    at = NOW + timedelta(hours=3)
    _run_worker(
        worker_factory,
        store,
        temporary,
        job_id=JOB_REPLAY,
        attempt_id=ATTEMPT_REPLAY,
        command_id=COMMAND_REPLAY,
        suffix="result-replay",
        at=at,
    )
    lease = _claim_result(result_factory, at + timedelta(seconds=1), lease_seconds=10)
    assert lease is not None and lease.envelope.attempt_id == ATTEMPT_REPLAY
    session = result_factory()
    try:
        first = DBIAnalysisResultIngestionService(session, store).ingest(
            lease,
            ingested_at=at + timedelta(seconds=1),
        )
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
    assert first.created is True and first.acknowledged is False
    assert _counts(result_factory, ATTEMPT_REPLAY) == (1, 9)

    replay = DBIAnalysisResultConsumer(
        result_factory,
        store,
        clock=MutableClock(at + timedelta(seconds=12)),
        lease_seconds=10,
        retry_delay_seconds=0,
    ).process_one()
    assert replay is not None
    assert replay.created is False and replay.acknowledged is True
    assert _counts(result_factory, ATTEMPT_REPLAY) == (1, 9)


def validate_divergent_result(worker_factory, result_factory, store, temporary: str) -> None:
    at = NOW + timedelta(hours=4)
    _run_worker(
        worker_factory,
        store,
        temporary,
        job_id=JOB_CONCURRENT,
        attempt_id=ATTEMPT_CONCURRENT,
        command_id=COMMAND_CONCURRENT,
        suffix="result-divergent",
        at=at,
    )
    lease = _claim_result(result_factory, at + timedelta(seconds=1), lease_seconds=10)
    assert lease is not None and lease.envelope.attempt_id == ATTEMPT_CONCURRENT
    original = AnalysisJobResult.model_validate_json(lease.envelope.payload.payload_json)
    forged = original.model_copy(update={"metrics": {"artifact_count": 999}})
    payload = prepare_delivery_payload(forged)
    forged_lease = lease.model_copy(
        update={
            "envelope": lease.envelope.model_copy(
                update={"payload": payload}
            )
        }
    )
    session = result_factory()
    try:
        try:
            DBIAnalysisResultIngestionService(session, store).ingest(
                forged_lease,
                ingested_at=at + timedelta(seconds=1),
            )
        except DBIResultIngestionConflict:
            session.rollback()
        else:
            raise AssertionError("result_sha256 divergente debía rechazarse.")
    finally:
        session.close()
    assert _counts(result_factory, ATTEMPT_CONCURRENT) == (0, 0)
    _nack_result(result_factory, lease, at + timedelta(seconds=1))

    good = DBIAnalysisResultConsumer(
        result_factory,
        store,
        clock=MutableClock(at + timedelta(seconds=2)),
        lease_seconds=10,
        retry_delay_seconds=0,
    ).process_one()
    assert good is not None and good.created is True


def validate_concurrent_consumers(worker_factory, result_factory, store, temporary: str) -> None:
    at = NOW + timedelta(hours=5)
    job_id = uuid4()
    attempt_id = uuid4()
    command_id = uuid4()
    _run_worker(
        worker_factory,
        store,
        temporary,
        job_id=job_id,
        attempt_id=attempt_id,
        command_id=command_id,
        suffix="result-concurrent",
        at=at,
    )

    def run_consumer():
        return DBIAnalysisResultConsumer(
            result_factory,
            store,
            clock=MutableClock(at + timedelta(seconds=1)),
            lease_seconds=10,
            retry_delay_seconds=0,
        ).process_one()

    with ThreadPoolExecutor(max_workers=2) as executor:
        values = [future.result(timeout=30) for future in (
            executor.submit(run_consumer),
            executor.submit(run_consumer),
        )]
    evidences = [value for value in values if value is not None]
    assert len(evidences) == 1
    assert evidences[0].acknowledged is True
    assert _counts(result_factory, attempt_id) == (1, 9)


def validate_terminal_without_artifacts(worker_factory, result_factory, store, temporary: str) -> None:
    cancel_at = NOW + timedelta(hours=6)
    canceled, pipeline = _run_worker(
        worker_factory,
        store,
        temporary,
        job_id=JOB_CANCEL,
        attempt_id=ATTEMPT_CANCEL,
        command_id=COMMAND_CANCEL,
        suffix="result-cancel",
        at=cancel_at,
        status="cancel_requested",
    )
    assert canceled.terminal_status == "canceled" and pipeline.executions == 0
    cancel_result = DBIAnalysisResultConsumer(
        result_factory,
        store,
        clock=MutableClock(cancel_at + timedelta(seconds=1)),
        lease_seconds=10,
        retry_delay_seconds=0,
    ).process_one()
    assert cancel_result is not None and cancel_result.status == "canceled"
    assert _counts(result_factory, ATTEMPT_CANCEL) == (1, 0)

    failed_at = NOW + timedelta(hours=7)
    failed_pipeline = FailedPipelineAdapter()
    failed, _ = _run_worker(
        worker_factory,
        store,
        temporary,
        job_id=JOB_FAILED,
        attempt_id=ATTEMPT_FAILED,
        command_id=COMMAND_FAILED,
        suffix="result-failed",
        at=failed_at,
        pipeline=failed_pipeline,
    )
    assert failed.terminal_status == "failed" and failed_pipeline.executions == 1
    failed_result = DBIAnalysisResultConsumer(
        result_factory,
        store,
        clock=MutableClock(failed_at + timedelta(seconds=1)),
        lease_seconds=10,
        retry_delay_seconds=0,
    ).process_one()
    assert failed_result is not None and failed_result.status == "failed"
    assert _counts(result_factory, ATTEMPT_FAILED) == (1, 0)


def main() -> None:
    _require_scope()
    _provision_role_and_shared_fixture()
    _provision_result_role()
    validate_acl()

    worker_engine, worker_factory = _factory(WORKER_ROLE)
    result_engine, result_factory = _factory(RESULT_ROLE)
    store = _object_store()
    try:
        with tempfile.TemporaryDirectory() as temporary:
            validate_success(worker_factory, result_factory, store, temporary)
            validate_storage_tamper(worker_factory, result_factory, store, temporary)
            validate_post_commit_replay(worker_factory, result_factory, store, temporary)
            validate_divergent_result(worker_factory, result_factory, store, temporary)
            validate_concurrent_consumers(worker_factory, result_factory, store, temporary)
            validate_terminal_without_artifacts(
                worker_factory, result_factory, store, temporary
            )
    finally:
        worker_engine.dispose()
        result_engine.dispose()

    print(
        "DBI-RESULT-001 PostgreSQL aprobado: Worker→Queue→Result, Storage, replay, "
        "concurrencia, terminales sin parciales y ACL mínima."
    )


if __name__ == "__main__":
    main()
