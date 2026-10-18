"""H14/2H-2D/3B: real loopback MinIO multipart API, NO parts and NO grants.

Explicit CI-only gate. Creates an isolated temporary bucket in a disposable
GitHub Actions MinIO service and deletes only its own incomplete uploads.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import time
from uuid import uuid4
from urllib.parse import urlparse

from botocore.exceptions import BotoCoreError, ClientError

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "ci-only-h14-minio")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from app.dbi.asset_multipart_contracts import (  # noqa: E402
    DBIMultipartChecksumAlgorithm, DBIMultipartChecksumType,
)
from app.dbi.asset_multipart_policy import DBI_MULTIPART_DEFAULT_LIMITS, DBIMultipartPolicy  # noqa: E402
from app.dbi.asset_multipart_provider import (  # noqa: E402
    DBIMultipartProviderAbortRequest, DBIMultipartProviderError,
    DBIMultipartProviderInitiateRequest, DBIMultipartProviderPolicy,
)
from app.dbi.asset_multipart_s3 import DBIS3MultipartAdapter  # noqa: E402
from app.dbi.storage_contracts import DBIStoragePurpose  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from app.dbi.storage_s3 import DBIS3ObjectStoreConfig, build_s3_client  # noqa: E402

MIB = 1024 * 1024


def make_client():
    if os.environ.get("DBI_MINIO_E2E_ENABLED") != "1":
        raise RuntimeError("Real S3 integration test requires opt-in DBI_MINIO_E2E_ENABLED=1")
    endpoint = os.environ.get("DBI_MINIO_E2E_ENDPOINT", "")
    if urlparse(endpoint).scheme != "http" or urlparse(endpoint).hostname not in {
        "127.0.0.1", "::1", "localhost",
    }:
        raise RuntimeError("E2E endpoint must be plaintext loopback only.")
    config = DBIS3ObjectStoreConfig(
        endpoint_url=endpoint,
        bucket="dbi-h14-test-" + uuid4().hex,
        region="us-east-1",
        access_key_id=os.environ["DBI_MINIO_E2E_ACCESS_KEY"],
        secret_access_key=os.environ["DBI_MINIO_E2E_SECRET_KEY"],
        connect_timeout_seconds=2,
        read_timeout_seconds=6,
        max_attempts=1,
    )
    return config, build_s3_client(config)


def wait_for_minio(client):
    # Bounded startup retry; fail CI rather than skipping integration tests.
    for _ in range(30):
        try:
            client.list_buckets()
            return
        except (ClientError, BotoCoreError, OSError):
            time.sleep(1)
    raise RuntimeError("MinIO local E2E did not become ready.")


def contract_for(bucket):
    address = DBIStoragePolicy.build_address(
        tenant_ref="dbi-h14-ci-tenant",
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=uuid4(),
    )
    metadata = DBIStoragePolicy.build_metadata(
        address=address,
        content_type="image/tiff",
        size_bytes=128 * MIB,
        sha256_hex="a" * 64,  # DECLARED ONLY, never verified against a TIFF
    )
    plan = DBIMultipartPolicy.build_upload_plan(
        size_bytes=metadata.size_bytes,
        limits=DBI_MULTIPART_DEFAULT_LIMITS,
        checksum_algorithm=DBIMultipartChecksumAlgorithm.SHA256,
        checksum_type=DBIMultipartChecksumType.COMPOSITE,
    )
    assert plan.part_count == 2 and plan.part_size_bytes == 64 * MIB
    return DBIMultipartProviderInitiateRequest(
        session_id=uuid4(), metadata=metadata, plan=plan,
        initiated_at=datetime.now(timezone.utc),
    )


def abort_request(contract, ref):
    return DBIMultipartProviderAbortRequest(
        session_id=contract.session_id,
        metadata=contract.metadata,
        plan=contract.plan,
        initiated_at=contract.initiated_at,
        requested_at=datetime.now(timezone.utc),
        provider_upload_ref=ref,
    )


def test_minio():
    config, client = make_client()
    wait_for_minio(client)
    client.create_bucket(Bucket=config.bucket)
    adapter = DBIS3MultipartAdapter(config, client=client)
    contract = contract_for(config.bucket)
    DBIMultipartProviderPolicy.validate_initiate_request(contract)
    key = contract.metadata.address.object_key
    neighbor_key = key + ".neighbor-not-a-dbi-object"
    refs = []
    neighbor = None

    try:
        assert adapter.inspect_incomplete_uploads(
            contract, expected_upload_ref=None,
        ).incomplete_count == 0
        # These are real MinIO HTTP requests; no TIFF bytes or part permits.
        first = adapter.initiate(contract)
        refs.append(first.provider_upload_ref)
        report = adapter.inspect_incomplete_uploads(
            contract, expected_upload_ref=first.provider_upload_ref,
        )
        assert (report.incomplete_count, report.expected_present, report.unexpected_count) == (
            1, True, 0,
        )

        second = adapter.initiate(contract)
        refs.append(second.provider_upload_ref)
        assert first.provider_upload_ref != second.provider_upload_ref
        report = adapter.inspect_incomplete_uploads(
            contract, expected_upload_ref=first.provider_upload_ref,
        )
        assert (report.incomplete_count, report.expected_present, report.unexpected_count) == (
            2, True, 1,
        )
        # Provider Prefix may return neighbors; adapter must match exact key.
        neighbor = client.create_multipart_upload(
            Bucket=config.bucket, Key=neighbor_key,
        )["UploadId"]
        report = adapter.inspect_incomplete_uploads(
            contract, expected_upload_ref=first.provider_upload_ref,
        )
        assert report.incomplete_count == 2 and report.unexpected_count == 1

        known = adapter.abort(abort_request(contract, first.provider_upload_ref))
        assert known.cleanup_confirmed and known.provider_uploads_aborted == 1
        refs.remove(first.provider_upload_ref)
        report = adapter.inspect_incomplete_uploads(
            contract, expected_upload_ref=first.provider_upload_ref,
        )
        assert (report.incomplete_count, report.expected_present, report.unexpected_count) == (
            1, False, 1,
        )

        all_exact = adapter.abort(abort_request(contract, None))
        assert all_exact.cleanup_confirmed and all_exact.provider_uploads_aborted == 1
        refs.clear()
        assert adapter.inspect_incomplete_uploads(
            contract, expected_upload_ref=None,
        ).incomplete_count == 0
        # The prefix-neighbor must survive exact-key cleanup.
        remaining = client.list_multipart_uploads(
            Bucket=config.bucket, Prefix=neighbor_key,
        ).get("Uploads", [])
        assert any(item.get("Key") == neighbor_key and item.get("UploadId") == neighbor
                   for item in remaining)
        assert not client.list_objects_v2(
            Bucket=config.bucket, Prefix=key,
        ).get("Contents", [])
        assert not adapter._grants
        print("H14/2H-2D/3B OK: real local MinIO start/list/duplicate/abort,"
              " neighboring key preserved, zero TIFF parts/grants.")
    finally:
        # Test-only cleanup on disposable bucket, never operational objects.
        for ref in refs:
            client.abort_multipart_upload(
                Bucket=config.bucket, Key=key, UploadId=ref,
            )
        if neighbor is not None:
            client.abort_multipart_upload(
                Bucket=config.bucket, Key=neighbor_key, UploadId=neighbor,
            )
        client.delete_bucket(Bucket=config.bucket)


if __name__ == "__main__":
    test_minio()
