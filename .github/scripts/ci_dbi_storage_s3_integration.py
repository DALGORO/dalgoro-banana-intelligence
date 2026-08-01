"""Prueba el adaptador DBI contra un S3 efímero con datos sintéticos."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.storage_contracts import (  # noqa: E402
    DBIStorageAccessMode,
    DBIStorageConflict,
    DBIStorageError,
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


class _DiagnosticS3Client:
    """Registra solo operación y clase de error; nunca argumentos o secretos."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.last_operation: str | None = None
        self.last_error_type: str | None = None

    def __getattr__(self, name: str):
        target = getattr(self._delegate, name)
        if not callable(target):
            return target

        def wrapped(*args, **kwargs):
            self.last_operation = name
            self.last_error_type = None
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


def _validate_integration(
    store: DBIS3ObjectStore,
    *,
    endpoint: str,
    bucket: str,
) -> None:
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

    _assert_anonymous_denied(
        endpoint,
        bucket,
        signed.metadata.address.object_key,
    )

    retired_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    assert store.retire(direct.metadata.address, retired_at=retired_at) is True
    assert store.retire(direct.metadata.address, retired_at=retired_at) is False
    _assert_error(DBIStorageNotFound, lambda: store.stat(direct.metadata.address))
    _assert_error(
        DBIStorageConflict,
        lambda: store.put(direct, BytesIO(PAYLOAD_DIRECT)),
    )

    signed_retired_at = retired_at + timedelta(seconds=1)
    assert store.retire(
        signed.metadata.address,
        retired_at=signed_retired_at,
    ) is True
    _assert_error(DBIStorageNotFound, lambda: store.stat(signed.metadata.address))

    assert PAYLOAD_DIRECT.decode("ascii") not in repr(store)
    assert PAYLOAD_SIGNED.decode("ascii") not in repr(store)


def main() -> None:
    endpoint = _required_env("DBI_STORAGE_S3_ENDPOINT_URL")
    bucket = _required_env("DBI_STORAGE_S3_BUCKET")
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
    diagnostic_client = _DiagnosticS3Client(build_s3_client(config))
    store = DBIS3ObjectStore(config, client=diagnostic_client)

    try:
        _validate_integration(store, endpoint=endpoint, bucket=bucket)
    except DBIStorageError:
        operation = diagnostic_client.last_operation or "unknown"
        error_type = diagnostic_client.last_error_type or "unknown"
        print(
            "Diagnóstico S3 seguro: "
            f"operation={operation} error_type={error_type}",
            file=sys.stderr,
        )
        raise

    print("Almacenamiento DBI: integración S3 efímera aprobada.")


if __name__ == "__main__":
    main()
