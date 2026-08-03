"""Pruebas offline de confirmación y verificación criptográfica DBI."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from app.dbi.asset_registration import DBIAssetRegistrationConflict
from app.dbi.asset_verification import DBIAssetVerificationDecision
from app.dbi.asset_verification_service import DBIAssetVerificationService
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
)
from app.dbi.models.assets import AnalysisInputAsset
from app.dbi.storage_contracts import (
    DBIStorageObjectRecord,
    DBIStorageObjectState,
    DBIStoragePurpose,
)
from app.dbi.storage_policy import DBIStoragePolicy


class FakeRepository:
    def __init__(self, row: AnalysisInputAsset | None) -> None:
        self.row = row
        self.get_calls = 0
        self.apply_calls = []

    def get_for_update(self, *, tenant_ref, farm_id, asset_id):
        self.get_calls += 1
        return self.row

    def apply_verification(self, *, row, decision, verified_at):
        self.apply_calls.append((row, decision, verified_at))
        row.status = decision.value
        row.verified_at = (
            verified_at
            if decision is DBIAssetVerificationDecision.VERIFIED
            else None
        )
        return True


class FakeStore:
    def __init__(self, *, metadata, content: bytes) -> None:
        self.metadata = metadata
        self.content = content
        self.stat_calls = 0
        self.read_calls = 0

    def stat(self, address):
        self.stat_calls += 1
        return DBIStorageObjectRecord(
            metadata=self.metadata,
            state=DBIStorageObjectState.ACTIVE,
            created_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )

    @contextmanager
    def open_read(self, address):
        self.read_calls += 1
        with BytesIO(self.content) as stream:
            yield stream


def _context(farm_id) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="principal-1",
        tenant_ref="tenant-1",
        organization_refs=frozenset({"org-1"}),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref="org-1", farm_id=farm_id)}
        ),
        permissions=frozenset({DBIPermission.WRITE}),
    )


def _row(content: bytes) -> tuple[AnalysisInputAsset, object]:
    asset_id = uuid4()
    farm_id = uuid4()
    digest = sha256(content).hexdigest()
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref="tenant-1",
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=asset_id,
        ),
        content_type="image/tiff",
        size_bytes=len(content),
        sha256_hex=digest,
    )
    row = AnalysisInputAsset(
        id=asset_id,
        tenant_ref="tenant-1",
        farm_id=farm_id,
        plot_id=None,
        asset_kind="orthophoto",
        status="registered",
        object_key=metadata.address.object_key,
        content_type=metadata.content_type,
        size_bytes=metadata.size_bytes,
        sha256=metadata.sha256,
        crs="EPSG:32717",
        created_by_ref="principal-1",
        verified_at=None,
    )
    return row, metadata


def _must_deny(callable_) -> None:
    try:
        callable_()
    except DBIAccessDenied:
        return
    raise AssertionError("La operación debía ser denegada.")


def _must_conflict(callable_) -> None:
    try:
        callable_()
    except DBIAssetRegistrationConflict:
        return
    raise AssertionError("La operación debía detectar una clave divergente.")


def main() -> None:
    content = b"synthetic-orthophoto-content"
    row, metadata = _row(content)
    repository = FakeRepository(row)
    store = FakeStore(metadata=metadata, content=content)
    service = DBIAssetVerificationService(repository, store)
    verified_at = datetime(2026, 8, 3, 1, tzinfo=timezone.utc)

    evidence = service.confirm(
        _context(row.farm_id),
        organization_ref="org-1",
        farm_id=row.farm_id,
        asset_id=row.id,
        verified_at=verified_at,
    )
    assert evidence.result.decision is DBIAssetVerificationDecision.VERIFIED
    assert evidence.result.observed_size_bytes == len(content)
    assert evidence.result.observed_sha256 == sha256(content).hexdigest()
    assert evidence.changed is True
    assert row.status == "verified"
    assert row.verified_at == verified_at
    assert store.stat_calls == 1 and store.read_calls == 1

    bad_row, bad_metadata = _row(content)
    bad_repository = FakeRepository(bad_row)
    bad_store = FakeStore(metadata=bad_metadata, content=b"tampered")
    bad_evidence = DBIAssetVerificationService(
        bad_repository,
        bad_store,
    ).confirm(
        _context(bad_row.farm_id),
        organization_ref="org-1",
        farm_id=bad_row.farm_id,
        asset_id=bad_row.id,
        verified_at=verified_at,
    )
    assert bad_evidence.result.decision is DBIAssetVerificationDecision.QUARANTINED
    assert bad_row.status == "quarantined"
    assert bad_row.verified_at is None

    forged_row, forged_metadata = _row(content)
    forged_row.object_key = "tenants/forged/analysis-inputs/forged"
    forged_repository = FakeRepository(forged_row)
    forged_store = FakeStore(metadata=forged_metadata, content=content)
    _must_conflict(
        lambda: DBIAssetVerificationService(
            forged_repository,
            forged_store,
        ).confirm(
            _context(forged_row.farm_id),
            organization_ref="org-1",
            farm_id=forged_row.farm_id,
            asset_id=forged_row.id,
            verified_at=verified_at,
        )
    )
    assert forged_repository.apply_calls == []
    assert forged_store.stat_calls == 0
    assert forged_store.read_calls == 0

    denied_repository = FakeRepository(row)
    denied_store = FakeStore(metadata=metadata, content=content)
    denied_service = DBIAssetVerificationService(denied_repository, denied_store)
    denied_context = DBIAccessContext(
        principal_ref="principal-1",
        tenant_ref="tenant-1",
        permissions=frozenset({DBIPermission.READ}),
    )
    _must_deny(
        lambda: denied_service.confirm(
            denied_context,
            organization_ref="org-1",
            farm_id=row.farm_id,
            asset_id=row.id,
            verified_at=verified_at,
        )
    )
    assert denied_repository.get_calls == 0
    assert denied_store.stat_calls == 0

    print("Confirmación y verificación criptográfica de activos DBI aprobadas offline.")


if __name__ == "__main__":
    main()
