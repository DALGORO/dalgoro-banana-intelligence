"""Prueba offline de la API multipartes autorizada y sin binarios."""

from __future__ import annotations

import ast
import base64
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, Response
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "dbi-ci-placeholder")
os.environ.setdefault("ENABLE_DOCS", "0")

from app.api.v1.dbi_asset_multipart import (
    complete_multipart_upload,
    grant_multipart_parts,
    initiate_multipart_upload,
    inspect_multipart_upload,
    record_multipart_part,
    router,
)
from app.dbi.asset_multipart_api_schemas import (
    DBIMultipartCompleteRequest,
    DBIMultipartGrantPartsRequest,
    DBIMultipartInitiateRequest,
    DBIMultipartInspectRequest,
    DBIMultipartRecordPartRequest,
)
from app.dbi.asset_multipart_application import (
    DBIMultipartPreparationEvidence,
    DBIMultipartSessionSnapshot,
)
from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm,
    DBIMultipartChecksumType,
    DBIMultipartPartEvidence,
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
    DBIMultipartUploadPlan,
)
from app.dbi.asset_multipart_policy import MIB, DBIMultipartConflict
from app.dbi.asset_multipart_provider import (
    DBIMultipartProviderCompletion,
    DBIMultipartProviderError,
    DBIMultipartProviderPartGrant,
)
from app.dbi.asset_multipart_upload_service import (
    DBIMultipartCompletionEvidence,
    DBIMultipartGrantEvidence,
    DBIMultipartInitiationEvidence,
    DBIMultipartInspectionEvidence,
    DBIMultipartPartRecord,
)
from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.storage_contracts import DBIStoragePurpose
from app.dbi.storage_policy import DBIStoragePolicy


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
ASSET_ID = UUID("11111111-1111-4111-8111-111111111111")
SESSION_ID = UUID("22222222-2222-4222-8222-222222222222")
FARM_ID = UUID("33333333-3333-4333-8333-333333333333")
PLOT_ID = UUID("44444444-4444-4444-8444-444444444444")
NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)
PART_CHECKSUM = base64.b64encode(b"p" * 32).decode("ascii")


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeService:
    def __init__(self, **results) -> None:
        self.results = results
        self.calls: list[tuple[str, dict]] = []

    def _result(self, operation, kwargs):
        self.calls.append((operation, kwargs))
        result = self.results[operation]
        if isinstance(result, Exception):
            raise result
        return result

    def initiate(self, _context, **kwargs):
        return self._result("initiate", kwargs)

    def grant_parts(self, _context, **kwargs):
        return self._result("grant_parts", kwargs)

    def record_part(self, _context, **kwargs):
        return self._result("record_part", kwargs)

    def complete(self, _context, **kwargs):
        return self._result("complete", kwargs)

    def inspect(self, _context, **kwargs):
        return self._result("inspect", kwargs)


@dataclass(frozen=True)
class ResolvedPart:
    grant: DBIMultipartProviderPartGrant
    method: str
    url: str
    headers: tuple[tuple[str, str], ...]


class FakeStore:
    def __init__(self, grants) -> None:
        self.grants = {grant.grant_ref: grant for grant in grants}
        self.resolve_calls = 0

    def resolve_part_access(self, grant_ref):
        self.resolve_calls += 1
        grant = self.grants[grant_ref]
        return ResolvedPart(
            grant=grant,
            method="PUT",
            url=f"https://storage.invalid/parts/{grant.part_number}",
            headers=(("x-amz-checksum-sha256", PART_CHECKSUM),),
        )


def _context() -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="principal-a",
        tenant_ref="tenant-a",
    )


