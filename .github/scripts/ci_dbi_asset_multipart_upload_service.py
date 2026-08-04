"""Prueba offline de orquestación autorizada multipartes DBI."""

from __future__ import annotations

import ast
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from app.dbi.asset_multipart_application import (
    DBIMultipartAssetSnapshot,
    DBIMultipartInitiationRecord,
    DBIMultipartPersistedInitiation,
    DBIMultipartSessionSnapshot,
)
from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm,
    DBIMultipartChecksumType,
    DBIMultipartPartEvidence,
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
)
from app.dbi.asset_multipart_policy import MIB, DBIMultipartConflict
from app.dbi.asset_multipart_provider import (
    DBIMultipartProviderCompletion,
    DBIMultipartProviderPartGrant,
    DBIMultipartProviderUpload,
)
from app.dbi.asset_multipart_upload_service import (
    DBIMultipartCompletionRecord,
    DBIMultipartPartAuthorization,
    DBIMultipartPartRecord,
    DBIMultipartSessionContext,
    DBIMultipartUploadService,
)
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
ASSET_ID = UUID("11111111-1111-4111-8111-111111111111")
FARM_ID = UUID("22222222-2222-4222-8222-222222222222")
PLOT_ID = UUID("33333333-3333-4333-8333-333333333333")
NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)
PART_CHECKSUM = base64.b64encode(b"p" * 32).decode("ascii")


def _snapshot(
    record: DBIMultipartInitiationRecord,
) -> DBIMultipartSessionSnapshot:
    return DBIMultipartSessionSnapshot(
        session_id=record.session_id,
        asset_id=record.asset.asset_id,
        tenant_ref=record.asset.tenant_ref,
        state=DBIMultipartSessionState.INITIATED,
        reason_code=None,
        size_bytes=record.plan.size_bytes,
        part_size_bytes=record.plan.part_size_bytes,
        part_count=record.plan.part_count,
        max_grants_per_window=record.plan.max_grants_per_window,
        max_client_concurrency=record.plan.max_client_concurrency,
        checksum_algorithm=record.plan.checksum_algorithm,
        checksum_type=record.plan.checksum_type,
        request_fingerprint=record.identity.request_fingerprint,
        created_by_ref=record.created_by_ref,
        version=1,
        expires_at=record.expires_at,
        last_activity_at=record.requested_at,
        created_at=record.requested_at,
        updated_at=record.requested_at,
    )


class FakeRepository:
    def __init__(self) -> None:
        self.asset = DBIMultipartAssetSnapshot(
            asset_id=ASSET_ID,
            tenant_ref="tenant-a",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            status="registered",
            content_type="image/tiff",
            size_bytes=128 * MIB,
            sha256="a" * 64,
        )
        self.snapshot: DBIMultipartSessionSnapshot | None = None
        self.provider_upload_ref: str | None = None
        self.parts: dict[int, DBIMultipartPartEvidence] = {}
        self.asset_calls = 0
        self.session_calls = 0

    def get_asset_for_update(self, **_kwargs):
        self.asset_calls += 1
        return self.asset

    def persist_initiation(self, *, record):
        if self.snapshot is None:
            self.snapshot = _snapshot(record)
            return DBIMultipartPersistedInitiation(
                snapshot=self.snapshot,
                created=True,
            )
        return DBIMultipartPersistedInitiation(
            snapshot=self.snapshot,
            created=False,
        )

    def get_session_for_update(self, **kwargs):
        self.session_calls += 1
        if (
            self.snapshot is None
            or kwargs["tenant_ref"] != "tenant-a"
            or kwargs["farm_id"] != FARM_ID
            or kwargs["plot_id"] != PLOT_ID
            or kwargs["asset_id"] != ASSET_ID
            or kwargs["session_id"] != self.snapshot.session_id
        ):
            return None
        return DBIMultipartSessionContext(
            snapshot=self.snapshot,
            asset=self.asset,
            provider_upload_ref=self.provider_upload_ref,
        )

    def bind_provider_upload(
        self,
        *,
        context,
        provider_upload_ref,
        changed_at,
    ):
        assert context.snapshot is self.snapshot
        self.provider_upload_ref = provider_upload_ref
        self.snapshot = replace(
            self.snapshot,
            state=DBIMultipartSessionState.UPLOADING,
            version=self.snapshot.version + 1,
            last_activity_at=changed_at,
            updated_at=changed_at,
        )
        return DBIMultipartSessionContext(
            snapshot=self.snapshot,
            asset=self.asset,
            provider_upload_ref=self.provider_upload_ref,
        )

    def record_part(self, *, context, evidence, observed_at):
        assert context.snapshot.session_id == self.snapshot.session_id
        existing = self.parts.get(evidence.part_number)
        if existing is not None and existing != evidence:
            raise DBIMultipartConflict("parte divergente.")
        created = existing is None
        if created:
            self.parts[evidence.part_number] = evidence
            self.snapshot = replace(
                self.snapshot,
                version=self.snapshot.version + 1,
                last_activity_at=observed_at,
                updated_at=observed_at,
            )
        return DBIMultipartPartRecord(
            snapshot=self.snapshot,
            evidence=self.parts[evidence.part_number],
            created=created,
            recorded_part_count=len(self.parts),
        )

    def list_parts(self, *, context):
        assert context.snapshot.session_id == self.snapshot.session_id
        return tuple(self.parts[number] for number in sorted(self.parts))

    def mark_completed(self, *, context, completed_at):
        changed = (
            self.snapshot.state
            is not DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION
        )
        if changed:
            self.snapshot = replace(
                self.snapshot,
                state=(
                    DBIMultipartSessionState
                    .COMPLETED_PENDING_CONTENT_VERIFICATION
                ),
                version=self.snapshot.version + 1,
                last_activity_at=completed_at,
                updated_at=completed_at,
                completed_at=completed_at,
            )
        return DBIMultipartCompletionRecord(
            snapshot=self.snapshot,
            changed=changed,
        )


