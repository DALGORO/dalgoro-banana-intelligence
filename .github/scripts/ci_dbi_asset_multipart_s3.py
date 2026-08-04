"""Valida el adaptador multipartes S3 no productivo con cliente simulado."""

from __future__ import annotations

import ast
import base64
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.asset_multipart_contracts import (  # noqa: E402
    DBIMultipartPartEvidence,
)
from app.dbi.asset_multipart_policy import MIB, DBIMultipartPolicy  # noqa: E402
from app.dbi.asset_multipart_provider import (  # noqa: E402
    DBIMultipartProviderAbortRequest,
    DBIMultipartProviderCompleteRequest,
    DBIMultipartProviderConflict,
    DBIMultipartProviderDenied,
    DBIMultipartProviderInitiateRequest,
    DBIMultipartProviderIntegrityError,
    DBIMultipartProviderNotFound,
    DBIMultipartProviderPartGrantRequest,
)
from app.dbi.asset_multipart_s3 import DBIS3MultipartAdapter  # noqa: E402
from app.dbi.storage_contracts import DBIStoragePurpose  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from app.dbi.storage_s3 import DBIS3ObjectStoreConfig  # noqa: E402

SESSION_ID = UUID("11111111-1111-4111-8111-111111111111")
ASSET_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 8, 3, 22, tzinfo=timezone.utc)
BUCKET = "dbi-ci-multipart"
PART_CHECKSUM = base64.b64encode(b"p" * 32).decode("ascii")
OBJECT_CHECKSUM = f"{PART_CHECKSUM}-2"


def _client_error(code: str, status: int, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "synthetic"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


class FakeS3MultipartClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.uploads: dict[str, dict] = {}
        self.objects: dict[str, dict] = {}
        self.next_errors: dict[str, ClientError] = {}

    def _record(self, operation: str, kwargs: dict) -> None:
        self.calls.append((operation, kwargs))
        error = self.next_errors.pop(operation, None)
        if error is not None:
            raise error

    def create_multipart_upload(self, **kwargs):
        self._record("create_multipart_upload", kwargs)
        upload_id = "provider-upload-secret-001"
        self.uploads[upload_id] = dict(kwargs)
        return {"UploadId": upload_id}

    def generate_presigned_url(self, operation, **kwargs):
        self._record(
            "generate_presigned_url",
            {"operation": operation, **kwargs},
        )
        return (
            "http://127.0.0.1:8333/multipart/part?"
            f"number={kwargs['Params']['PartNumber']}"
        )

    def complete_multipart_upload(self, **kwargs):
        self._record("complete_multipart_upload", kwargs)
        upload = self.uploads.pop(kwargs["UploadId"], None)
        if upload is None:
            raise _client_error("NoSuchUpload", 404, "CompleteMultipartUpload")
        assert kwargs["IfNoneMatch"] == "*"
        assert kwargs["MpuObjectSize"] == 128 * MIB
        assert [
            item["PartNumber"]
            for item in kwargs["MultipartUpload"]["Parts"]
        ] == [1, 2]
        self.objects[kwargs["Key"]] = {
            "ContentLength": kwargs["MpuObjectSize"],
            "ContentType": upload["ContentType"],
            "Metadata": dict(upload["Metadata"]),
            "ChecksumType": kwargs["ChecksumType"],
            "ChecksumSHA256": OBJECT_CHECKSUM,
            "ETag": '"synthetic-object-etag"',
            "LastModified": NOW + timedelta(minutes=5),
        }
        return {
            "ChecksumSHA256": OBJECT_CHECKSUM,
            "ChecksumType": kwargs["ChecksumType"],
        }

    def head_object(self, **kwargs):
        self._record("head_object", kwargs)
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise _client_error("NoSuchKey", 404, "HeadObject")
        return dict(stored)

    def abort_multipart_upload(self, **kwargs):
        self._record("abort_multipart_upload", kwargs)
        if self.uploads.pop(kwargs["UploadId"], None) is None:
            raise _client_error("NoSuchUpload", 404, "AbortMultipartUpload")
        return {}

    def list_parts(self, **kwargs):
        self._record("list_parts", kwargs)
        if kwargs["UploadId"] not in self.uploads:
            raise _client_error("NoSuchUpload", 404, "ListParts")
        return {"Parts": [{"PartNumber": 1}], "IsTruncated": False}

    def list_multipart_uploads(self, **kwargs):
        self._record("list_multipart_uploads", kwargs)
        uploads = [
            {"Key": upload["Key"], "UploadId": upload_id}
            for upload_id, upload in self.uploads.items()
            if upload["Key"].startswith(kwargs["Prefix"])
        ]
        return {"Uploads": uploads, "IsTruncated": False}


def _config(**overrides) -> DBIS3ObjectStoreConfig:
    values = {
        "endpoint_url": "http://127.0.0.1:8333",
        "bucket": BUCKET,
        "region": "us-east-1",
        "access_key_id": "dbi-ci-access",
        "secret_access_key": "dbi-ci-secret",
        "verify_tls": True,
    }
    values.update(overrides)
    return DBIS3ObjectStoreConfig(**values)


def _initiation() -> DBIMultipartProviderInitiateRequest:
    size_bytes = 128 * MIB
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref="tenant-a",
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=ASSET_ID,
        ),
        content_type="image/tiff",
        size_bytes=size_bytes,
        sha256_hex="a" * 64,
    )
    return DBIMultipartProviderInitiateRequest(
        session_id=SESSION_ID,
        metadata=metadata,
        plan=DBIMultipartPolicy.build_upload_plan(size_bytes=size_bytes),
        initiated_at=NOW,
    )


