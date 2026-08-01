"""Prueba el adaptador DBI contra un S3 efímero con datos sintéticos."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.storage_contracts import (  # noqa: E402
    DBIStorageAccessMode,
    DBIStorageConflict,
    DBIStorageDenied,
    DBIStorageError,
    DBIStorageIntegrityError,
    DBIStorageNotFound,
    DBIStoragePurpose,
    DBIStorageWriteRequest,
)
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from app.dbi.storage_s3 import (  # noqa: E402
    DBIS3ObjectStore,
    DBIS3ObjectStoreConfig,
    build_s3_client,
)

PAYLOAD_DIRECT = b"dbi-synthetic-direct-object"
PAYLOAD_SIGNED = b"dbi-synthetic-signed-object"
PAYLOAD_RECOVERY = b"dbi-synthetic-recovery-object"
PAYLOAD_INCOMPLETE = b"dbi-synthetic-incomplete-object"
PAYLOAD_FORBIDDEN = b"dbi-synthetic-forbidden-object"


class _DiagnosticS3Client:
    """Registra solo operación y clase de error; nunca argumentos o secretos."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.last_operation: str | None = None
        self.last_error_type: str | None = None
        self.operation_counts: Counter[str] = Counter()

    def __getattr__(self, name: str):
        target = getattr(self._delegate, name)
        if not callable(target):
            return target

        def wrapped(*args, **kwargs):
            self.last_operation = name
            self.last_error_type = None
            self.operation_counts[name] += 1
            try:
                return target(*args, **kwargs)
            except Exception as error:
                self.last_error_type = type(error).__name__
                raise

        return wrapped


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable efímera {name}.")
    return value


def _request(payload: bytes) -> DBIStorageWriteRequest:
    address = DBIStoragePolicy.build_address(
        tenant_ref="tenant-ci-synthetic",
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=uuid4(),
    )
    return DBIStorageWriteRequest(
        metadata=DBIStoragePolicy.build_metadata(
            address=address,
            content_type="application/octet-stream",
            size_bytes=len(payload),
            sha256_hex=sha256(payload).hexdigest(),
        )
    )


def _assert_error(error_type, factory) -> None:
    try:
        factory()
    except error_type:
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}.")


def _execute_signed_put(url: str, headers, payload: bytes) -> None:
    request = Request(
        url,
        data=payload,
        headers=dict(headers),
        method="PUT",
    )
    with urlopen(request, timeout=10) as response:
        assert response.status in {200, 201, 204}
        response.read()


def _execute_signed_put_denied(url: str, headers, payload: bytes) -> None:
    incomplete_headers = dict(headers)
    incomplete_headers.pop("x-amz-meta-dbi-sha256")
    request = Request(
        url,
        data=payload,
        headers=incomplete_headers,
        method="PUT",
    )
    try:
        urlopen(request, timeout=10)
    except HTTPError as error:
        assert error.code in {400, 403}
        error.close()
        return
    raise AssertionError("Una carga firmada sin un header obligatorio debía fallar.")


def _execute_signed_get(url: str) -> bytes:
    with urlopen(Request(url, method="GET"), timeout=10) as response:
        assert response.status == 200
        return response.read()


def _assert_anonymous_denied(endpoint: str, bucket: str, object_key: str) -> None:
    url = f"{endpoint.rstrip('/')}/{bucket}/{object_key}"
    try:
        urlopen(Request(url, method="GET"), timeout=5)
    except HTTPError as error:
        assert error.code == 403
        error.close()
        return
    raise AssertionError("El objeto sintético no puede leerse anónimamente.")


def _build_store(
    config: DBIS3ObjectStoreConfig,
) -> tuple[DBIS3ObjectStore, _DiagnosticS3Client]:
    diagnostic_client = _DiagnosticS3Client(build_s3_client(config))
    return (
        DBIS3ObjectStore(config, client=diagnostic_client),
        diagnostic_client,
    )


