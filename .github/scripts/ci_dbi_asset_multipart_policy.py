"""Pruebas offline de contratos y política multipartes DBI-ASSET-003."""

from __future__ import annotations

import ast
import base64
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm,
    DBIMultipartChecksumType,
    DBIMultipartLimits,
    DBIMultipartPartEvidence,
    DBIMultipartPolicyReason,
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
)
from app.dbi.asset_multipart_policy import (
    DBI_MULTIPART_DEFAULT_LIMITS,
    GIB,
    MIB,
    DBIMultipartConflict,
    DBIMultipartPolicy,
    DBIMultipartPolicyError,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "apps" / "platform-web" / "backend"
SESSION_ID = UUID("11111111-1111-4111-8111-111111111111")
ASSET_ID = UUID("22222222-2222-4222-8222-222222222222")
SHA256_HEX = "a" * 64
PART_CHECKSUM = base64.b64encode(b"p" * 32).decode("ascii")


def _must_fail(callable_, error_type=DBIMultipartPolicyError) -> None:
    try:
        callable_()
    except error_type:
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}.")


def _evidence(plan, number: int) -> DBIMultipartPartEvidence:
    return DBIMultipartPartEvidence(
        session_id=SESSION_ID,
        part_number=number,
        size_bytes=DBIMultipartPolicy.expected_part_size(
            plan,
            part_number=number,
        ),
        checksum=PART_CHECKSUM,
        etag=f"etag-{number}",
    )


def validate_default_boundaries() -> None:
    limits = DBIMultipartPolicy.validate_limits(DBI_MULTIPART_DEFAULT_LIMITS)
    assert limits.synchronous_max_bytes == 64 * MIB
    assert limits.multipart_max_bytes == 20 * GIB
    assert limits.part_size_bytes == 64 * MIB
    assert limits.max_parts == 10_000
    assert limits.max_grants_per_window == 8
    assert limits.max_client_concurrency == 4

    synchronous = DBIMultipartPolicy.build_upload_plan(size_bytes=64 * MIB)
    assert synchronous.decision is DBIMultipartRoutingDecision.SYNCHRONOUS
    assert synchronous.part_count == 0
    assert synchronous.part_size_bytes is None

    first_multipart = DBIMultipartPolicy.build_upload_plan(size_bytes=64 * MIB + 1)
    assert first_multipart.decision is DBIMultipartRoutingDecision.MULTIPART
    assert first_multipart.part_count == 2
    assert DBIMultipartPolicy.expected_part_size(
        first_multipart,
        part_number=1,
    ) == 64 * MIB
    assert DBIMultipartPolicy.expected_part_size(
        first_multipart,
        part_number=2,
    ) == 1

    ten_gib = DBIMultipartPolicy.build_upload_plan(size_bytes=10 * GIB)
    maximum = DBIMultipartPolicy.build_upload_plan(size_bytes=20 * GIB)
    blocked = DBIMultipartPolicy.build_upload_plan(size_bytes=20 * GIB + 1)
    assert ten_gib.part_count == 160
    assert maximum.part_count == 320
    assert blocked.decision is DBIMultipartRoutingDecision.BLOCKED_BY_POLICY
    assert blocked.reason_code is DBIMultipartPolicyReason.SIZE_EXCEEDS_POLICY
    assert blocked.part_count == 0


def validate_configurable_limits() -> None:
    base = DBI_MULTIPART_DEFAULT_LIMITS
    invalid = (
        replace(base, synchronous_max_bytes=True),
        replace(base, multipart_max_bytes=base.synchronous_max_bytes),
        replace(base, part_size_bytes=5 * MIB - 1),
        replace(base, part_size_bytes=5 * GIB + 1),
        replace(base, max_parts=10_001),
        replace(base, max_grants_per_window=65),
        replace(base, max_client_concurrency=9),
    )
    for limits in invalid:
        _must_fail(lambda limits=limits: DBIMultipartPolicy.validate_limits(limits))

    part_limited = replace(
        base,
        multipart_max_bytes=100 * MIB,
        part_size_bytes=5 * MIB,
        max_parts=10,
    )
    blocked = DBIMultipartPolicy.build_upload_plan(
        size_bytes=64 * MIB + 1,
        limits=part_limited,
    )
    assert blocked.reason_code is DBIMultipartPolicyReason.PART_COUNT_EXCEEDS_POLICY


def validate_checksum_semantics() -> None:
    DBIMultipartPolicy.validate_checksum_mode(
        DBIMultipartChecksumAlgorithm.SHA256,
        DBIMultipartChecksumType.COMPOSITE,
    )
    DBIMultipartPolicy.validate_checksum_mode(
        DBIMultipartChecksumAlgorithm.CRC64NVME,
        DBIMultipartChecksumType.FULL_OBJECT,
    )
    _must_fail(
        lambda: DBIMultipartPolicy.validate_checksum_mode(
            DBIMultipartChecksumAlgorithm.SHA256,
            DBIMultipartChecksumType.FULL_OBJECT,
        )
    )
    assert DBIMultipartPolicy.validate_transport_checksum(
        PART_CHECKSUM,
        algorithm=DBIMultipartChecksumAlgorithm.SHA256,
    ) == PART_CHECKSUM
    for invalid in ("", "not-base64", base64.b64encode(b"short").decode("ascii")):
        _must_fail(
            lambda invalid=invalid: DBIMultipartPolicy.validate_transport_checksum(
                invalid,
                algorithm=DBIMultipartChecksumAlgorithm.SHA256,
            )
        )


