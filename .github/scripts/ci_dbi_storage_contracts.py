"""Valida contratos y política pura de almacenamiento DBI sin servicios."""

from __future__ import annotations

import ast
import sys
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.storage_contracts import (  # noqa: E402
    DBIPrivateObjectStore,
    DBIStorageAccessMode,
    DBIStorageAddress,
    DBIStorageConflict,
    DBIStorageObjectMetadata,
    DBIStorageObjectRecord,
    DBIStorageObjectState,
    DBIStoragePurpose,
    DBIStorageTemporaryGrant,
)
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
NOW = datetime(2026, 8, 1, 20, 0, tzinfo=timezone.utc)
SHA256_A = "a" * 64


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIStorageConflict:
        return
    raise AssertionError("La política de almacenamiento debía rechazar el valor.")


def validate_canonical_addresses() -> None:
    object_id = uuid4()
    address = DBIStoragePolicy.build_address(
        tenant_ref=TENANT_A,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=object_id,
    )
    assert address.tenant_ref == TENANT_A
    assert address.object_id == object_id
    assert address.object_key == (
        f"tenants/{DBIStoragePolicy.tenant_namespace(TENANT_A)}"
        f"/analysis-inputs/{object_id}"
    )
    assert TENANT_A not in address.object_key
    assert DBIStoragePolicy.validate_address(address) is address
    assert DBIStoragePolicy.tenant_namespace(TENANT_A) != (
        DBIStoragePolicy.tenant_namespace(TENANT_B)
    )

    for tenant_ref in (
        "",
        " tenant-a",
        "tenant-a ",
        "all",
        "any",
        "tenant-*",
        "tenant\ncontrol",
        "x" * 129,
    ):
        _assert_conflict(
            lambda tenant_ref=tenant_ref: DBIStoragePolicy.build_address(
                tenant_ref=tenant_ref,
                purpose=DBIStoragePurpose.ANALYSIS_INPUT,
                object_id=object_id,
            )
        )

    tenant_b_key = DBIStoragePolicy.build_address(
        tenant_ref=TENANT_B,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=object_id,
    ).object_key
    forged_keys = (
        f"/{address.object_key}",
        "https://objects.example/private",
        "tenants/../../escape",
        "tenants//escape",
        "tenants\\escape",
        f"{address.object_key}?token=secret",
        f"{address.object_key}#fragment",
        tenant_b_key,
    )
    for forged_key in forged_keys:
        _assert_conflict(
            lambda forged_key=forged_key: DBIStoragePolicy.validate_address(
                replace(address, object_key=forged_key)
            )
        )

    _assert_conflict(
        lambda: DBIStoragePolicy.validate_address(
            replace(address, tenant_ref=TENANT_B)
        )
    )
    _assert_conflict(
        lambda: DBIStoragePolicy.validate_address(
            replace(address, purpose=DBIStoragePurpose.ANALYSIS_ARTIFACT)
        )
    )
    _assert_conflict(
        lambda: DBIStoragePolicy.validate_address(
            DBIStorageAddress(
                tenant_ref=TENANT_A,
                purpose=DBIStoragePurpose.ANALYSIS_INPUT,
                object_id=uuid4(),
                object_key=address.object_key,
            )
        )
    )


def validate_metadata_policy() -> None:
    address = DBIStoragePolicy.build_address(
        tenant_ref=TENANT_A,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=uuid4(),
    )
    metadata = DBIStoragePolicy.build_metadata(
        address=address,
        content_type="image/tiff",
        size_bytes=1_024,
        sha256_hex=SHA256_A,
    )
    assert metadata == DBIStorageObjectMetadata(
        address=address,
        content_type="image/tiff",
        size_bytes=1_024,
        sha256=SHA256_A,
    )
    assert DBIStoragePolicy.validate_metadata(metadata) is metadata

    for size_bytes in (0, -1, True, 9_223_372_036_854_775_808):
        _assert_conflict(
            lambda size_bytes=size_bytes: DBIStoragePolicy.build_metadata(
                address=address,
                content_type="image/tiff",
                size_bytes=size_bytes,
                sha256_hex=SHA256_A,
            )
        )
    for digest in (
        "A" * 64,
        "a" * 63,
        "g" * 64,
        "sha256:" + SHA256_A,
    ):
        _assert_conflict(
            lambda digest=digest: DBIStoragePolicy.build_metadata(
                address=address,
                content_type="image/tiff",
                size_bytes=1,
                sha256_hex=digest,
            )
        )
    for content_type in (
        "Image/Tiff",
        "image/tiff; charset=binary",
        "application/pdf",
        "text/html",
        " image/tiff",
    ):
        _assert_conflict(
            lambda content_type=content_type: DBIStoragePolicy.build_metadata(
                address=address,
                content_type=content_type,
                size_bytes=1,
                sha256_hex=SHA256_A,
            )
        )

    artifact_address = DBIStoragePolicy.build_address(
        tenant_ref=TENANT_A,
        purpose=DBIStoragePurpose.ANALYSIS_ARTIFACT,
        object_id=uuid4(),
    )
    artifact_metadata = DBIStoragePolicy.build_metadata(
        address=artifact_address,
        content_type="application/pdf",
        size_bytes=2_048,
        sha256_hex="b" * 64,
    )
    assert artifact_metadata.content_type == "application/pdf"


