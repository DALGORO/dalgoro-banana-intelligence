"""Valida el adaptador S3 DBI con un cliente simulado y sin red."""

from __future__ import annotations

import ast
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from urllib.parse import parse_qsl
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
)

NOW = datetime(2026, 8, 1, 23, 0, tzinfo=timezone.utc)
PAYLOAD = b"synthetic-s3-private-object"
BUCKET = "dbi-ci-synthetic"


def _client_error(code: str, status: int, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "synthetic"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self.next_errors: dict[str, ClientError] = {}

    def _record(self, operation: str, kwargs: dict) -> None:
        self.calls.append((operation, kwargs))
        error = self.next_errors.pop(operation, None)
        if error is not None:
            raise error

    def put_object(self, **kwargs):
        self._record("put_object", kwargs)
        key = kwargs["Key"]
        if kwargs.get("IfNoneMatch") == "*" and key in self.objects:
            raise _client_error("PreconditionFailed", 412, "PutObject")
        payload = kwargs["Body"]
        assert isinstance(payload, bytes)
        assert len(payload) == kwargs["ContentLength"]
        tags = dict(parse_qsl(kwargs["Tagging"]))
        self.objects[key] = {
            "Body": payload,
            "ContentLength": kwargs["ContentLength"],
            "ContentType": kwargs["ContentType"],
            "Metadata": dict(kwargs["Metadata"]),
            "LastModified": NOW,
            "Tags": tags,
        }
        return {"ETag": '"synthetic"'}

    def head_object(self, **kwargs):
        self._record("head_object", kwargs)
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise _client_error("NoSuchKey", 404, "HeadObject")
        return {
            "ContentLength": stored["ContentLength"],
            "ContentType": stored["ContentType"],
            "Metadata": dict(stored["Metadata"]),
            "LastModified": stored["LastModified"],
        }

    def get_object_tagging(self, **kwargs):
        self._record("get_object_tagging", kwargs)
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise _client_error("NoSuchKey", 404, "GetObjectTagging")
        return {
            "TagSet": [
                {"Key": key, "Value": value}
                for key, value in stored["Tags"].items()
            ]
        }

    def get_object(self, **kwargs):
        self._record("get_object", kwargs)
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise _client_error("NoSuchKey", 404, "GetObject")
        return {"Body": BytesIO(stored["Body"])}

    def put_object_tagging(self, **kwargs):
        self._record("put_object_tagging", kwargs)
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise _client_error("NoSuchKey", 404, "PutObjectTagging")
        stored["Tags"] = {
            item["Key"]: item["Value"]
            for item in kwargs["Tagging"]["TagSet"]
        }
        return {}

    def generate_presigned_url(self, operation, **kwargs):
        arguments = {"operation": operation, **kwargs}
        self._record("generate_presigned_url", arguments)
        return (
            "http://127.0.0.1:8333/temporary/synthetic?"
            f"operation={operation}&expires={kwargs['ExpiresIn']}"
        )


def _config(**overrides) -> DBIS3ObjectStoreConfig:
    values = {
        "endpoint_url": "http://127.0.0.1:8333",
        "bucket": BUCKET,
        "region": "us-east-1",
        "access_key_id": "dbi-ci-access",
        "secret_access_key": "dbi-ci-secret",
        "verify_tls": True,
        "max_object_size_bytes": 1024,
    }
    values.update(overrides)
    return DBIS3ObjectStoreConfig(**values)


def _request(*, object_id=None, payload: bytes = PAYLOAD, content_type=None):
    address = DBIStoragePolicy.build_address(
        tenant_ref="tenant-a",
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=object_id or uuid4(),
    )
    return DBIStorageWriteRequest(
        metadata=DBIStoragePolicy.build_metadata(
            address=address,
            content_type=content_type or "application/octet-stream",
            size_bytes=len(payload),
            sha256_hex=sha256(payload).hexdigest(),
        )
    )


def _store(client: FakeS3Client | None = None) -> tuple[DBIS3ObjectStore, FakeS3Client]:
    fake = client or FakeS3Client()
    grants = iter(
        (
            "grant_01J00000000000000000000000",
            "grant_01J00000000000000000000001",
            "grant_01J00000000000000000000002",
        )
    )
    return (
        DBIS3ObjectStore(
            _config(),
            client=fake,
            clock=lambda: NOW,
            grant_ref_factory=lambda: next(grants),
        ),
        fake,
    )


def _assert_error(error_type, factory) -> None:
    try:
        factory()
    except error_type:
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}.")