def _parts(upload):
    return tuple(
        DBIMultipartPartEvidence(
            session_id=SESSION_ID,
            part_number=number,
            size_bytes=64 * MIB,
            checksum=PART_CHECKSUM,
            etag=f"etag-{number}",
        )
        for number in (1, 2)
    )


def _adapter(client=None):
    fake = client or FakeS3MultipartClient()
    return (
        DBIS3MultipartAdapter(
            _config(),
            client=fake,
            clock=lambda: NOW,
            grant_ref_factory=lambda: "grant_01J00000000000000000000000",
        ),
        fake,
    )


def _must_raise(error_type, callable_) -> None:
    try:
        callable_()
    except error_type:
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}.")


def validate_nonproductive_configuration() -> None:
    _must_raise(
        ValueError,
        lambda: DBIS3MultipartAdapter(
            _config(endpoint_url="https://objects.example"),
            client=FakeS3MultipartClient(),
        ),
    )
    adapter, _client = _adapter()
    assert "dbi-ci-access" not in repr(adapter)
    assert "dbi-ci-secret" not in repr(adapter)


def validate_initiate_and_part_access() -> None:
    adapter, client = _adapter()
    initiation = _initiation()
    upload = adapter.initiate(initiation)
    assert upload.session_id == SESSION_ID
    assert "provider-upload-secret-001" not in repr(upload)

    create = next(
        kwargs
        for operation, kwargs in client.calls
        if operation == "create_multipart_upload"
    )
    assert create["Bucket"] == BUCKET
    assert create["Key"] == initiation.metadata.address.object_key
    assert create["ChecksumAlgorithm"] == "SHA256"
    assert create["ChecksumType"] == "COMPOSITE"
    assert create["Metadata"]["dbi-sha256"] == initiation.metadata.sha256
    assert create["Tagging"] == "dbi-state=active"
    assert "ACL" not in create

    grant = adapter.issue_part_access(
        DBIMultipartProviderPartGrantRequest(
            upload=upload,
            part_number=1,
            size_bytes=64 * MIB,
            checksum=PART_CHECKSUM,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
        )
    )
    access = adapter.resolve_part_access(
        grant.grant_ref,
        now=NOW + timedelta(seconds=1),
    )
    assert access.method == "PUT"
    assert "multipart/part" in access.url
    assert "multipart/part" not in repr(access)
    assert PART_CHECKSUM not in repr(access)
    assert dict(access.headers) == {
        "content-length": str(64 * MIB),
        "x-amz-checksum-sha256": PART_CHECKSUM,
    }

    presign = next(
        kwargs
        for operation, kwargs in client.calls
        if operation == "generate_presigned_url"
    )
    assert presign["operation"] == "upload_part"
    assert presign["ExpiresIn"] == 900
    assert presign["Params"]["UploadId"] == "provider-upload-secret-001"
    assert presign["Params"]["ChecksumSHA256"] == PART_CHECKSUM

    _must_raise(
        DBIMultipartProviderNotFound,
        lambda: adapter.resolve_part_access(
            grant.grant_ref,
            now=NOW + timedelta(minutes=15),
        ),
    )


def validate_complete_and_idempotent_inspection() -> None:
    adapter, client = _adapter()
    upload = adapter.initiate(_initiation())
    request = DBIMultipartProviderCompleteRequest(
        upload=upload,
        parts=_parts(upload),
    )
    completed = adapter.complete(request)
    assert completed.created is True
    assert completed.metadata == upload.metadata
    assert completed.transport_checksum == OBJECT_CHECKSUM
    assert completed.completed_at == NOW + timedelta(minutes=5)
    assert OBJECT_CHECKSUM not in repr(completed)
    assert "synthetic-object-etag" not in repr(completed)

    complete_call = next(
        kwargs
        for operation, kwargs in client.calls
        if operation == "complete_multipart_upload"
    )
    assert complete_call["ChecksumType"] == "COMPOSITE"
    assert complete_call["MultipartUpload"]["Parts"][0] == {
        "ETag": '"etag-1"',
        "PartNumber": 1,
        "ChecksumSHA256": PART_CHECKSUM,
    }
    assert "ChecksumSHA256" not in {
        key for key in complete_call if key != "MultipartUpload"
    }

    repeated = adapter.complete(request)
    assert repeated.created is False
    assert repeated.metadata == completed.metadata
    inspected = adapter.inspect_completed(upload)
    assert inspected.created is False
    assert inspected.transport_checksum == OBJECT_CHECKSUM


