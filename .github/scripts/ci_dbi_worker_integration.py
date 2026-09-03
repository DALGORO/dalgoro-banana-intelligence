"""Integración PostgreSQL/PostGIS de DBI-WORKER-001 con pipeline sintético."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.delivery.contracts import (  # noqa: E402
    DeliveryMessageStatus,
    DeliveryStream,
    prepare_delivery_payload,
)
from app.dbi.delivery.repository import DBIDeliveryRepository  # noqa: E402
from app.dbi.jobs.service_contracts import contract_sha256  # noqa: E402
from app.dbi.models.analysis_jobs import AnalysisJob, AnalysisJobAttempt  # noqa: E402
from app.dbi.models.delivery import DBIDeliveryMessage  # noqa: E402
from app.dbi.storage_contracts import (  # noqa: E402
    DBIStoragePurpose,
    DBIStorageWriteRequest,
)
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from app.dbi.worker.contracts import (  # noqa: E402
    DBIWorkerAckPending,
    MODEL_ARTIFACT_TENANT_REF,
    PipelineExecutionEvidence,
)
from app.dbi.worker.heartbeat import DBIWorkerLeaseHeartbeat  # noqa: E402
from app.dbi.worker.service import DBIAnalysisWorkerService  # noqa: E402
from app.schemas.dbi_analysis_jobs import AnalysisJobCommand, AnalysisJobInputs  # noqa: E402

HOST = "127.0.0.1"
PORT = 5432
DATABASE = "dbi_test"
ADMIN_ROLE = "postgres"
WORKER_ROLE = "dbi_test_worker"
ORGANIZATION = "organization-ci-worker"
TENANT = "tenant-ci-worker"
FARM_ID = UUID("81000000-0000-4000-8000-000000000001")
PLOT_ID = UUID("82000000-0000-4000-8000-000000000001")
ORTHO_ID = UUID("85000000-0000-4000-8000-000000000001")
BOUNDARY_ID = UUID("86000000-0000-4000-8000-000000000001")
MODEL_ARTIFACT_ID = UUID("87000000-0000-4000-8000-000000000001")
MODEL_ROW_ID = UUID("88000000-0000-4000-8000-000000000001")
PIPELINE_ROW_ID = UUID("89000000-0000-4000-8000-000000000001")
MODEL_VERSION = "banana_worker_ci_v1"
PIPELINE_VERSION = "pipeline_worker_ci_v1"
NOW = datetime(2026, 9, 3, 5, 0, tzinfo=timezone.utc)

JOB_SUCCESS = UUID("83000000-0000-4000-8000-000000000001")
ATTEMPT_SUCCESS = UUID("84000000-0000-4000-8000-000000000001")
MESSAGE_SUCCESS = UUID("8a000000-0000-4000-8000-000000000001")
JOB_HEARTBEAT = UUID("83000000-0000-4000-8000-000000000002")
ATTEMPT_HEARTBEAT = UUID("84000000-0000-4000-8000-000000000002")
MESSAGE_HEARTBEAT = UUID("8a000000-0000-4000-8000-000000000002")
JOB_REPLAY = UUID("83000000-0000-4000-8000-000000000003")
ATTEMPT_REPLAY = UUID("84000000-0000-4000-8000-000000000003")
MESSAGE_REPLAY = UUID("8a000000-0000-4000-8000-000000000003")
JOB_CANCEL = UUID("83000000-0000-4000-8000-000000000004")
ATTEMPT_CANCEL = UUID("84000000-0000-4000-8000-000000000004")
MESSAGE_CANCEL = UUID("8a000000-0000-4000-8000-000000000004")
JOB_CONCURRENT = UUID("83000000-0000-4000-8000-000000000005")
ATTEMPT_CONCURRENT = UUID("84000000-0000-4000-8000-000000000005")
MESSAGE_CONCURRENT = UUID("8a000000-0000-4000-8000-000000000005")

ORTHO_PAYLOAD = b"ortho-ci-worker" * 8192
BOUNDARY_PAYLOAD = b"boundary-ci-worker" * 128
MODEL_PAYLOAD = b"model-ci-worker" * 4096


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class FakePipelineAdapter:
    def __init__(self) -> None:
        self.executions = 0

    def run(self, *, plan, workspace, heartbeat, cancel_requested):
        self.executions += 1
        heartbeat()
        if cancel_requested():
            return PipelineExecutionEvidence(status="canceled", return_code=0)

        run = workspace.output_root / f"run_{plan.attempt_id}"
        gis = run / "05_gis"
        (gis / "densidad_hexagonal_objetivo_1400").mkdir(parents=True)
        (gis / "prioridad_operativa_1400").mkdir(parents=True)
        (gis / "mapa_calor_kde_1400").mkdir(parents=True)
        maps = run / "06_mapas" / "paquete_cartografico_1400_dalgoro_v2"
        maps.mkdir(parents=True)
        report = run / "07_reporte" / "informe_dalgoro_v2_1400"
        report.mkdir(parents=True)

        files = {
            gis / "inventario_banano_validado.gpkg": b"validated-inventory",
            gis / "limite_analisis.gpkg": b"analysis-boundary",
            gis / "densidad_hexagonal_objetivo_1400" / "densidad_hexagonal.gpkg": b"hex",
            gis / "prioridad_operativa_1400" / "candidatos_siembra_priorizados.gpkg": b"priority",
            gis / "mapa_calor_kde_1400" / "densidad_kde_corregida_plantas_ha.tif": b"kde",
            maps / "mapa_01.png": b"png",
            report / "informe_tecnico_ci.pdf": b"pdf",
            run / "estado_pipeline.json": b'{"status":"completed"}',
            run / "manifiesto_pipeline.json": b'{"success":true}',
        }
        for path, payload in files.items():
            path.write_bytes(payload)
        heartbeat()
        return PipelineExecutionEvidence(
            status="succeeded",
            return_code=0,
            run_directory=str(run),
            pipeline_manifest_path=str(run / "manifiesto_pipeline.json"),
            pipeline_state_path=str(run / "estado_pipeline.json"),
        )


class CrashAfterResultWorker(DBIAnalysisWorkerService):
    def _ack(self, *, message_id, lease_ref) -> bool:
        raise RuntimeError("synthetic crash after durable result")


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración Worker sólo corre en GitHub Actions.")
    if os.environ.get("DBI_WORKER_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta habilitar DBI_WORKER_RUN_INTEGRATION.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración Worker exige DBI_ENVIRONMENT=test.")
    url = os.environ.get("DBI_DATABASE_URL", "")
    if WORKER_ROLE not in url or HOST not in url or DATABASE not in url:
        raise RuntimeError("DBI_DATABASE_URL no apunta al rol Worker de CI.")


def _admin_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=ADMIN_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _canonical_json(value: dict) -> tuple[str, str]:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _storage_metadata(*, tenant: str, purpose: DBIStoragePurpose, object_id: UUID, payload: bytes, content_type: str):
    return DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref=tenant,
            purpose=purpose,
            object_id=object_id,
        ),
        content_type=content_type,
        size_bytes=len(payload),
        sha256_hex=hashlib.sha256(payload).hexdigest(),
    )


def _object_store() -> DBIInMemoryObjectStore:
    store = DBIInMemoryObjectStore(max_object_size_bytes=4 * 1024 * 1024)
    for metadata, payload in (
        (
            _storage_metadata(
                tenant=TENANT,
                purpose=DBIStoragePurpose.ANALYSIS_INPUT,
                object_id=ORTHO_ID,
                payload=ORTHO_PAYLOAD,
                content_type="image/tiff",
            ),
            ORTHO_PAYLOAD,
        ),
        (
            _storage_metadata(
                tenant=TENANT,
                purpose=DBIStoragePurpose.ANALYSIS_INPUT,
                object_id=BOUNDARY_ID,
                payload=BOUNDARY_PAYLOAD,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            BOUNDARY_PAYLOAD,
        ),
        (
            _storage_metadata(
                tenant=MODEL_ARTIFACT_TENANT_REF,
                purpose=DBIStoragePurpose.MODEL_ARTIFACT,
                object_id=MODEL_ARTIFACT_ID,
                payload=MODEL_PAYLOAD,
                content_type="application/octet-stream",
            ),
            MODEL_PAYLOAD,
        ),
    ):
        store.put(DBIStorageWriteRequest(metadata=metadata), BytesIO(payload))
    return store


def _command(job_id: UUID, suffix: str) -> AnalysisJobCommand:
    return AnalysisJobCommand(
        request_id=f"request-worker-{suffix}",
        correlation_id=f"correlation-worker-{suffix}",
        job_id=str(job_id),
        tenant_id=TENANT,
        farm_id=str(FARM_ID),
        lot_id=str(PLOT_ID),
        inputs=AnalysisJobInputs(
            orthophoto_asset_id=str(ORTHO_ID),
            boundary_asset_id=str(BOUNDARY_ID),
            exclusions_asset_id=None,
        ),
        model_version_id=MODEL_VERSION,
        pipeline_config_version=PIPELINE_VERSION,
        requested_by="principal-worker-ci",
    )


def _provision_role_and_shared_fixture() -> None:
    config_json, config_sha = _canonical_json(
        {
            "target_density_plants_ha": 1400,
            "tile_size": 640,
            "overlap": 128,
            "confidence": 0.4,
            "iou": 0.7,
            "run_system_check": False,
            "run_boundary_validation": False,
        }
    )
    ortho_meta = _storage_metadata(
        tenant=TENANT,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=ORTHO_ID,
        payload=ORTHO_PAYLOAD,
        content_type="image/tiff",
    )
    boundary_meta = _storage_metadata(
        tenant=TENANT,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=BOUNDARY_ID,
        payload=BOUNDARY_PAYLOAD,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (WORKER_ROLE,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(WORKER_ROLE))
                )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DATABASE), sql.Identifier(WORKER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(WORKER_ROLE)
                )
            )
            for table_name in (
                "dbi_farms",
                "dbi_plots",
                "dbi_analysis_input_assets",
                "dbi_model_versions",
                "dbi_pipeline_config_versions",
            ):
                cursor.execute(
                    sql.SQL("GRANT SELECT ON dbi.{} TO {}").format(
                        sql.Identifier(table_name), sql.Identifier(WORKER_ROLE)
                    )
                )
            cursor.execute(
                sql.SQL("GRANT SELECT, UPDATE ON dbi.dbi_analysis_jobs TO {}").format(
                    sql.Identifier(WORKER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT, UPDATE ON dbi.dbi_analysis_job_attempts TO {}").format(
                    sql.Identifier(WORKER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE ON dbi.dbi_delivery_messages TO {}").format(
                    sql.Identifier(WORKER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(WORKER_ROLE)
                )
            )

            cursor.execute(
                """
                INSERT INTO dbi.dbi_farms
                    (id, organization_ref, code, name, status, created_at, updated_at)
                VALUES (%s, %s, 'CI-WORKER-FARM', 'Finca Worker CI', 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (FARM_ID, ORGANIZATION, NOW, NOW),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_plots
                    (id, farm_id, code, name, area_hectares, boundary, status, created_at, updated_at)
                VALUES (%s, %s, 'CI-WORKER-PLOT', 'Lote Worker CI', 1.0, NULL, 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (PLOT_ID, FARM_ID, NOW, NOW),
            )
            for object_id, kind, metadata, crs in (
                (ORTHO_ID, "orthophoto", ortho_meta, "EPSG:32717"),
                (BOUNDARY_ID, "boundary", boundary_meta, None),
            ):
                cursor.execute(
                    """
                    INSERT INTO dbi.dbi_analysis_input_assets
                        (id, tenant_ref, farm_id, plot_id, asset_kind, status, object_key,
                         content_type, size_bytes, sha256, crs, created_by_ref, verified_at,
                         created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'verified', %s, %s, %s, %s, %s,
                            'actor-worker-ci', %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        object_key = EXCLUDED.object_key,
                        content_type = EXCLUDED.content_type,
                        size_bytes = EXCLUDED.size_bytes,
                        sha256 = EXCLUDED.sha256,
                        crs = EXCLUDED.crs,
                        verified_at = EXCLUDED.verified_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        object_id,
                        TENANT,
                        FARM_ID,
                        PLOT_ID,
                        kind,
                        metadata.address.object_key,
                        metadata.content_type,
                        metadata.size_bytes,
                        metadata.sha256,
                        crs,
                        NOW,
                        NOW,
                        NOW,
                    ),
                )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_model_versions
                    (id, model_family, model_version, status, training_dataset_version,
                     validation_dataset_version, input_contract_version, output_contract_version,
                     artifact_ref, metrics_json, metrics_sha256, created_by_ref, approved_by_ref,
                     created_at, approved_at, retired_at)
                VALUES (%s, 'banana_detection', %s, 'approved', 'train_worker_ci',
                        'validation_worker_ci', 'orthophoto_tiles_v1', 'banana_detections_v1',
                        %s, NULL, NULL, 'actor-worker-ci', 'approver-worker-ci', %s, %s, NULL)
                ON CONFLICT (id) DO NOTHING
                """,
                (MODEL_ROW_ID, MODEL_VERSION, str(MODEL_ARTIFACT_ID), NOW, NOW),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_pipeline_config_versions
                    (id, model_family, config_version, status, config_json, config_sha256,
                     created_by_ref, approved_by_ref, created_at, approved_at, retired_at)
                VALUES (%s, 'banana_detection', %s, 'approved', %s, %s,
                        'actor-worker-ci', 'approver-worker-ci', %s, %s, NULL)
                ON CONFLICT (id) DO NOTHING
                """,
                (PIPELINE_ROW_ID, PIPELINE_VERSION, config_json, config_sha, NOW, NOW),
            )


def _insert_job(job_id: UUID, attempt_id: UUID, message_id: UUID, suffix: str, *, status: str = "queued", available_at: datetime) -> None:
    command = _command(job_id, suffix)
    payload = prepare_delivery_payload(command)
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO dbi.dbi_analysis_jobs
                    (id, tenant_ref, request_id, correlation_id, farm_id, plot_id, campaign_id,
                     orthophoto_asset_ref, boundary_asset_ref, exclusions_asset_ref,
                     model_version_ref, pipeline_config_version, requested_by_ref,
                     command_sha256, status, accepted_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s, NULL, %s, %s, %s,
                        %s, %s, %s, %s, %s)
                """,
                (
                    job_id,
                    TENANT,
                    command.request_id,
                    command.correlation_id,
                    FARM_ID,
                    PLOT_ID,
                    str(ORTHO_ID),
                    str(BOUNDARY_ID),
                    MODEL_VERSION,
                    PIPELINE_VERSION,
                    command.requested_by,
                    contract_sha256(command),
                    status,
                    available_at,
                    available_at,
                    available_at,
                ),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_analysis_job_attempts
                    (id, job_id, attempt_number, status, worker_ref, pipeline_build_ref,
                     result_sha256, failure_code, queued_at, started_at, finished_at,
                     created_at, updated_at)
                VALUES (%s, %s, 1, 'queued', NULL, NULL, NULL, NULL, %s, NULL, NULL, %s, %s)
                """,
                (attempt_id, job_id, available_at, available_at, available_at),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_delivery_messages
                    (id, stream, job_id, attempt_id, correlation_id, schema_version,
                     payload_json, payload_sha256, status, delivery_count, max_deliveries,
                     available_at, lease_ref, lease_expires_at, last_lease_ref,
                     last_error_code, delivered_at, created_at, updated_at)
                VALUES (%s, 'analysis_command', %s, %s, %s, %s, %s, %s,
                        'pending', 0, 5, %s, NULL, NULL, NULL, NULL, NULL, %s, %s)
                """,
                (
                    message_id,
                    job_id,
                    attempt_id,
                    command.correlation_id,
                    payload.schema_version,
                    payload.payload_json,
                    payload.payload_sha256,
                    available_at,
                    available_at,
                    available_at,
                ),
            )


def _engine_and_factory():
    engine = create_engine(
        os.environ["DBI_DATABASE_URL"],
        poolclass=NullPool,
        future=True,
    )
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _claim(factory, at: datetime, lease_seconds: int = 30):
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


def _ack(factory, lease, at: datetime) -> None:
    session = factory()
    try:
        DBIDeliveryRepository(session).ack(
            message_id=lease.envelope.message_id,
            lease_ref=lease.lease_ref,
            delivered_at=at,
        )
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def validate_success(factory, store, temporary: str) -> None:
    _insert_job(
        JOB_SUCCESS,
        ATTEMPT_SUCCESS,
        MESSAGE_SUCCESS,
        "success",
        available_at=NOW,
    )
    clock = MutableClock(NOW)
    pipeline = FakePipelineAdapter()
    evidence = DBIAnalysisWorkerService(
        factory,
        store,
        workspace_root=temporary,
        worker_ref="worker-ci-success",
        pipeline_adapter=pipeline,
        clock=clock,
        lease_seconds=60,
        heartbeat_seconds=10,
    ).process_one()
    assert evidence is not None
    assert evidence.terminal_status == "succeeded"
    assert evidence.acknowledged is True and evidence.replayed is False
    assert pipeline.executions == 1

    session = factory()
    try:
        job = session.get(AnalysisJob, JOB_SUCCESS)
        attempt = session.get(AnalysisJobAttempt, ATTEMPT_SUCCESS)
        assert job is not None and job.status == "succeeded"
        assert attempt is not None and attempt.status == "succeeded"
        assert attempt.worker_ref == "worker-ci-success"
        assert attempt.result_sha256 is not None
        command = session.get(DBIDeliveryMessage, MESSAGE_SUCCESS)
        assert command is not None and command.status == "delivered"
        result_count = session.scalar(
            select(func.count(DBIDeliveryMessage.id)).where(
                DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_RESULT.value,
                DBIDeliveryMessage.attempt_id == ATTEMPT_SUCCESS,
            )
        )
        assert result_count == 1
    finally:
        session.close()


def validate_heartbeat(factory) -> None:
    at = NOW + timedelta(minutes=10)
    _insert_job(
        JOB_HEARTBEAT,
        ATTEMPT_HEARTBEAT,
        MESSAGE_HEARTBEAT,
        "heartbeat",
        available_at=at,
    )
    lease = _claim(factory, at, lease_seconds=30)
    assert lease is not None and lease.envelope.message_id == MESSAGE_HEARTBEAT
    clock = MutableClock(at + timedelta(seconds=20))
    heartbeat = DBIWorkerLeaseHeartbeat(
        factory,
        message_id=MESSAGE_HEARTBEAT,
        lease_ref=lease.lease_ref,
        lease_seconds=30,
        interval_seconds=5,
        clock=clock,
    )
    assert heartbeat.beat(force=True) is True
    assert heartbeat.last_expires_at == at + timedelta(seconds=50)
    assert _claim(factory, at + timedelta(seconds=31), lease_seconds=30) is None
    recovered = _claim(factory, at + timedelta(seconds=51), lease_seconds=30)
    assert recovered is not None and recovered.envelope.message_id == MESSAGE_HEARTBEAT
    assert recovered.lease_ref != lease.lease_ref
    assert recovered.envelope.delivery_count == 2
    _ack(factory, recovered, at + timedelta(seconds=52))


def validate_result_before_ack_replay(factory, store, temporary: str) -> None:
    at = NOW + timedelta(minutes=20)
    _insert_job(
        JOB_REPLAY,
        ATTEMPT_REPLAY,
        MESSAGE_REPLAY,
        "replay",
        available_at=at,
    )
    clock = MutableClock(at)
    pipeline = FakePipelineAdapter()
    crashing = CrashAfterResultWorker(
        factory,
        store,
        workspace_root=temporary,
        worker_ref="worker-ci-crash",
        pipeline_adapter=pipeline,
        clock=clock,
        lease_seconds=30,
        heartbeat_seconds=10,
    )
    try:
        crashing.process_one()
    except DBIWorkerAckPending:
        pass
    else:
        raise AssertionError("el crash post-resultado debía dejar ACK pendiente.")
    assert pipeline.executions == 1

    session = factory()
    try:
        assert session.scalar(
            select(AnalysisJob.status).where(AnalysisJob.id == JOB_REPLAY)
        ) == "succeeded"
        command_status = session.scalar(
            select(DBIDeliveryMessage.status).where(DBIDeliveryMessage.id == MESSAGE_REPLAY)
        )
        assert command_status == "leased"
        assert session.scalar(
            select(func.count(DBIDeliveryMessage.id)).where(
                DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_RESULT.value,
                DBIDeliveryMessage.attempt_id == ATTEMPT_REPLAY,
            )
        ) == 1
    finally:
        session.close()

    clock.value = at + timedelta(seconds=31)
    replay = DBIAnalysisWorkerService(
        factory,
        store,
        workspace_root=temporary,
        worker_ref="worker-ci-replay",
        pipeline_adapter=pipeline,
        clock=clock,
        lease_seconds=30,
        heartbeat_seconds=10,
    ).process_one()
    assert replay is not None and replay.replayed is True
    assert replay.terminal_status == "succeeded" and replay.acknowledged is True
    assert pipeline.executions == 1, "replay no debe ejecutar de nuevo el pipeline"


def validate_cancel_before_start(factory, store, temporary: str) -> None:
    at = NOW + timedelta(minutes=30)
    _insert_job(
        JOB_CANCEL,
        ATTEMPT_CANCEL,
        MESSAGE_CANCEL,
        "cancel",
        status="cancel_requested",
        available_at=at,
    )
    clock = MutableClock(at)
    pipeline = FakePipelineAdapter()
    result = DBIAnalysisWorkerService(
        factory,
        store,
        workspace_root=temporary,
        worker_ref="worker-ci-cancel",
        pipeline_adapter=pipeline,
        clock=clock,
        lease_seconds=60,
        heartbeat_seconds=10,
    ).process_one()
    assert result is not None and result.terminal_status == "canceled"
    assert pipeline.executions == 0
    session = factory()
    try:
        assert session.scalar(
            select(AnalysisJob.status).where(AnalysisJob.id == JOB_CANCEL)
        ) == "canceled"
        attempt = session.get(AnalysisJobAttempt, ATTEMPT_CANCEL)
        assert attempt is not None and attempt.status == "canceled"
        assert attempt.started_at == at and attempt.finished_at == at
    finally:
        session.close()


def validate_concurrent_claim(factory) -> None:
    at = NOW + timedelta(minutes=40)
    _insert_job(
        JOB_CONCURRENT,
        ATTEMPT_CONCURRENT,
        MESSAGE_CONCURRENT,
        "concurrent",
        available_at=at,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_claim, factory, at, 30),
            executor.submit(_claim, factory, at, 30),
        ]
        claims = [future.result(timeout=20) for future in futures]
    leases = [item for item in claims if item is not None]
    assert len(leases) == 1
    assert leases[0].envelope.message_id == MESSAGE_CONCURRENT
    _ack(factory, leases[0], at + timedelta(seconds=1))


def main() -> None:
    _require_scope()
    _provision_role_and_shared_fixture()
    engine, factory = _engine_and_factory()
    store = _object_store()
    try:
        with tempfile.TemporaryDirectory() as temporary:
            validate_success(factory, store, temporary)
            validate_heartbeat(factory)
            validate_result_before_ack_replay(factory, store, temporary)
            validate_cancel_before_start(factory, store, temporary)
            validate_concurrent_claim(factory)
    finally:
        engine.dispose()

    print(
        "DBI-WORKER-001 PostgreSQL aprobado: ejecución terminal, heartbeat, "
        "recovery post-resultado, cancelación y claim concurrente."
    )


if __name__ == "__main__":
    main()
