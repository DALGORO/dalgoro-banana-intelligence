"""Valida el puerto proveedor-neutral multipartes DBI sin red."""

from __future__ import annotations

import ast
import base64
import sys
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.asset_multipart_contracts import (  # noqa: E402
    DBIMultipartChecksumAlgorithm,
    DBIMultipartChecksumType,
    DBIMultipartPartEvidence,
)
from app.dbi.asset_multipart_policy import MIB, DBIMultipartPolicy  # noqa: E402
from app.dbi.asset_multipart_provider import (  # noqa: E402
    DBIMultipartObjectStore,
    DBIMultipartProviderCompleteRequest,
    DBIMultipartProviderConflict,
    DBIMultipartProviderInitiateRequest,
    DBIMultipartProviderPartGrant,
    DBIMultipartProviderPartGrantRequest,
    DBIMultipartProviderPolicy,
    DBIMultipartProviderUpload,
)
from app.dbi.storage_contracts import DBIStoragePurpose  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402

SESSION_ID = UUID("11111111-1111-4111-8111-111111111111")
ASSET_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 8, 3, 21, tzinfo=timezone.utc)
PART_CHECKSUM = base64.b64encode(b"p" * 32).decode("ascii")


def _request(
    *,
    algorithm=DBIMultipartChecksumAlgorithm.SHA256,
    checksum_type=DBIMultipartChecksumType.COMPOSITE,
) -> DBIMultipartProviderInitiateRequest:
    size_bytes = 128 * MIB
    address = DBIStoragePolicy.build_address(
        tenant_ref="tenant-a",
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=ASSET_ID,
    )
    metadata = DBIStoragePolicy.build_metadata(
        address=address,
        content_type="image/tiff",
        size_bytes=size_bytes,
        sha256_hex="a" * 64,
    )
    return DBIMultipartProviderInitiateRequest(
        session_id=SESSION_ID,
        metadata=metadata,
        plan=DBIMultipartPolicy.build_upload_plan(
            size_bytes=size_bytes,
            checksum_algorithm=algorithm,
            checksum_type=checksum_type,
        ),
        initiated_at=NOW,
    )


def _upload(
    request: DBIMultipartProviderInitiateRequest | None = None,
) -> DBIMultipartProviderUpload:
    initiation = request or _request()
    return DBIMultipartProviderUpload(
        provider_upload_ref="provider-upload-secret-001",
        session_id=initiation.session_id,
        metadata=initiation.metadata,
        plan=initiation.plan,
        initiated_at=initiation.initiated_at,
    )


def _parts(upload: DBIMultipartProviderUpload):
    return tuple(
        DBIMultipartPartEvidence(
            session_id=upload.session_id,
            part_number=number,
            size_bytes=DBIMultipartPolicy.expected_part_size(
                upload.plan,
                part_number=number,
            ),
            checksum=PART_CHECKSUM,
            etag=f"etag-{number}",
        )
        for number in range(1, upload.plan.part_count + 1)
    )


def _must_conflict(callable_) -> None:
    try:
        callable_()
    except DBIMultipartProviderConflict:
        return
    raise AssertionError("El contrato proveedor debía fallar cerrado.")


def validate_initiation_and_safe_reference() -> None:
    request = _request()
    assert DBIMultipartProviderPolicy.validate_initiate_request(request) is request
    upload = _upload(request)
    assert DBIMultipartProviderPolicy.validate_upload(upload) is upload
    assert "provider-upload-secret-001" not in repr(upload)

    _must_conflict(
        lambda: DBIMultipartProviderPolicy.validate_initiate_request(
            replace(request, session_id="invalid")
        )
    )
    _must_conflict(
        lambda: DBIMultipartProviderPolicy.validate_initiate_request(
            replace(
                request,
                plan=DBIMultipartPolicy.build_upload_plan(size_bytes=32 * MIB),
            )
        )
    )


def validate_part_grant() -> None:
    upload = _upload()
    request = DBIMultipartProviderPartGrantRequest(
        upload=upload,
        part_number=1,
        size_bytes=64 * MIB,
        checksum=PART_CHECKSUM,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    assert DBIMultipartProviderPolicy.validate_part_grant_request(request) is request
    assert "provider-upload-secret-001" not in repr(request)
    assert PART_CHECKSUM not in repr(request)

    _must_conflict(
        lambda: DBIMultipartProviderPolicy.validate_part_grant_request(
            replace(request, size_bytes=request.size_bytes - 1)
        )
    )
    _must_conflict(
        lambda: DBIMultipartProviderPolicy.validate_part_grant_request(
            replace(request, part_number=3)
        )
    )


def validate_completion_contracts() -> None:
    upload = _upload()
    composite = DBIMultipartProviderCompleteRequest(
        upload=upload,
        parts=_parts(upload),
    )
    assert DBIMultipartProviderPolicy.validate_complete_request(composite) is composite
    assert PART_CHECKSUM not in repr(composite)
    _must_conflict(
        lambda: DBIMultipartProviderPolicy.validate_complete_request(
            replace(composite, parts=composite.parts[:-1])
        )
    )
    _must_conflict(
        lambda: DBIMultipartProviderPolicy.validate_complete_request(
            replace(composite, full_object_checksum=PART_CHECKSUM)
        )
    )

    full_request = _request(
        algorithm=DBIMultipartChecksumAlgorithm.CRC64NVME,
        checksum_type=DBIMultipartChecksumType.FULL_OBJECT,
    )
    full_upload = _upload(full_request)
    crc_checksum = base64.b64encode(b"c" * 8).decode("ascii")
    crc_parts = tuple(
        replace(part, checksum=crc_checksum)
        for part in _parts(full_upload)
    )
    full = DBIMultipartProviderCompleteRequest(
        upload=full_upload,
        parts=crc_parts,
        full_object_checksum=crc_checksum,
    )
    assert DBIMultipartProviderPolicy.validate_complete_request(full) is full
    _must_conflict(
        lambda: DBIMultipartProviderPolicy.validate_complete_request(
            replace(full, full_object_checksum=None)
        )
    )


def validate_contract_surface() -> None:
    methods = {
        name
        for name in DBIMultipartObjectStore.__dict__
        if not name.startswith("_")
    }
    assert methods == {
        "initiate",
        "issue_part_access",
        "complete",
        "inspect_completed",
    }
    forbidden_fields = {
        "url",
        "bucket",
        "endpoint",
        "credential",
        "secret",
        "token",
    }
    for contract in (
        DBIMultipartProviderInitiateRequest,
        DBIMultipartProviderUpload,
        DBIMultipartProviderPartGrantRequest,
        DBIMultipartProviderPartGrant,
        DBIMultipartProviderCompleteRequest,
    ):
        assert not (
            forbidden_fields
            & {item.name.casefold() for item in fields(contract)}
        )

    source = (
        BACKEND / "app" / "dbi" / "asset_multipart_provider.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    assert {
        "boto3",
        "botocore",
        "sqlalchemy",
        "fastapi",
        "requests",
        "httpx",
    }.isdisjoint(roots)


def main() -> None:
    validate_initiation_and_safe_reference()
    validate_part_grant()
    validate_completion_contracts()
    validate_contract_surface()
    print("Puerto proveedor-neutral multipartes DBI aprobado offline.")


if __name__ == "__main__":
    main()