def validate_integrity_and_error_translation() -> None:
    adapter, client = _adapter()
    upload = adapter.initiate(_initiation())
    client.next_errors["head_object"] = _client_error(
        "AccessDenied",
        403,
        "HeadObject",
    )
    _must_raise(
        DBIMultipartProviderDenied,
        lambda: adapter.inspect_completed(upload),
    )

    client.objects[upload.metadata.address.object_key] = {
        "ContentLength": upload.metadata.size_bytes + 1,
        "ContentType": upload.metadata.content_type,
        "Metadata": {},
        "ChecksumType": "COMPOSITE",
        "ChecksumSHA256": OBJECT_CHECKSUM,
        "ETag": '"synthetic"',
        "LastModified": NOW,
    }
    _must_raise(
        DBIMultipartProviderIntegrityError,
        lambda: adapter.inspect_completed(upload),
    )


def validate_abort_bound_unbound_and_original_safety() -> None:
    adapter, client = _adapter()
    initiation = _initiation()
    upload = adapter.initiate(initiation)
    grant = adapter.issue_part_access(
        DBIMultipartProviderPartGrantRequest(
            upload=upload,
            part_number=1,
            size_bytes=64 * MIB,
            checksum=PART_CHECKSUM,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
        )
    )
    request = DBIMultipartProviderAbortRequest(
        session_id=SESSION_ID,
        metadata=initiation.metadata,
        plan=initiation.plan,
        initiated_at=NOW,
        requested_at=NOW + timedelta(hours=1),
        provider_upload_ref=upload.provider_upload_ref,
    )
    confirmation = adapter.abort(request)
    assert confirmation.cleanup_confirmed is True
    assert confirmation.provider_uploads_aborted == 1
    assert upload.provider_upload_ref not in client.uploads
    _must_raise(
        DBIMultipartProviderNotFound,
        lambda: adapter.resolve_part_access(grant.grant_ref),
    )

    repeated = adapter.abort(request)
    assert repeated.cleanup_confirmed is True
    assert repeated.provider_uploads_aborted == 0

    object_key = initiation.metadata.address.object_key
    client.uploads.update(
        {
            "orphan-upload-001": {"Key": object_key},
            "orphan-upload-002": {"Key": object_key},
            "other-upload-001": {"Key": f"{object_key}-other"},
        }
    )
    unbound = adapter.abort(
        DBIMultipartProviderAbortRequest(
            session_id=SESSION_ID,
            metadata=initiation.metadata,
            plan=initiation.plan,
            initiated_at=NOW,
            requested_at=NOW + timedelta(hours=2),
        )
    )
    assert unbound.cleanup_confirmed is True
    assert unbound.provider_uploads_aborted == 2
    assert "other-upload-001" in client.uploads

    client.objects[object_key] = {"preserved": True}
    final_retry = adapter.abort(
        DBIMultipartProviderAbortRequest(
            session_id=SESSION_ID,
            metadata=initiation.metadata,
            plan=initiation.plan,
            initiated_at=NOW,
            requested_at=NOW + timedelta(hours=3),
        )
    )
    assert final_retry.cleanup_confirmed is True
    assert client.objects[object_key] == {"preserved": True}

    completed_adapter, completed_client = _adapter()
    completed_upload = completed_adapter.initiate(initiation)
    completed_adapter.complete(
        DBIMultipartProviderCompleteRequest(
            upload=completed_upload,
            parts=_parts(completed_upload),
        )
    )
    _must_raise(
        DBIMultipartProviderConflict,
        lambda: completed_adapter.abort(
            DBIMultipartProviderAbortRequest(
                session_id=SESSION_ID,
                metadata=initiation.metadata,
                plan=initiation.plan,
                initiated_at=NOW,
                requested_at=NOW + timedelta(hours=4),
                provider_upload_ref=completed_upload.provider_upload_ref,
            )
        ),
    )
    assert object_key in completed_client.objects


def validate_source_boundaries() -> None:
    source = (
        BACKEND / "app" / "dbi" / "asset_multipart_s3.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for forbidden in (
        "delete_object",
        "public-read",
        "os.environ",
        "DATABASE_URL",
        "SessionLocal",
        "fastapi",
    ):
        assert forbidden not in source
    assert '"abort_multipart_upload"' in source
    assert '"list_multipart_uploads"' in source
    assert '"list_parts"' in source
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    assert {"sqlalchemy", "requests", "httpx"}.isdisjoint(roots)


def main() -> None:
    validate_nonproductive_configuration()
    validate_initiate_and_part_access()
    validate_complete_and_idempotent_inspection()
    validate_integrity_and_error_translation()
    validate_abort_bound_unbound_and_original_safety()
    validate_source_boundaries()
    print("Adaptador multipartes S3-compatible DBI aprobado offline.")


if __name__ == "__main__":
    main()
