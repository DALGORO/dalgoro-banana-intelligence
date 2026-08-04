"""Ciclo multipartes real sobre S3 efímero, sintético y loopback."""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from urllib.request import Request, urlopen
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.asset_multipart_contracts import (  # noqa: E402
    DBIMultipartPartEvidence,
    DBIMultipartRoutingDecision,
)
from app.dbi.asset_multipart_metrics import (  # noqa: E402
    DBIMeteredMultipartObjectStore,
    DBIMultipartMetrics,
)
from app.dbi.asset_multipart_policy import (  # noqa: E402
    MIB,
    DBIMultipartPolicy,
)
from app.dbi.asset_multipart_provider import (  # noqa: E402
    DBIMultipartProviderAbortRequest,
    DBIMultipartProviderCompleteRequest,
    DBIMultipartProviderInitiateRequest,
    DBIMultipartProviderPartGrantRequest,
)
from app.dbi.asset_multipart_s3 import DBIS3MultipartAdapter  # noqa: E402
from app.dbi.storage_contracts import DBIStoragePurpose  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from app.dbi.storage_s3 import (  # noqa: E402
    DBIS3ObjectStoreConfig,
    build_s3_client,
)

S3_ENDPOINT = "http://127.0.0.1:8333"
S3_BUCKET = "dbi-ci-synthetic"
TENANT_REF = "tenant-ci-multipart"
COMPLETED_OBJECT_ID = UUID("74000000-0000-4000-8000-000000000001")
ABORTED_OBJECT_ID = UUID("74000000-0000-4000-8000-000000000002")
COMPLETED_SESSION_ID = UUID("75000000-0000-4000-8000-000000000001")
ABORTED_SESSION_ID = UUID("75000000-0000-4000-8000-000000000002")
SIZE_BYTES = 65 * MIB
NOW = datetime(2026, 8, 4, 16, 0, tzinfo=timezone.utc)
HASH_CHUNK_BYTES = MIB


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable efímera {name}.")
    return value


def _require_ci_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración multipartes solo corre en GitHub Actions.")
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL no está permitida en esta integración.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración multipartes exige ambiente test.")
    if os.environ.get("DBI_ASSET_RUN_INTEGRATION") != "1":
        raise RuntimeError("La integración multipartes no fue habilitada.")
    if _required_env("DBI_STORAGE_S3_ENDPOINT_URL") != S3_ENDPOINT:
        raise RuntimeError("El endpoint S3 debe ser el loopback efímero aprobado.")
    if _required_env("DBI_STORAGE_S3_BUCKET") != S3_BUCKET:
        raise RuntimeError("El bucket S3 debe ser el fixture sintético aprobado.")


def _digest_repeated(value: int, size_bytes: int) -> tuple[str, str]:
    digest = sha256()
    chunk = bytes((value,)) * min(HASH_CHUNK_BYTES, size_bytes)
    remaining = size_bytes
    while remaining:
        current = min(len(chunk), remaining)
        digest.update(chunk[:current])
        remaining -= current
    return digest.hexdigest(), base64.b64encode(digest.digest()).decode("ascii")


def _full_sha256_hex(plan) -> str:
    digest = sha256()
    for part_number in range(1, plan.part_count + 1):
        size_bytes = DBIMultipartPolicy.expected_part_size(
            plan,
            part_number=part_number,
        )
        value = 64 + part_number
        chunk = bytes((value,)) * min(HASH_CHUNK_BYTES, size_bytes)
        remaining = size_bytes
        while remaining:
            current = min(len(chunk), remaining)
            digest.update(chunk[:current])
            remaining -= current
    return digest.hexdigest()


def _config() -> DBIS3ObjectStoreConfig:
    return DBIS3ObjectStoreConfig(
        endpoint_url=_required_env("DBI_STORAGE_S3_ENDPOINT_URL"),
        bucket=_required_env("DBI_STORAGE_S3_BUCKET"),
        region="us-east-1",
        access_key_id=_required_env("AWS_ACCESS_KEY_ID"),
        secret_access_key=_required_env("AWS_SECRET_ACCESS_KEY"),
        session_token=os.environ.get("AWS_SESSION_TOKEN"),
        verify_tls=True,
        connect_timeout_seconds=3,
        read_timeout_seconds=90,
        max_attempts=2,
        max_object_size_bytes=128 * MIB,
    )


def _initiation(*, session_id: UUID, object_id: UUID):
    plan = DBIMultipartPolicy.build_upload_plan(size_bytes=SIZE_BYTES)
    if (
        plan.decision is not DBIMultipartRoutingDecision.MULTIPART
        or plan.part_count != 2
        or plan.part_size_bytes != 64 * MIB
    ):
        raise AssertionError("El fixture grande no siguió la política multipartes.")
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref=TENANT_REF,
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=object_id,
        ),
        content_type="image/tiff",
        size_bytes=SIZE_BYTES,
        sha256_hex=_full_sha256_hex(plan),
    )
    return DBIMultipartProviderInitiateRequest(
        session_id=session_id,
        metadata=metadata,
        plan=plan,
        initiated_at=NOW,
    )


def _upload_part(store, upload, *, part_number: int) -> DBIMultipartPartEvidence:
    size_bytes = DBIMultipartPolicy.expected_part_size(
        upload.plan,
        part_number=part_number,
    )
    value = 64 + part_number
    _hex_digest, checksum = _digest_repeated(value, size_bytes)
    grant = store.issue_part_access(
        DBIMultipartProviderPartGrantRequest(
            upload=upload,
            part_number=part_number,
            size_bytes=size_bytes,
            checksum=checksum,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
        )
    )
    access = store.resolve_part_access(
        grant.grant_ref,
        now=NOW + timedelta(seconds=1),
    )
    request = Request(
        access.url,
        data=bytes((value,)) * size_bytes,
        headers=dict(access.headers),
        method=access.method,
    )
    with urlopen(request, timeout=120) as response:
        etag = response.headers.get("ETag", "").strip('"')
        if response.status not in {200, 201} or not etag:
            raise AssertionError("S3 no confirmó la parte sintética.")
    return DBIMultipartPartEvidence(
        session_id=upload.session_id,
        part_number=part_number,
        size_bytes=size_bytes,
        checksum=checksum,
        etag=etag,
    )