def validate_configuration() -> None:
    config = _config()
    rendered = repr(config)
    assert "dbi-ci-access" not in rendered
    assert "dbi-ci-secret" not in rendered

    invalid_overrides = (
        {"endpoint_url": "http://objects.example"},
        {"endpoint_url": "https://objects.example", "verify_tls": False},
        {"endpoint_url": "http://user:password@127.0.0.1:8333"},
        {"endpoint_url": "http://127.0.0.1:8333/path"},
        {"endpoint_url": "http://127.0.0.1:8333?token=secret"},
        {"bucket": "Invalid_Bucket"},
        {"bucket": "dbi..bucket"},
        {"region": " us-east-1"},
        {"access_key_id": ""},
        {"secret_access_key": "secret\nvalue"},
        {"max_object_size_bytes": 0},
    )
    for overrides in invalid_overrides:
        _assert_error(ValueError, lambda overrides=overrides: _config(**overrides))


def validate_write_read_and_idempotency() -> None:
    store, client = _store()
    request = _request()
    address = request.metadata.address

    created = store.put(request, BytesIO(PAYLOAD))
    assert created.created is True
    assert created.record.metadata == request.metadata
    assert store.stat(address) == created.record
    with store.open_read(address) as stream:
        assert stream.read() == PAYLOAD
    assert stream.closed is True

    put_call = next(kwargs for operation, kwargs in client.calls if operation == "put_object")
    assert put_call["IfNoneMatch"] == "*"
    assert put_call["ContentType"] == request.metadata.content_type
    assert put_call["ContentLength"] == len(PAYLOAD)
    assert put_call["Metadata"]["dbi-sha256"] == request.metadata.sha256
    assert put_call["Tagging"] == "dbi-state=active"
    assert "ACL" not in put_call

    repeated = store.put(request, BytesIO(PAYLOAD))
    assert repeated.created is False
    assert repeated.record == created.record

    divergent_metadata = replace(request.metadata, content_type="image/tiff")
    _assert_error(
        DBIStorageConflict,
        lambda: store.put(
            DBIStorageWriteRequest(metadata=divergent_metadata),
            BytesIO(PAYLOAD),
        ),
    )
    divergent_payload = b"different-synthetic-object"
    divergent = _request(
        object_id=address.object_id,
        payload=divergent_payload,
    )
    _assert_error(
        DBIStorageConflict,
        lambda: store.put(divergent, BytesIO(divergent_payload)),
    )


def validate_integrity_and_provider_metadata() -> None:
    store, client = _store()
    request = _request()

    for content in (
        BytesIO(PAYLOAD[:-1]),
        BytesIO(PAYLOAD + b"x"),
        BytesIO(b"x" * len(PAYLOAD)),
        StringIO(PAYLOAD.decode("ascii")),
    ):
        _assert_error(
            DBIStorageIntegrityError,
            lambda content=content: store.put(request, content),
        )
    assert not client.objects

    store.put(request, BytesIO(PAYLOAD))
    key = request.metadata.address.object_key
    client.objects[key]["Metadata"].pop("dbi-sha256")
    _assert_error(
        DBIStorageIntegrityError,
        lambda: store.stat(request.metadata.address),
    )

    client.objects[key]["Metadata"]["dbi-sha256"] = request.metadata.sha256
    client.objects[key]["Body"] = b"x" * len(PAYLOAD)
    _assert_error(
        DBIStorageIntegrityError,
        lambda: store.open_read(request.metadata.address).__enter__(),
    )