def validate_temporal_policy() -> None:
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref=TENANT_A,
            purpose=DBIStoragePurpose.TECHNICAL_SOURCE,
            object_id=uuid4(),
        ),
        content_type="application/pdf",
        size_bytes=2_048,
        sha256_hex="d" * 64,
    )
    issued_at = NOW
    expires_at = NOW + timedelta(minutes=15)
    assert DBIStoragePolicy.validate_access_window(
        issued_at=issued_at,
        expires_at=expires_at,
    ) == (issued_at, expires_at)

    grant = DBIStorageTemporaryGrant(
        grant_ref="grant_01J00000000000000000000000",
        metadata=metadata,
        mode=DBIStorageAccessMode.READ,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    assert grant.address == metadata.address
    assert grant.metadata == metadata
    assert "grant_" not in repr(grant)
    assert DBIStoragePolicy.validate_grant(grant) is grant

    for ttl in (
        timedelta(seconds=29),
        timedelta(hours=1, seconds=1),
        timedelta(seconds=-1),
    ):
        _assert_conflict(
            lambda ttl=ttl: DBIStoragePolicy.validate_access_window(
                issued_at=issued_at,
                expires_at=issued_at + ttl,
            )
        )
    _assert_conflict(
        lambda: DBIStoragePolicy.validate_access_window(
            issued_at=issued_at.replace(tzinfo=None),
            expires_at=expires_at,
        )
    )
    _assert_conflict(
        lambda: DBIStoragePolicy.validate_grant(
            replace(grant, grant_ref="https://objects.example/signed")
        )
    )
    forged_metadata = replace(
        metadata,
        sha256="D" * 64,
    )
    _assert_conflict(
        lambda: DBIStoragePolicy.validate_grant(
            replace(grant, metadata=forged_metadata)
        )
    )


def validate_record_policy() -> None:
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref=TENANT_A,
            purpose=DBIStoragePurpose.MODEL_ARTIFACT,
            object_id=uuid4(),
        ),
        content_type="application/octet-stream",
        size_bytes=4_096,
        sha256_hex="c" * 64,
    )
    active = DBIStorageObjectRecord(
        metadata=metadata,
        state=DBIStorageObjectState.ACTIVE,
        created_at=NOW,
    )
    assert DBIStoragePolicy.validate_record(active) is active

    retired = replace(
        active,
        state=DBIStorageObjectState.RETIRED,
        retired_at=NOW + timedelta(seconds=1),
    )
    assert DBIStoragePolicy.validate_record(retired) is retired
    _assert_conflict(
        lambda: DBIStoragePolicy.validate_record(
            replace(active, retired_at=NOW)
        )
    )
    _assert_conflict(
        lambda: DBIStoragePolicy.validate_record(
            replace(retired, retired_at=NOW - timedelta(seconds=1))
        )
    )


def validate_contract_surface() -> None:
    protocol_methods = {
        name
        for name in DBIPrivateObjectStore.__dict__
        if not name.startswith("_")
    }
    assert protocol_methods == {
        "put",
        "stat",
        "open_read",
        "copy_to",
        "retire",
        "issue_temporary_access",
    }

    forbidden_field_names = {
        "url",
        "uri",
        "path",
        "credential",
        "secret",
        "token",
        "bucket",
        "endpoint",
        "public",
    }
    for contract in (
        DBIStorageAddress,
        DBIStorageObjectMetadata,
        DBIStorageObjectRecord,
        DBIStorageTemporaryGrant,
    ):
        assert not (
            forbidden_field_names
            & {field.name.casefold() for field in fields(contract)}
        )

    source_paths = (
        BACKEND / "app" / "dbi" / "storage_contracts.py",
        BACKEND / "app" / "dbi" / "storage_policy.py",
    )
    forbidden_import_roots = {
        "boto3",
        "botocore",
        "google",
        "azure",
        "minio",
        "requests",
        "httpx",
    }
    for path in source_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
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
    validate_canonical_addresses()
    validate_metadata_policy()
    validate_temporal_policy()
    validate_record_policy()
    validate_contract_surface()
    print("Almacenamiento DBI: contratos y política pura aprobados.")


if __name__ == "__main__":
    main()
