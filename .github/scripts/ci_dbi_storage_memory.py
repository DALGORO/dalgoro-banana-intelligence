"""Valida el adaptador en memoria del almacenamiento privado DBI."""

from __future__ import annotations

import ast
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.storage_contracts import (  # noqa: E402
    DBIStorageAccessMode,
    DBIStorageConflict,
    DBIStorageIntegrityError,
    DBIStorageNotFound,
    DBIStorageObjectState,
    DBIStoragePurpose,
    DBIStorageWriteRequest,
)
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402

NOW = datetime(2026, 8, 1, 21, 0, tzinfo=timezone.utc)
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
PAYLOAD = b"verified-private-object"


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _request(
    *,
    tenant_ref: str = TENANT_A,
    object_id=None,
    payload: bytes = PAYLOAD,
    content_type: str = "application/octet-stream",
) -> DBIStorageWriteRequest:
    address = DBIStoragePolicy.build_address(
        tenant_ref=tenant_ref,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=object_id or uuid4(),
    )
    return DBIStorageWriteRequest(
        metadata=DBIStoragePolicy.build_metadata(
            address=address,
            content_type=content_type,
            size_bytes=len(payload),
            sha256_hex=_digest(payload),
        )
    )


def _assert_error(error_type, factory) -> None:
    try:
        factory()
    except error_type:
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}.")


def _store(*, max_object_size_bytes: int = 1024) -> DBIInMemoryObjectStore:
    grants = iter(
        (
            "grant_01J00000000000000000000000",
            "grant_01J00000000000000000000001",
            "grant_01J00000000000000000000002",
            "grant_01J00000000000000000000003",
        )
    )
    return DBIInMemoryObjectStore(
        clock=lambda: NOW,
        grant_ref_factory=lambda: next(grants),
        max_object_size_bytes=max_object_size_bytes,
    )


def validate_write_read_and_stat() -> None:
    store = _store()
    request = _request()

    result = store.put(request, BytesIO(PAYLOAD))
    assert result.created is True
    assert result.record.metadata == request.metadata
    assert result.record.state is DBIStorageObjectState.ACTIVE
    assert result.record.created_at == NOW
    assert result.record.retired_at is None

    record = store.stat(request.metadata.address)
    assert record == result.record
    with store.open_read(request.metadata.address) as stream:
        assert stream.read() == PAYLOAD
        assert stream.read() == b""
    assert stream.closed is True

    with store.open_read(request.metadata.address) as second_stream:
        assert second_stream is not stream
        assert second_stream.read(8) == PAYLOAD[:8]


def validate_exact_idempotency_and_conflicts() -> None:
    store = _store()
    object_id = uuid4()
    request = _request(object_id=object_id)
    first = store.put(request, BytesIO(PAYLOAD))
    second = store.put(request, BytesIO(PAYLOAD))
    assert first.created is True
    assert second.created is False
    assert second.record == first.record

    divergent_metadata = replace(
        request.metadata,
        content_type="image/tiff",
    )
    _assert_error(
        DBIStorageConflict,
        lambda: store.put(
            DBIStorageWriteRequest(metadata=divergent_metadata),
            BytesIO(PAYLOAD),
        ),
    )

    divergent_payload = b"different-private-object"
    divergent_request = _request(
        object_id=object_id,
        payload=divergent_payload,
    )
    _assert_error(
        DBIStorageConflict,
        lambda: store.put(divergent_request, BytesIO(divergent_payload)),
    )
    assert store.stat(request.metadata.address) == first.record


def validate_integrity_before_storage() -> None:
    store = _store(max_object_size_bytes=64)
    request = _request()

    _assert_error(
        DBIStorageIntegrityError,
        lambda: store.put(request, BytesIO(PAYLOAD[:-1])),
    )
    _assert_error(
        DBIStorageIntegrityError,
        lambda: store.put(request, BytesIO(PAYLOAD + b"x")),
    )
    _assert_error(
        DBIStorageIntegrityError,
        lambda: store.put(request, BytesIO(b"x" * len(PAYLOAD))),
    )
    _assert_error(
        DBIStorageIntegrityError,
        lambda: store.put(request, StringIO(PAYLOAD.decode("ascii"))),
    )
    _assert_error(
        DBIStorageNotFound,
        lambda: store.stat(request.metadata.address),
    )

    oversized_store = _store(max_object_size_bytes=len(PAYLOAD) - 1)
    _assert_error(
        DBIStorageIntegrityError,
        lambda: oversized_store.put(request, BytesIO(PAYLOAD)),
    )


