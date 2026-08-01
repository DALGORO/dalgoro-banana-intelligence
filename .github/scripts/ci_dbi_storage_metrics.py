"""Valida métricas agregadas y no sensibles del almacenamiento DBI."""

from __future__ import annotations

import ast
import sys
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.storage_contracts import (  # noqa: E402
    DBIStorageAccessMode,
    DBIStorageDenied,
    DBIStorageIntegrityError,
    DBIStorageNotFound,
    DBIStoragePurpose,
    DBIStorageWriteRequest,
)
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402
from app.dbi.storage_metrics import (  # noqa: E402
    DBIMeteredObjectStore,
    DBIStorageMetricsSnapshot,
)
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402

NOW = datetime(2026, 8, 1, 22, 0, tzinfo=timezone.utc)
PAYLOAD = b"metered-private-object"


def _request() -> DBIStorageWriteRequest:
    address = DBIStoragePolicy.build_address(
        tenant_ref="tenant-a",
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=uuid4(),
    )
    return DBIStorageWriteRequest(
        metadata=DBIStoragePolicy.build_metadata(
            address=address,
            content_type="application/octet-stream",
            size_bytes=len(PAYLOAD),
            sha256_hex=sha256(PAYLOAD).hexdigest(),
        )
    )


def _assert_error(error_type, factory) -> None:
    try:
        factory()
    except error_type:
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}.")


def validate_success_metrics() -> None:
    request = _request()
    memory = DBIInMemoryObjectStore(
        clock=lambda: NOW,
        grant_ref_factory=lambda: "grant_01J00000000000000000000000",
    )
    store = DBIMeteredObjectStore(memory)

    assert store.put(request, BytesIO(PAYLOAD)).created is True
    assert store.put(request, BytesIO(PAYLOAD)).created is False
    assert store.stat(request.metadata.address).metadata == request.metadata
    with store.open_read(request.metadata.address) as stream:
        assert stream.read() == PAYLOAD
    grant = store.issue_temporary_access(
        request.metadata.address,
        mode=DBIStorageAccessMode.READ,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    assert grant.address == request.metadata.address
    assert store.retire(
        request.metadata.address,
        retired_at=NOW + timedelta(seconds=1),
    ) is True
    assert store.retire(
        request.metadata.address,
        retired_at=NOW + timedelta(seconds=1),
    ) is False

    snapshot = store.metrics_snapshot()
    assert snapshot == DBIStorageMetricsSnapshot(
        put_attempts=2,
        created_objects=1,
        idempotent_writes=1,
        stat_attempts=1,
        read_attempts=1,
        retire_attempts=2,
        retired_objects=1,
        idempotent_retires=1,
        temporary_access_attempts=1,
        temporary_grants=1,
        bytes_verified=len(PAYLOAD) * 2,
        bytes_created=len(PAYLOAD),
        bytes_opened=len(PAYLOAD),
        denied_errors=0,
        conflict_errors=0,
        not_found_errors=0,
        integrity_errors=0,
    )


def validate_error_metrics() -> None:
    request = _request()
    memory = DBIInMemoryObjectStore(clock=lambda: NOW)
    store = DBIMeteredObjectStore(memory)

    _assert_error(
        DBIStorageIntegrityError,
        lambda: store.put(request, BytesIO(PAYLOAD[:-1])),
    )
    _assert_error(
        DBIStorageNotFound,
        lambda: store.stat(request.metadata.address),
    )
    assert store.put(request, BytesIO(PAYLOAD)).created is True
    assert store.retire(
        request.metadata.address,
        retired_at=NOW + timedelta(seconds=1),
    ) is True
    _assert_error(
        DBIStorageNotFound,
        lambda: store.open_read(request.metadata.address).__enter__(),
    )
    _assert_error(
        Exception,
        lambda: store.put(request, BytesIO(PAYLOAD)),
    )

    snapshot = store.metrics_snapshot()
    assert snapshot.put_attempts == 3
    assert snapshot.created_objects == 1
    assert snapshot.integrity_errors == 1
    assert snapshot.not_found_errors == 2
    assert snapshot.conflict_errors == 1
    assert snapshot.bytes_verified == len(PAYLOAD)


def validate_denied_metric() -> None:
    class DeniedStore:
        def stat(self, address):
            raise DBIStorageDenied()

    store = DBIMeteredObjectStore(DeniedStore())
    _assert_error(DBIStorageDenied, lambda: store.stat(object()))
    snapshot = store.metrics_snapshot()
    assert snapshot.stat_attempts == 1
    assert snapshot.denied_errors == 1


def validate_metrics_surface() -> None:
    forbidden_names = {
        "key",
        "tenant",
        "organization",
        "object",
        "url",
        "uri",
        "path",
        "credential",
        "secret",
        "token",
        "grant_ref",
        "content",
        "mime",
        "sha256",
    }
    metric_fields = {field.name.casefold() for field in fields(DBIStorageMetricsSnapshot)}
    assert not (forbidden_names & metric_fields)

    source_path = BACKEND / "app" / "dbi" / "storage_metrics.py"
    source = source_path.read_text(encoding="utf-8")
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
            "logging",
            "sqlalchemy",
        }
        & imported_roots
    )
    assert "DATABASE_URL" not in source
    assert "grant_ref" not in source
    assert "object_key" not in source


def main() -> None:
    validate_success_metrics()
    validate_error_metrics()
    validate_denied_metric()
    validate_metrics_surface()
    print("Almacenamiento DBI: métricas agregadas aprobadas.")


if __name__ == "__main__":
    main()