class FakeProvider:
    def __init__(self) -> None:
        self.upload: DBIMultipartProviderUpload | None = None
        self.initiate_calls = 0
        self.grant_calls = 0
        self.complete_calls = 0
        self.inspect_calls = 0

    def initiate(self, request):
        self.initiate_calls += 1
        self.upload = DBIMultipartProviderUpload(
            provider_upload_ref="provider-upload-secret-001",
            session_id=request.session_id,
            metadata=request.metadata,
            plan=request.plan,
            initiated_at=request.initiated_at,
        )
        return self.upload

    def issue_part_access(self, request):
        self.grant_calls += 1
        return DBIMultipartProviderPartGrant(
            grant_ref=f"grant_part_{request.part_number:04d}_opaque",
            session_id=request.upload.session_id,
            part_number=request.part_number,
            size_bytes=request.size_bytes,
            checksum_algorithm=request.upload.plan.checksum_algorithm,
            issued_at=request.issued_at,
            expires_at=request.expires_at,
        )

    def complete(self, request):
        self.complete_calls += 1
        assert len(request.parts) == 2
        return self._completion(created=True)

    def inspect_completed(self, _upload):
        self.inspect_calls += 1
        return self._completion(created=False)

    def _completion(self, *, created):
        return DBIMultipartProviderCompletion(
            session_id=self.upload.session_id,
            metadata=self.upload.metadata,
            checksum_algorithm=self.upload.plan.checksum_algorithm,
            checksum_type=self.upload.plan.checksum_type,
            transport_checksum="transport-checksum-2",
            etag="assembled-etag",
            completed_at=NOW + timedelta(minutes=5),
            created=created,
        )


def _context(*, write=True):
    return DBIAccessContext(
        principal_ref="principal-a",
        tenant_ref="tenant-a",
        organization_refs=frozenset({"org-a"}),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref="org-a", farm_id=FARM_ID)}
        ),
        plot_scopes=frozenset(
            {
                DBIPlotScope(
                    organization_ref="org-a",
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                )
            }
        ),
        permissions=frozenset(
            {DBIPermission.WRITE if write else DBIPermission.READ}
        ),
    )


def _service(repository, provider):
    return DBIMultipartUploadService(
        repository,
        provider,
        clock=lambda: NOW,
    )


def _initiate(service):
    return service.initiate(
        _context(),
        organization_ref="org-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        idempotency_key="multipart-request-0001",
        checksum_algorithm=DBIMultipartChecksumAlgorithm.SHA256,
        checksum_type=DBIMultipartChecksumType.COMPOSITE,
    )