def validate_tenant_isolation() -> None:
    store = _store()
    object_id = uuid4()
    tenant_a_request = _request(tenant_ref=TENANT_A, object_id=object_id)
    tenant_b_request = _request(tenant_ref=TENANT_B, object_id=object_id)
    tenant_b_address = tenant_b_request.metadata.address
    store.put(tenant_a_request, BytesIO(PAYLOAD))

    _assert_error(DBIStorageNotFound, lambda: store.stat(tenant_b_address))
    _assert_error(
        DBIStorageNotFound,
        lambda: store.open_read(tenant_b_address).__enter__(),
    )
    _assert_error(
        DBIStorageNotFound,
        lambda: store.retire(tenant_b_address, retired_at=NOW),
    )
    _assert_error(
        DBIStorageNotFound,
        lambda: store.issue_temporary_access(
            tenant_b_request.metadata,
            mode=DBIStorageAccessMode.READ,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        ),
    )


def validate_logical_retirement() -> None:
    store = _store()
    request = _request()
    store.put(request, BytesIO(PAYLOAD))
    address = request.metadata.address
    retired_at = NOW + timedelta(seconds=1)

    assert store.retire(address, retired_at=retired_at) is True
    assert store.retire(address, retired_at=retired_at) is False
    _assert_error(DBIStorageNotFound, lambda: store.stat(address))
    _assert_error(
        DBIStorageNotFound,
        lambda: store.open_read(address).__enter__(),
    )
    _assert_error(
        DBIStorageNotFound,
        lambda: store.issue_temporary_access(
            request.metadata,
            mode=DBIStorageAccessMode.READ,
            issued_at=retired_at,
            expires_at=retired_at + timedelta(minutes=5),
        ),
    )
    _assert_error(
        DBIStorageConflict,
        lambda: store.issue_temporary_access(
            request.metadata,
            mode=DBIStorageAccessMode.WRITE,
            issued_at=retired_at,
            expires_at=retired_at + timedelta(minutes=5),
        ),
    )
    _assert_error(
        DBIStorageConflict,
        lambda: store.put(request, BytesIO(PAYLOAD)),
    )


def validate_temporary_access() -> None:
    store = _store()
    request = _request()
    store.put(request, BytesIO(PAYLOAD))

    read_grant = store.issue_temporary_access(
        request.metadata,
        mode=DBIStorageAccessMode.READ,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    existing_write_grant = store.issue_temporary_access(
        request.metadata,
        mode=DBIStorageAccessMode.WRITE,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    upload_request = _request()
    upload_grant = store.issue_temporary_access(
        upload_request.metadata,
        mode=DBIStorageAccessMode.WRITE,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )

    assert read_grant.address == request.metadata.address
    assert read_grant.metadata == request.metadata
    assert read_grant.mode is DBIStorageAccessMode.READ
    assert existing_write_grant.mode is DBIStorageAccessMode.WRITE
    assert upload_grant.metadata == upload_request.metadata
    assert upload_grant.mode is DBIStorageAccessMode.WRITE
    assert len(
        {
            read_grant.grant_ref,
            existing_write_grant.grant_ref,
            upload_grant.grant_ref,
        }
    ) == 3
    assert "grant_" not in repr(read_grant)
    _assert_error(
        DBIStorageNotFound,
        lambda: store.stat(upload_request.metadata.address),
    )

    divergent_metadata = replace(
        request.metadata,
        sha256="f" * 64,
    )
    _assert_error(
        DBIStorageConflict,
        lambda: store.issue_temporary_access(
            divergent_metadata,
            mode=DBIStorageAccessMode.READ,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        ),
    )
    _assert_error(
        DBIStorageConflict,
        lambda: store.issue_temporary_access(
            divergent_metadata,
            mode=DBIStorageAccessMode.WRITE,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        ),
    )
    _assert_error(
        DBIStorageConflict,
        lambda: store.issue_temporary_access(
            request.metadata,
            mode=DBIStorageAccessMode.READ,
            issued_at=NOW,
            expires_at=NOW + timedelta(seconds=29),
        ),
    )
    _assert_error(
        DBIStorageConflict,
        lambda: store.issue_temporary_access(
            request.metadata,
            mode="read",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        ),
    )


def validate_adapter_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "storage_memory.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                alias.name.partition(".")[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.partition(".")[0])

    assert not (
        {
            "boto3",
            "botocore",
            "google",
            "azure",
            "minio",
            "requests",
            "httpx",
            "sqlalchemy",
        }
        & imported_roots
    )
    assert "DATABASE_URL" not in source
    assert "SessionLocal" not in source
    assert "open(" not in source
    assert "unlink(" not in source


def main() -> None:
    validate_write_read_and_stat()
    validate_exact_idempotency_and_conflicts()
    validate_integrity_before_storage()
    validate_tenant_isolation()
    validate_logical_retirement()
    validate_temporary_access()
    validate_adapter_boundaries()
    print("Almacenamiento DBI: adaptador en memoria verificado.")


if __name__ == "__main__":
    main()