def validate_parts() -> None:
    plan = DBIMultipartPolicy.build_upload_plan(size_bytes=128 * MIB + 1)
    parts = tuple(_evidence(plan, number) for number in range(1, 4))
    normalized = DBIMultipartPolicy.validate_complete_part_set(
        plan,
        tuple(reversed(parts)),
    )
    assert tuple(part.part_number for part in normalized) == (1, 2, 3)
    assert sum(part.size_bytes for part in normalized) == plan.size_bytes

    _must_fail(
        lambda: DBIMultipartPolicy.validate_complete_part_set(plan, parts[:-1]),
        DBIMultipartConflict,
    )
    _must_fail(
        lambda: DBIMultipartPolicy.validate_complete_part_set(
            plan,
            parts + (parts[-1],),
        ),
        DBIMultipartConflict,
    )
    _must_fail(
        lambda: DBIMultipartPolicy.validate_part_evidence(
            replace(parts[0], size_bytes=parts[0].size_bytes - 1),
            plan=plan,
        ),
        DBIMultipartConflict,
    )
    _must_fail(
        lambda: DBIMultipartPolicy.validate_part_evidence(
            replace(parts[0], session_id="forged"),
            plan=plan,
        )
    )


def validate_idempotency() -> None:
    identity = DBIMultipartPolicy.build_idempotency_identity(
        idempotency_key="upload-request-0001",
        asset_id=ASSET_ID,
        content_type="image/tiff",
        size_bytes=10 * GIB,
        sha256_hex=SHA256_HEX,
    )
    exact = DBIMultipartPolicy.build_idempotency_identity(
        idempotency_key="upload-request-0001",
        asset_id=ASSET_ID,
        content_type="image/tiff",
        size_bytes=10 * GIB,
        sha256_hex=SHA256_HEX,
    )
    other_key = DBIMultipartPolicy.build_idempotency_identity(
        idempotency_key="upload-request-0002",
        asset_id=ASSET_ID,
        content_type="image/tiff",
        size_bytes=10 * GIB,
        sha256_hex=SHA256_HEX,
    )
    divergent = DBIMultipartPolicy.build_idempotency_identity(
        idempotency_key="upload-request-0001",
        asset_id=ASSET_ID,
        content_type="image/tiff",
        size_bytes=10 * GIB + 1,
        sha256_hex=SHA256_HEX,
    )
    assert DBIMultipartPolicy.validate_idempotent_reuse(identity, exact) is True
    assert DBIMultipartPolicy.validate_idempotent_reuse(identity, other_key) is False
    _must_fail(
        lambda: DBIMultipartPolicy.validate_idempotent_reuse(identity, divergent),
        DBIMultipartConflict,
    )
    assert "upload-request-0001" not in repr(identity)
    _must_fail(
        lambda: DBIMultipartPolicy.build_idempotency_identity(
            idempotency_key="short",
            asset_id=ASSET_ID,
            content_type="image/tiff",
            size_bytes=10 * GIB,
            sha256_hex=SHA256_HEX,
        )
    )


def validate_transitions() -> None:
    uploading = DBIMultipartPolicy.plan_transition(
        DBIMultipartSessionState.INITIATED,
        DBIMultipartSessionState.UPLOADING,
    )
    assert uploading.changed is True
    completed = DBIMultipartPolicy.plan_transition(
        DBIMultipartSessionState.UPLOADING,
        DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION,
    )
    assert completed.changed is True
    repeated = DBIMultipartPolicy.plan_transition(
        DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION,
        DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION,
    )
    assert repeated.changed is False
    for terminal in (
        DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION,
        DBIMultipartSessionState.ABORTED,
        DBIMultipartSessionState.EXPIRED,
        DBIMultipartSessionState.BLOCKED_BY_POLICY,
    ):
        _must_fail(
            lambda terminal=terminal: DBIMultipartPolicy.plan_transition(
                terminal,
                DBIMultipartSessionState.UPLOADING,
            ),
            DBIMultipartConflict,
        )


def validate_static_boundaries() -> None:
    paths = (
        BACKEND_ROOT / "app" / "dbi" / "asset_multipart_contracts.py",
        BACKEND_ROOT / "app" / "dbi" / "asset_multipart_policy.py",
    )
    forbidden_imports = {
        "boto3",
        "botocore",
        "fastapi",
        "sqlalchemy",
        "requests",
        "httpx",
    }
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.partition(".")[0])
        assert forbidden_imports.isdisjoint(roots)

    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for forbidden in (
        "open_read(",
        "put_object(",
        "generate_presigned_url(",
        "commit(",
        "rollback(",
        "DATABASE_URL",
    ):
        assert forbidden not in source


def main() -> None:
    validate_default_boundaries()
    validate_configurable_limits()
    validate_checksum_semantics()
    validate_parts()
    validate_idempotency()
    validate_transitions()
    validate_static_boundaries()
    print("Contratos y política multipartes DBI-ASSET-003 aprobados offline.")


if __name__ == "__main__":
    main()