def _validate_integration(
    store: DBIS3ObjectStore,
    diagnostic_client: _DiagnosticS3Client,
    *,
    config: DBIS3ObjectStoreConfig,
    endpoint: str,
    bucket: str,
    forbidden_bucket: str,
) -> dict[str, object]:
    started_at = perf_counter()

    direct = _request(PAYLOAD_DIRECT)
    created = store.put(direct, BytesIO(PAYLOAD_DIRECT))
    assert created.created is True
    repeated = store.put(direct, BytesIO(PAYLOAD_DIRECT))
    assert repeated.created is False
    assert repeated.record == created.record
    assert store.stat(direct.metadata.address) == created.record
    with store.open_read(direct.metadata.address) as stream:
        assert stream.read() == PAYLOAD_DIRECT

    _assert_error(
        DBIStorageConflict,
        lambda: store.put(
            DBIStorageWriteRequest(
                metadata=replace(direct.metadata, content_type="image/tiff")
            ),
            BytesIO(PAYLOAD_DIRECT),
        ),
    )

    incomplete = _request(PAYLOAD_INCOMPLETE)
    calls_before_incomplete = sum(diagnostic_client.operation_counts.values())
    _assert_error(
        DBIStorageIntegrityError,
        lambda: store.put(incomplete, BytesIO(PAYLOAD_INCOMPLETE[:-1])),
    )
    assert sum(diagnostic_client.operation_counts.values()) == calls_before_incomplete
    _assert_error(
        DBIStorageNotFound,
        lambda: store.stat(incomplete.metadata.address),
    )
    recovered_direct = store.put(incomplete, BytesIO(PAYLOAD_INCOMPLETE))
    assert recovered_direct.created is True

    signed = _request(PAYLOAD_SIGNED)
    issued_at = datetime.now(timezone.utc)
    write_grant = store.issue_temporary_access(
        signed.metadata,
        mode=DBIStorageAccessMode.WRITE,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=5),
    )
    write_access = store.resolve_temporary_access(
        write_grant.grant_ref,
        now=issued_at,
    )
    _execute_signed_put(
        write_access.url,
        write_access.headers,
        PAYLOAD_SIGNED,
    )
    signed_record = store.stat(signed.metadata.address)
    assert signed_record.metadata == signed.metadata

    read_issued_at = datetime.now(timezone.utc)
    read_grant = store.issue_temporary_access(
        signed.metadata,
        mode=DBIStorageAccessMode.READ,
        issued_at=read_issued_at,
        expires_at=read_issued_at + timedelta(minutes=5),
    )
    read_access = store.resolve_temporary_access(
        read_grant.grant_ref,
        now=read_issued_at,
    )
    assert _execute_signed_get(read_access.url) == PAYLOAD_SIGNED

    recovery = _request(PAYLOAD_RECOVERY)
    recovery_issued_at = datetime.now(timezone.utc)
    failed_grant = store.issue_temporary_access(
        recovery.metadata,
        mode=DBIStorageAccessMode.WRITE,
        issued_at=recovery_issued_at,
        expires_at=recovery_issued_at + timedelta(minutes=5),
    )
    failed_access = store.resolve_temporary_access(
        failed_grant.grant_ref,
        now=recovery_issued_at,
    )
    _execute_signed_put_denied(
        failed_access.url,
        failed_access.headers,
        PAYLOAD_RECOVERY,
    )
    _assert_error(
        DBIStorageNotFound,
        lambda: store.stat(recovery.metadata.address),
    )

    retry_issued_at = datetime.now(timezone.utc)
    retry_grant = store.issue_temporary_access(
        recovery.metadata,
        mode=DBIStorageAccessMode.WRITE,
        issued_at=retry_issued_at,
        expires_at=retry_issued_at + timedelta(minutes=5),
    )
    retry_access = store.resolve_temporary_access(
        retry_grant.grant_ref,
        now=retry_issued_at,
    )
    _execute_signed_put(
        retry_access.url,
        retry_access.headers,
        PAYLOAD_RECOVERY,
    )
    assert store.stat(recovery.metadata.address).metadata == recovery.metadata

    _assert_anonymous_denied(
        endpoint,
        bucket,
        signed.metadata.address.object_key,
    )

    forbidden_store, forbidden_client = _build_store(
        replace(config, bucket=forbidden_bucket)
    )
    forbidden_request = _request(PAYLOAD_FORBIDDEN)
    _assert_error(
        DBIStorageDenied,
        lambda: forbidden_store.put(
            forbidden_request,
            BytesIO(PAYLOAD_FORBIDDEN),
        ),
    )
    _assert_error(
        DBIStorageDenied,
        lambda: forbidden_store.stat(forbidden_request.metadata.address),
    )

    retired_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    for index, request in enumerate(
        (direct, incomplete, signed, recovery),
        start=0,
    ):
        request_retired_at = retired_at + timedelta(seconds=index)
        assert store.retire(
            request.metadata.address,
            retired_at=request_retired_at,
        ) is True
        assert store.retire(
            request.metadata.address,
            retired_at=request_retired_at,
        ) is False
        _assert_error(
            DBIStorageNotFound,
            lambda request=request: store.stat(request.metadata.address),
        )
        _assert_error(
            DBIStorageConflict,
            lambda request=request: store.put(
                request,
                BytesIO(
                    {
                        direct.metadata.address.object_id: PAYLOAD_DIRECT,
                        incomplete.metadata.address.object_id: PAYLOAD_INCOMPLETE,
                        signed.metadata.address.object_id: PAYLOAD_SIGNED,
                        recovery.metadata.address.object_id: PAYLOAD_RECOVERY,
                    }[request.metadata.address.object_id]
                ),
            ),
        )

    for payload in (
        PAYLOAD_DIRECT,
        PAYLOAD_SIGNED,
        PAYLOAD_RECOVERY,
        PAYLOAD_INCOMPLETE,
        PAYLOAD_FORBIDDEN,
    ):
        assert payload.decode("ascii") not in repr(store)

    combined_operations = diagnostic_client.operation_counts.copy()
    combined_operations.update(forbidden_client.operation_counts)
    elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
    summary: dict[str, object] = {
        "elapsed_ms": elapsed_ms,
        "external_provider_cost_usd": 0.0,
        "failed_uploads_recovered": 2,
        "provider_operations": dict(sorted(combined_operations.items())),
        "synthetic_objects_created": 4,
        "synthetic_unique_bytes": sum(
            len(payload)
            for payload in (
                PAYLOAD_DIRECT,
                PAYLOAD_SIGNED,
                PAYLOAD_RECOVERY,
                PAYLOAD_INCOMPLETE,
            )
        ),
    }
    assert elapsed_ms > 0
    assert summary["external_provider_cost_usd"] == 0.0
    assert combined_operations["put_object"] > 0
    assert combined_operations["head_object"] > 0
    assert combined_operations["get_object"] > 0
    assert combined_operations["put_object_tagging"] > 0
    return summary