def validate_logical_retirement() -> None:
    store, _client = _store()
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
        DBIStorageConflict,
        lambda: store.put(request, BytesIO(PAYLOAD)),
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


def validate_temporary_access() -> None:
    store, client = _store()
    request = _request()

    write_grant = store.issue_temporary_access(
        request.metadata,
        mode=DBIStorageAccessMode.WRITE,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    write_access = store.resolve_temporary_access(
        write_grant.grant_ref,
        now=NOW + timedelta(seconds=1),
    )
    assert write_access.method == "PUT"
    assert "temporary/synthetic" in write_access.url
    assert "temporary/synthetic" not in repr(write_access)
    write_headers = dict(write_access.headers)
    assert write_headers["content-length"] == str(len(PAYLOAD))
    assert write_headers["content-type"] == "application/octet-stream"
    assert write_headers["if-none-match"] == "*"
    assert write_headers["x-amz-meta-dbi-sha256"] == request.metadata.sha256
    assert write_headers["x-amz-tagging"] == "dbi-state=active"

    presign_call = next(
        kwargs
        for operation, kwargs in client.calls
        if operation == "generate_presigned_url"
    )
    assert presign_call["operation"] == "put_object"
    assert presign_call["HttpMethod"] == "PUT"
    assert presign_call["ExpiresIn"] == 300
    assert presign_call["Params"]["IfNoneMatch"] == "*"

    store.put(request, BytesIO(PAYLOAD))
    _assert_error(
        DBIStorageConflict,
        lambda: store.issue_temporary_access(
            request.metadata,
            mode=DBIStorageAccessMode.WRITE,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        ),
    )

    read_grant = store.issue_temporary_access(
        request.metadata,
        mode=DBIStorageAccessMode.READ,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    read_access = store.resolve_temporary_access(read_grant.grant_ref, now=NOW)
    assert read_access.method == "GET"
    assert read_access.headers == ()

    _assert_error(
        DBIStorageConflict,
        lambda: store.issue_temporary_access(
            replace(request.metadata, content_type="image/tiff"),
            mode=DBIStorageAccessMode.READ,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        ),
    )
    _assert_error(
        DBIStorageNotFound,
        lambda: store.resolve_temporary_access(
            write_grant.grant_ref,
            now=NOW + timedelta(minutes=5),
        ),
    )
    _assert_error(
        DBIStorageNotFound,
        lambda: store.resolve_temporary_access("invalid", now=NOW),
    )


def validate_error_translation() -> None:
    store, client = _store()
    address = _request().metadata.address

    client.next_errors["head_object"] = _client_error(
        "AccessDenied",
        403,
        "HeadObject",
    )
    _assert_error(DBIStorageDenied, lambda: store.stat(address))

    client.next_errors["head_object"] = _client_error(
        "InternalError",
        500,
        "HeadObject",
    )
    _assert_error(DBIStorageError, lambda: store.stat(address))


def validate_source_boundaries() -> None:
    source_path = BACKEND / "app" / "dbi" / "storage_s3.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "delete_object" not in source
    assert "public-read" not in source
    assert "os.environ" not in source
    assert "boto3.client" not in source
    assert "DATABASE_URL" not in source
    assert "SessionLocal" not in source

    forbidden_import_roots = {
        "sqlalchemy",
        "fastapi",
        "requests",
        "google",
        "azure",
        "minio",
    }
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                alias.name.partition(".")[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.partition(".")[0])
    assert not (forbidden_import_roots & imported_roots)


def main() -> None:
    validate_configuration()
    validate_write_read_and_idempotency()
    validate_integrity_and_provider_metadata()
    validate_logical_retirement()
    validate_temporary_access()
    validate_error_translation()
    validate_source_boundaries()
    print("Almacenamiento DBI: adaptador S3 aprobado offline.")


if __name__ == "__main__":
    main()
