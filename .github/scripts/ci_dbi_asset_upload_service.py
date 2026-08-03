"""Pruebas offline de registro y grant temporal de carga DBI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.dbi.asset_registration import (
    DBIAssetRegistrationAction,
    DBIAssetRegistrationPlan,
)
from app.dbi.asset_schemas import AnalysisInputAssetRegister
from app.dbi.asset_service import DBIAssetRegistrationEvidence
from app.dbi.asset_upload_service import (
    DBIAssetUploadGrantFailure,
    DBIAssetUploadService,
)
from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.storage_contracts import (
    DBIStorageAccessMode,
    DBIStorageConflict,
    DBIStoragePurpose,
    DBIStorageTemporaryGrant,
)
from app.dbi.storage_policy import DBIStoragePolicy


class FakeRegistrationService:
    def __init__(self, evidence=None, error=None) -> None:
        self.evidence = evidence
        self.error = error
        self.calls = 0

    def register(self, context, *, organization_ref, farm_id, request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.evidence


class FakeStore:
    def __init__(self, *, error=None, divergent=False) -> None:
        self.error = error
        self.divergent = divergent
        self.calls = []

    def issue_temporary_access(self, metadata, *, mode, issued_at, expires_at):
        self.calls.append((metadata, mode, issued_at, expires_at))
        if self.error is not None:
            raise self.error
        returned_metadata = metadata
        if self.divergent:
            returned_metadata = DBIStoragePolicy.build_metadata(
                address=DBIStoragePolicy.build_address(
                    tenant_ref=metadata.address.tenant_ref,
                    purpose=metadata.address.purpose,
                    object_id=uuid4(),
                ),
                content_type=metadata.content_type,
                size_bytes=metadata.size_bytes,
                sha256_hex=metadata.sha256,
            )
        return DBIStorageTemporaryGrant(
            grant_ref="synthetic-grant-ref-1234",
            metadata=returned_metadata,
            mode=mode,
            issued_at=issued_at,
            expires_at=expires_at,
        )


def _evidence() -> DBIAssetRegistrationEvidence:
    asset_id = uuid4()
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref="tenant-1",
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=asset_id,
        ),
        content_type="image/tiff",
        size_bytes=128,
        sha256_hex="a" * 64,
    )
    return DBIAssetRegistrationEvidence(
        plan=DBIAssetRegistrationPlan(
            action=DBIAssetRegistrationAction.CREATE,
            metadata=metadata,
            asset_id=asset_id,
            tenant_ref="tenant-1",
            farm_id=uuid4(),
            plot_id=None,
            asset_kind="orthophoto",
            status="registered",
            crs="EPSG:32717",
            created_by_ref="principal-1",
        ),
        created=True,
    )


def _request(asset_id) -> AnalysisInputAssetRegister:
    return AnalysisInputAssetRegister(
        asset_id=asset_id,
        asset_kind="orthophoto",
        content_type="image/tiff",
        size_bytes=128,
        sha256="a" * 64,
        crs="EPSG:32717",
    )


def _context() -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="principal-1",
        tenant_ref="tenant-1",
    )


def _must_fail(callable_, error_type) -> None:
    try:
        callable_()
    except error_type:
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}.")


def main() -> None:
    evidence = _evidence()
    registration = FakeRegistrationService(evidence=evidence)
    store = FakeStore()
    service = DBIAssetUploadService(
        registration,
        store,
        grant_ttl=timedelta(minutes=10),
    )
    issued_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
    result = service.register_and_issue_upload(
        _context(),
        organization_ref="org-1",
        farm_id=evidence.plan.farm_id,
        request=_request(evidence.plan.asset_id),
        issued_at=issued_at,
    )
    assert result.registration is evidence
    assert result.grant.mode is DBIStorageAccessMode.WRITE
    assert result.grant.metadata == evidence.plan.metadata
    assert result.grant.expires_at == issued_at + timedelta(minutes=10)
    assert registration.calls == 1
    assert len(store.calls) == 1

    denied_registration = FakeRegistrationService(error=DBIAccessDenied())
    untouched_store = FakeStore()
    denied_service = DBIAssetUploadService(denied_registration, untouched_store)
    _must_fail(
        lambda: denied_service.register_and_issue_upload(
            _context(),
            organization_ref="org-1",
            farm_id=evidence.plan.farm_id,
            request=_request(evidence.plan.asset_id),
            issued_at=issued_at,
        ),
        DBIAccessDenied,
    )
    assert untouched_store.calls == []

    persistence_failure = RuntimeError("persistencia fallida")
    failed_registration = FakeRegistrationService(error=persistence_failure)
    untouched_store_2 = FakeStore()
    failed_service = DBIAssetUploadService(failed_registration, untouched_store_2)
    _must_fail(
        lambda: failed_service.register_and_issue_upload(
            _context(),
            organization_ref="org-1",
            farm_id=evidence.plan.farm_id,
            request=_request(evidence.plan.asset_id),
            issued_at=issued_at,
        ),
        RuntimeError,
    )
    assert untouched_store_2.calls == []

    grant_failure_store = FakeStore(error=DBIStorageConflict("fallo sintético"))
    grant_failure_service = DBIAssetUploadService(
        FakeRegistrationService(evidence=evidence),
        grant_failure_store,
    )
    _must_fail(
        lambda: grant_failure_service.register_and_issue_upload(
            _context(),
            organization_ref="org-1",
            farm_id=evidence.plan.farm_id,
            request=_request(evidence.plan.asset_id),
            issued_at=issued_at,
        ),
        DBIAssetUploadGrantFailure,
    )
    assert len(grant_failure_store.calls) == 1

    divergent_service = DBIAssetUploadService(
        FakeRegistrationService(evidence=evidence),
        FakeStore(divergent=True),
    )
    _must_fail(
        lambda: divergent_service.register_and_issue_upload(
            _context(),
            organization_ref="org-1",
            farm_id=evidence.plan.farm_id,
            request=_request(evidence.plan.asset_id),
            issued_at=issued_at,
        ),
        DBIAssetUploadGrantFailure,
    )

    _must_fail(
        lambda: DBIAssetUploadService(
            FakeRegistrationService(evidence=evidence),
            FakeStore(),
            grant_ttl=timedelta(seconds=10),
        ),
        DBIStorageConflict,
    )

    print("Registro y grant temporal de carga DBI aprobados offline.")


if __name__ == "__main__":
    main()