def _write_safe_summary(summary: dict[str, object]) -> None:
    rendered = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    print(f"Métricas S3 sintéticas: {rendered}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    operations = summary["provider_operations"]
    assert isinstance(operations, dict)
    with Path(summary_path).open("a", encoding="utf-8") as stream:
        stream.write("\n## DBI-STORAGE-001 · métricas de integración S3\n\n")
        stream.write(f"- Duración funcional: `{summary['elapsed_ms']} ms`\n")
        stream.write(
            f"- Objetos sintéticos creados: `{summary['synthetic_objects_created']}`\n"
        )
        stream.write(
            f"- Bytes sintéticos únicos: `{summary['synthetic_unique_bytes']}`\n"
        )
        stream.write(
            f"- Cargas fallidas recuperadas: `{summary['failed_uploads_recovered']}`\n"
        )
        stream.write(
            f"- Costo directo del proveedor externo: `${summary['external_provider_cost_usd']:.2f}`\n"
        )
        stream.write(
            "- Operaciones proveedor: `"
            + json.dumps(operations, sort_keys=True, separators=(",", ":"))
            + "`\n"
        )
        stream.write(
            "- Facturación del runner: fuera del alcance de esta métrica; depende del plan de GitHub.\n"
        )


def main() -> None:
    endpoint = _required_env("DBI_STORAGE_S3_ENDPOINT_URL")
    bucket = _required_env("DBI_STORAGE_S3_BUCKET")
    forbidden_bucket = _required_env("DBI_STORAGE_S3_FORBIDDEN_BUCKET")
    access_key = _required_env("AWS_ACCESS_KEY_ID")
    secret_key = _required_env("AWS_SECRET_ACCESS_KEY")

    config = DBIS3ObjectStoreConfig(
        endpoint_url=endpoint,
        bucket=bucket,
        region="us-east-1",
        access_key_id=access_key,
        secret_access_key=secret_key,
        verify_tls=True,
        connect_timeout_seconds=3,
        read_timeout_seconds=10,
        max_attempts=2,
        max_object_size_bytes=1024 * 1024,
    )
    store, diagnostic_client = _build_store(config)

    try:
        summary = _validate_integration(
            store,
            diagnostic_client,
            config=config,
            endpoint=endpoint,
            bucket=bucket,
            forbidden_bucket=forbidden_bucket,
        )
    except DBIStorageError:
        operation = diagnostic_client.last_operation or "unknown"
        error_type = diagnostic_client.last_error_type or "unknown"
        print(
            "Diagnóstico S3 seguro: "
            f"operation={operation} error_type={error_type}",
            file=sys.stderr,
        )
        raise

    _write_safe_summary(summary)
    print("Almacenamiento DBI: integración S3 efímera aprobada.")


if __name__ == "__main__":
    main()
