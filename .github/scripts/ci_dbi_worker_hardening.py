"""Endurece ACL y recuperación de artefactos para DBI-WORKER-001."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.delivery.contracts import DeliveryStream  # noqa: E402
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt  # noqa: E402
from app.dbi.models.delivery import DBIDeliveryMessage  # noqa: E402
from app.dbi.storage_contracts import (  # noqa: E402
    DBIStorageIntegrityError,
    DBIStoragePurpose,
)
from app.dbi.worker.contracts import DBIWorkerFailureCode  # noqa: E402
from app.dbi.worker.service import DBIAnalysisWorkerService  # noqa: E402
from app.schemas.dbi_analysis_jobs import AnalysisJobResult  # noqa: E402
from ci_dbi_worker_integration import (  # noqa: E402
    DATABASE,
    FARM_ID,
    HOST,
    NOW,
    PORT,
    WORKER_ROLE,
    FakePipelineAdapter,
    MutableClock,
    _admin_connect,
    _engine_and_factory,
    _insert_job,
    _object_store,
)

JOB_ARTIFACT_FAILURE = UUID("83000000-0000-4000-8000-000000000006")
ATTEMPT_ARTIFACT_FAILURE = UUID("84000000-0000-4000-8000-000000000006")
MESSAGE_ARTIFACT_FAILURE = UUID("8a000000-0000-4000-8000-000000000006")


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("El hardening Worker sólo corre en GitHub Actions.")
    if os.environ.get("DBI_WORKER_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta habilitar DBI_WORKER_RUN_INTEGRATION.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("El hardening Worker exige DBI_ENVIRONMENT=test.")
    url = os.environ.get("DBI_DATABASE_URL", "")
    if WORKER_ROLE not in url or HOST not in url or DATABASE not in url:
        raise RuntimeError("DBI_DATABASE_URL no apunta al rol Worker autorizado.")


def _worker_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=WORKER_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def restrict_worker_role_to_operational_columns() -> None:
    """Reemplaza UPDATE de tabla por las columnas exactas usadas por el Worker."""

    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            for table_name in (
                "dbi_analysis_jobs",
                "dbi_analysis_job_attempts",
                "dbi_delivery_messages",
            ):
                cursor.execute(
                    sql.SQL("REVOKE UPDATE ON dbi.{} FROM {}").format(
                        sql.Identifier(table_name), sql.Identifier(WORKER_ROLE)
                    )
                )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, updated_at) "
                    "ON dbi.dbi_analysis_jobs TO {}"
                ).format(sql.Identifier(WORKER_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, worker_ref, pipeline_build_ref, result_sha256, "
                    "failure_code, started_at, finished_at, updated_at) "
                    "ON dbi.dbi_analysis_job_attempts TO {}"
                ).format(sql.Identifier(WORKER_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (status, delivery_count, available_at, lease_ref, "
                    "lease_expires_at, last_lease_ref, last_error_code, delivered_at, updated_at) "
                    "ON dbi.dbi_delivery_messages TO {}"
                ).format(sql.Identifier(WORKER_ROLE))
            )


def _assert_denied(statement: str, parameters: tuple) -> None:
    with _worker_connect() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(statement, parameters)
            except psycopg.errors.InsufficientPrivilege:
                return
    raise AssertionError("el rol Worker obtuvo una mutación de dominio no autorizada.")


def validate_minimal_acl() -> None:
    _assert_denied(
        "UPDATE dbi.dbi_farms SET name = name WHERE id = %s",
        (FARM_ID,),
    )
    _assert_denied(
        "UPDATE dbi.dbi_analysis_jobs SET model_version_ref = model_version_ref "
        "WHERE id IS NOT NULL",
        (),
    )


class FailingArtifactStore:
    """Falla durante el tercer artefacto y delega todo lo demás al store real."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.artifact_writes = 0

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def put(self, request, content):
        if request.metadata.address.purpose is DBIStoragePurpose.ANALYSIS_ARTIFACT:
            self.artifact_writes += 1
            if self.artifact_writes == 3:
                raise DBIStorageIntegrityError("synthetic artifact upload failure")
        return self._delegate.put(request, content)


def validate_partial_artifact_failure(factory, temporary: str) -> None:
    at = NOW + timedelta(minutes=50)
    _insert_job(
        JOB_ARTIFACT_FAILURE,
        ATTEMPT_ARTIFACT_FAILURE,
        MESSAGE_ARTIFACT_FAILURE,
        "artifact-failure",
        available_at=at,
    )
    store = FailingArtifactStore(_object_store())
    pipeline = FakePipelineAdapter()
    evidence = DBIAnalysisWorkerService(
        factory,
        store,
        workspace_root=temporary,
        worker_ref="worker-ci-artifact-failure",
        pipeline_adapter=pipeline,
        clock=MutableClock(at),
        lease_seconds=60,
        heartbeat_seconds=10,
    ).process_one()

    assert evidence is not None
    assert evidence.terminal_status == "failed"
    assert evidence.failure_code is DBIWorkerFailureCode.STORAGE_INTEGRITY
    assert evidence.acknowledged is True
    assert pipeline.executions == 1
    assert store.artifact_writes == 3

    session = factory()
    try:
        job = session.get(AnalysisJob, JOB_ARTIFACT_FAILURE)
        attempt = session.get(AnalysisJobAttempt, ATTEMPT_ARTIFACT_FAILURE)
        command = session.get(DBIDeliveryMessage, MESSAGE_ARTIFACT_FAILURE)
        assert job is not None and job.status == "failed"
        assert attempt is not None and attempt.status == "failed"
        assert attempt.failure_code == DBIWorkerFailureCode.STORAGE_INTEGRITY.value
        assert command is not None and command.status == "delivered"

        result_rows = session.execute(
            select(DBIDeliveryMessage).where(
                DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_RESULT.value,
                DBIDeliveryMessage.attempt_id == ATTEMPT_ARTIFACT_FAILURE,
            )
        ).scalars().all()
        assert len(result_rows) == 1
        result = AnalysisJobResult.model_validate_json(result_rows[0].payload_json)
        assert result.status == "failed"
        assert result.artifacts == []
        assert result.errors == [DBIWorkerFailureCode.STORAGE_INTEGRITY.value]
        assert session.scalar(
            select(func.count(DBIDeliveryMessage.id)).where(
                DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_RESULT.value,
                DBIDeliveryMessage.attempt_id == ATTEMPT_ARTIFACT_FAILURE,
            )
        ) == 1
    finally:
        session.close()


def main() -> None:
    _require_scope()
    restrict_worker_role_to_operational_columns()
    validate_minimal_acl()
    engine, factory = _engine_and_factory()
    try:
        with tempfile.TemporaryDirectory() as temporary:
            validate_partial_artifact_failure(factory, temporary)
    finally:
        engine.dispose()
    print(
        "DBI-WORKER-001 hardening aprobado: ACL por columna y fallo de artefactos seguro."
    )


if __name__ == "__main__":
    main()