def _snapshot(
    state=DBIMultipartSessionState.UPLOADING,
) -> DBIMultipartSessionSnapshot:
    return DBIMultipartSessionSnapshot(
        session_id=SESSION_ID,
        asset_id=ASSET_ID,
        tenant_ref="tenant-a",
        state=state,
        reason_code=None,
        size_bytes=128 * MIB,
        part_size_bytes=64 * MIB,
        part_count=2,
        max_grants_per_window=8,
        max_client_concurrency=4,
        checksum_algorithm=DBIMultipartChecksumAlgorithm.SHA256,
        checksum_type=DBIMultipartChecksumType.COMPOSITE,
        request_fingerprint="f" * 64,
        created_by_ref="principal-a",
        version=2,
        expires_at=NOW + timedelta(hours=24),
        last_activity_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _plan() -> DBIMultipartUploadPlan:
    return DBIMultipartUploadPlan(
        decision=DBIMultipartRoutingDecision.MULTIPART,
        size_bytes=128 * MIB,
        part_size_bytes=64 * MIB,
        part_count=2,
        max_grants_per_window=8,
        max_client_concurrency=4,
        checksum_algorithm=DBIMultipartChecksumAlgorithm.SHA256,
        checksum_type=DBIMultipartChecksumType.COMPOSITE,
    )


def _scope():
    return {
        "organization_ref": "org-a",
        "farm_id": FARM_ID,
        "plot_id": PLOT_ID,
    }


def _grants():
    return tuple(
        DBIMultipartProviderPartGrant(
            grant_ref=f"grant_part_{number:04d}_opaque",
            session_id=SESSION_ID,
            part_number=number,
            size_bytes=64 * MIB,
            checksum_algorithm=DBIMultipartChecksumAlgorithm.SHA256,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
        )
        for number in (1, 2)
    )


def _must_http_error(callable_, status_code):
    try:
        callable_()
    except HTTPException as error:
        assert error.status_code == status_code
        return
    raise AssertionError(f"Se esperaba HTTP {status_code}.")


def validate_api_flow() -> None:
    snapshot = _snapshot()
    initiation = DBIMultipartInitiationEvidence(
        preparation=DBIMultipartPreparationEvidence(
            plan=_plan(),
            session=replace(snapshot, state=DBIMultipartSessionState.INITIATED),
            created=True,
        ),
        session=snapshot,
        provider_started=True,
    )
    initiate_session = FakeSession()
    response = Response()
    initiated = initiate_multipart_upload(
        asset_id=ASSET_ID,
        payload=DBIMultipartInitiateRequest(
            **_scope(),
            idempotency_key="multipart-request-0001",
        ),
        response=response,
        session=initiate_session,
        context=_context(),
        service=FakeService(initiate=initiation),
    )
    assert response.status_code == 201
    assert initiate_session.commits == 1 and initiate_session.rollbacks == 0
    assert initiated.session.state is DBIMultipartSessionState.UPLOADING
    assert "idempotency_key" not in initiated.model_dump()
    assert "provider_upload_ref" not in initiated.model_dump()

    grants = _grants()
    grant_session = FakeSession()
    store = FakeStore(grants)
    granted = grant_multipart_parts(
        asset_id=ASSET_ID,
        session_id=SESSION_ID,
        payload=DBIMultipartGrantPartsRequest(
            **_scope(),
            parts=[
                {"part_number": 1, "checksum": PART_CHECKSUM},
                {"part_number": 2, "checksum": PART_CHECKSUM},
            ],
        ),
        session=grant_session,
        context=_context(),
        store=store,
        service=FakeService(
            grant_parts=DBIMultipartGrantEvidence(
                session=snapshot,
                grants=grants,
            )
        ),
    )
    assert grant_session.commits == 1 and store.resolve_calls == 2
    assert [grant.part_number for grant in granted.grants] == [1, 2]
    grant_dump = granted.model_dump()
    assert "grant_ref" not in str(grant_dump)
    assert "provider_upload_ref" not in str(grant_dump)

    recorded = record_multipart_part(
        asset_id=ASSET_ID,
        session_id=SESSION_ID,
        payload=DBIMultipartRecordPartRequest(
            **_scope(),
            part_number=1,
            size_bytes=64 * MIB,
            checksum=PART_CHECKSUM,
            etag="etag-1",
        ),
        session=FakeSession(),
        context=_context(),
        service=FakeService(
            record_part=DBIMultipartPartRecord(
                snapshot=snapshot,
                evidence=DBIMultipartPartEvidence(
                    session_id=SESSION_ID,
                    part_number=1,
                    size_bytes=64 * MIB,
                    checksum=PART_CHECKSUM,
                    etag="etag-1",
                ),
                created=True,
                recorded_part_count=1,
            )
        ),
    )
    assert recorded.created is True
    recorded_dump = recorded.model_dump()
    assert "checksum" not in recorded_dump and "etag" not in recorded_dump

    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref="tenant-a",
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=ASSET_ID,
        ),
        content_type="image/tiff",
        size_bytes=128 * MIB,
        sha256_hex="a" * 64,
    )
    completed_snapshot = replace(
        snapshot,
        state=(
            DBIMultipartSessionState
            .COMPLETED_PENDING_CONTENT_VERIFICATION
        ),
        completed_at=NOW + timedelta(minutes=5),
    )
    completed = complete_multipart_upload(
        asset_id=ASSET_ID,
        session_id=SESSION_ID,
        payload=DBIMultipartCompleteRequest(**_scope()),
        session=FakeSession(),
        context=_context(),
        service=FakeService(
            complete=DBIMultipartCompletionEvidence(
                session=completed_snapshot,
                completion=DBIMultipartProviderCompletion(
                    session_id=SESSION_ID,
                    metadata=metadata,
                    checksum_algorithm=DBIMultipartChecksumAlgorithm.SHA256,
                    checksum_type=DBIMultipartChecksumType.COMPOSITE,
                    transport_checksum="transport-checksum-2",
                    etag="assembled-etag",
                    completed_at=NOW + timedelta(minutes=5),
                    created=True,
                ),
                changed=True,
            )
        ),
    )
    assert completed.transport_integrity == "confirmed"
    assert completed.content_verification == "pending"
    assert "transport_checksum" not in completed.model_dump()
    assert "etag" not in completed.model_dump()

    inspected = inspect_multipart_upload(
        asset_id=ASSET_ID,
        session_id=SESSION_ID,
        payload=DBIMultipartInspectRequest(**_scope()),
        session=FakeSession(),
        context=_context(),
        service=FakeService(
            inspect=DBIMultipartInspectionEvidence(
                session=completed_snapshot,
                recorded_part_count=2,
            )
        ),
    )
    assert inspected.recorded_part_count == 2
    assert "request_fingerprint" not in inspected.model_dump()["session"]