def _part(session_id, number):
    return DBIMultipartPartEvidence(
        session_id=session_id,
        part_number=number,
        size_bytes=64 * MIB,
        checksum=PART_CHECKSUM,
        etag=f"etag-{number}",
    )


def validate_complete_flow_and_retries() -> None:
    repository = FakeRepository()
    provider = FakeProvider()
    service = _service(repository, provider)

    initiated = _initiate(service)
    assert initiated.preparation.plan.decision is DBIMultipartRoutingDecision.MULTIPART
    assert initiated.provider_started is True
    assert initiated.session.state is DBIMultipartSessionState.UPLOADING
    assert provider.initiate_calls == 1
    assert "provider-upload-secret-001" not in repr(initiated)

    retry = _initiate(service)
    assert retry.provider_started is False
    assert retry.session.session_id == initiated.session.session_id
    assert provider.initiate_calls == 1

    grants = service.grant_parts(
        _context(),
        organization_ref="org-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        session_id=initiated.session.session_id,
        parts=(
            DBIMultipartPartAuthorization(1, PART_CHECKSUM),
            DBIMultipartPartAuthorization(2, PART_CHECKSUM),
        ),
    )
    assert [grant.part_number for grant in grants.grants] == [1, 2]
    assert all(
        grant.expires_at == NOW + timedelta(minutes=15)
        for grant in grants.grants
    )
    assert PART_CHECKSUM not in repr(grants)

    first = service.record_part(
        _context(),
        organization_ref="org-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        session_id=initiated.session.session_id,
        evidence=_part(initiated.session.session_id, 1),
    )
    assert first.created is True and first.recorded_part_count == 1
    first_retry = service.record_part(
        _context(),
        organization_ref="org-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        session_id=initiated.session.session_id,
        evidence=_part(initiated.session.session_id, 1),
    )
    assert first_retry.created is False
    service.record_part(
        _context(),
        organization_ref="org-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        session_id=initiated.session.session_id,
        evidence=_part(initiated.session.session_id, 2),
    )

    completed = service.complete(
        _context(),
        organization_ref="org-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        session_id=initiated.session.session_id,
        full_object_checksum=None,
    )
    assert completed.changed is True
    assert completed.session.state is (
        DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION
    )
    assert repository.asset.status == "registered"
    assert provider.complete_calls == 1

    completed_retry = service.complete(
        _context(),
        organization_ref="org-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        session_id=initiated.session.session_id,
        full_object_checksum=None,
    )
    assert completed_retry.changed is False
    assert provider.complete_calls == 1
    assert provider.inspect_calls == 1

    inspected = service.inspect(
        _context(),
        organization_ref="org-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        session_id=initiated.session.session_id,
    )
    assert inspected.recorded_part_count == 2
    assert "provider-upload-secret-001" not in repr(inspected)


def validate_authorization_precedes_repository() -> None:
    repository = FakeRepository()
    provider = FakeProvider()
    service = _service(repository, provider)
    try:
        service.inspect(
            _context(write=False),
            organization_ref="org-a",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            asset_id=ASSET_ID,
            session_id=UUID("44444444-4444-4444-8444-444444444444"),
        )
    except DBIAccessDenied:
        pass
    else:
        raise AssertionError("La inspección sin escritura debía denegarse.")
    assert repository.session_calls == 0
    assert provider.initiate_calls == 0


def validate_static_boundaries() -> None:
    path = (
        BACKEND / "app" / "dbi" / "asset_multipart_upload_service.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    assert {
        "fastapi",
        "sqlalchemy",
        "boto3",
        "botocore",
        "requests",
        "httpx",
    }.isdisjoint(roots)
    for forbidden in (
        "UploadFile",
        "File(",
        "open(",
        ".commit(",
        ".rollback(",
        "abort",
        "delete",
    ):
        assert forbidden not in source


def main() -> None:
    validate_complete_flow_and_retries()
    validate_authorization_precedes_repository()
    validate_static_boundaries()
    print("Orquestación multipartes DBI-ASSET-003 aprobada offline.")


if __name__ == "__main__":
    main()