def _no_incomplete_upload(raw_client, object_key: str) -> bool:
    response = raw_client.list_multipart_uploads(
        Bucket=S3_BUCKET,
        Prefix=object_key,
        MaxUploads=10,
    )
    return not any(
        item.get("Key") == object_key
        for item in response.get("Uploads", [])
        if isinstance(item, dict)
    )


def _write_summary(snapshot, *, latency_ms: float) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    safe_metrics = {
        "bytes": snapshot.completed_bytes,
        "parts": snapshot.completed_parts,
        "retries": snapshot.retry_recovery_attempts,
        "conflicts": snapshot.provider_conflicts,
        "residues": snapshot.residual_uploads_observed,
        "provider_duration_us": snapshot.provider_duration_microseconds,
    }
    with open(summary_path, "a", encoding="utf-8") as stream:
        stream.write("## DBI-ASSET-003 · S3 multipartes efímero\n\n")
        stream.write(f"- Latencia total: `{latency_ms:.2f} ms`\n")
        stream.write(
            "- Métricas agregadas: `"
            + json.dumps(safe_metrics, sort_keys=True, separators=(",", ":"))
            + "`\n"
        )
        stream.write("- Binario atravesó la API DBI: `no`\n")
        stream.write("- Residuo multipartes al cerrar: `0`\n")
        stream.write("- Costo directo de proveedor externo: `USD 0.00`\n")


def main() -> None:
    _require_ci_scope()
    config = _config()
    raw_client = build_s3_client(config)
    metrics = DBIMultipartMetrics()
    store = DBIMeteredMultipartObjectStore(
        DBIS3MultipartAdapter(config, client=raw_client),
        metrics,
    )
    completed_request = _initiation(
        session_id=COMPLETED_SESSION_ID,
        object_id=COMPLETED_OBJECT_ID,
    )
    aborted_request = _initiation(
        session_id=ABORTED_SESSION_ID,
        object_id=ABORTED_OBJECT_ID,
    )
    started_at = perf_counter()
    pending_uploads = []

    try:
        completed_upload = store.initiate(completed_request)
        pending_uploads.append(completed_upload)
        parts = tuple(
            _upload_part(store, completed_upload, part_number=number)
            for number in range(1, completed_upload.plan.part_count + 1)
        )
        completion = store.complete(
            DBIMultipartProviderCompleteRequest(
                upload=completed_upload,
                parts=parts,
            )
        )
        if not completion.created or completion.metadata.size_bytes != SIZE_BYTES:
            raise AssertionError("La finalización S3 no fue canónica.")
        inspected = store.inspect_completed(completed_upload)
        if (
            inspected.created
            or inspected.metadata != completion.metadata
            or not _no_incomplete_upload(
                raw_client,
                completed_upload.metadata.address.object_key,
            )
        ):
            raise AssertionError("La recuperación idempotente no fue canónica.")
        pending_uploads.remove(completed_upload)

        aborted_upload = store.initiate(aborted_request)
        pending_uploads.append(aborted_upload)
        _upload_part(store, aborted_upload, part_number=1)
        confirmation = store.abort(
            DBIMultipartProviderAbortRequest(
                session_id=aborted_upload.session_id,
                metadata=aborted_upload.metadata,
                plan=aborted_upload.plan,
                initiated_at=aborted_upload.initiated_at,
                requested_at=NOW + timedelta(minutes=5),
                provider_upload_ref=aborted_upload.provider_upload_ref,
            )
        )
        if (
            not confirmation.cleanup_confirmed
            or confirmation.provider_uploads_aborted != 1
            or not _no_incomplete_upload(
                raw_client,
                aborted_upload.metadata.address.object_key,
            )
        ):
            raise AssertionError("La limpieza S3 dejó residuos multipartes.")
        pending_uploads.remove(aborted_upload)

        snapshot = metrics.snapshot()
        if (
            snapshot.completed_bytes != SIZE_BYTES
            or snapshot.completed_parts != 2
            or snapshot.part_grants_issued != 3
            or snapshot.retry_recovery_attempts != 1
            or snapshot.provider_uploads_aborted != 1
            or snapshot.residual_uploads_observed != 0
        ):
            raise AssertionError("Las métricas de integración son divergentes.")
        latency_ms = (perf_counter() - started_at) * 1000
        _write_summary(snapshot, latency_ms=latency_ms)
        print(
            "dbi multipart s3 integration passed "
            f"bytes={snapshot.completed_bytes} parts={snapshot.completed_parts} "
            f"retries={snapshot.retry_recovery_attempts} residues=0"
        )
    finally:
        for upload in pending_uploads:
            try:
                raw_client.abort_multipart_upload(
                    Bucket=S3_BUCKET,
                    Key=upload.metadata.address.object_key,
                    UploadId=upload.provider_upload_ref,
                )
            except Exception:
                pass
        raw_client.delete_object(
            Bucket=S3_BUCKET,
            Key=completed_request.metadata.address.object_key,
        )
        raw_client.delete_object(
            Bucket=S3_BUCKET,
            Key=aborted_request.metadata.address.object_key,
        )


if __name__ == "__main__":
    main()