def validate_errors_and_schemas() -> None:
    payload = DBIMultipartInspectRequest(**_scope())
    for error, status_code in (
        (DBIAccessDenied(), 404),
        (DBIMultipartConflict("conflict"), 409),
        (DBIMultipartProviderError("provider"), 503),
    ):
        session = FakeSession()
        _must_http_error(
            lambda error=error: inspect_multipart_upload(
                asset_id=ASSET_ID,
                session_id=SESSION_ID,
                payload=payload,
                session=session,
                context=_context(),
                service=FakeService(inspect=error),
            ),
            status_code,
        )
        assert session.commits == 0 and session.rollbacks == 1

    invalid_payloads = (
        {
            **_scope(),
            "idempotency_key": "multipart-request-0001",
            "tenant_ref": "tenant-inyectado",
        },
        {
            **_scope(),
            "idempotency_key": "multipart-request-0001",
            "object_key": "tenants/other/private",
        },
        {
            **_scope(),
            "idempotency_key": "short",
        },
    )
    for value in invalid_payloads:
        try:
            DBIMultipartInitiateRequest(**value)
        except ValidationError:
            pass
        else:
            raise AssertionError("El esquema debía rechazar el campo inseguro.")


def validate_source_boundaries() -> None:
    path = BACKEND / "app" / "api" / "v1" / "dbi_asset_multipart.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "UploadFile" not in source
    assert "File(" not in source
    assert "provider_upload_ref" not in source
    assert "object_key" not in source
    assert "bucket" not in source.casefold()
    assert "endpoint" not in source.casefold()
    assert "abort" not in source.casefold()
    assert "delete" not in source.casefold()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    assert {"boto3", "botocore", "requests", "httpx"}.isdisjoint(roots)

    paths = {
        route.path
        for route in router.routes
        if "POST" in getattr(route, "methods", set())
    }
    assert paths == {
        "/dbi/assets/{asset_id}/multipart/initiate",
        "/dbi/assets/{asset_id}/multipart/{session_id}/grants",
        "/dbi/assets/{asset_id}/multipart/{session_id}/parts",
        "/dbi/assets/{asset_id}/multipart/{session_id}/complete",
        "/dbi/assets/{asset_id}/multipart/{session_id}/inspect",
    }


def main() -> None:
    validate_api_flow()
    validate_errors_and_schemas()
    validate_source_boundaries()
    print("API multipartes DBI-ASSET-003 aprobada offline.")


if __name__ == "__main__":
    main()
