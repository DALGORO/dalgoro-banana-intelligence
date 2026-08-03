"""Pruebas offline de la frontera HTTP transaccional de activos DBI."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException, Response
from pydantic import ValidationError

# El módulo de configuración se construye durante los imports de la API.
# Estas variables sintéticas deben existir antes de importar cualquier módulo app.
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "dbi-ci-placeholder")
os.environ.setdefault("ENABLE_DOCS", "0")

from app.api.v1.dbi_assets import (
    confirm_asset_upload,
    register_asset_upload,
    retire_asset,
)
from app.dbi.asset_api_schemas import (
    DBIAssetConfirmRequest,
    DBIAssetRetireRequest,
    DBIAssetUploadRequest,
)
from app.dbi.asset_registration import (
    DBIAssetRegistrationAction,
    DBIAssetRegistrationPlan,
)
from app.dbi.asset_retirement_service import DBIAssetRetirementEvidence
from app.dbi.asset_service import DBIAssetRegistrationEvidence
from app.dbi.asset_upload_service import (
    DBIAssetSynchronousLimitExceeded,
    DBIAssetUploadEvidence,
)
from app.dbi.asset_verification import (
    DBIAssetVerificationDecision,
    DBIAssetVerificationResult,
)
from app.dbi.asset_verification_service import DBIAssetVerificationEvidence
from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.storage_contracts import (
    DBIStorageAccessMode,
    DBIStorageError,
    DBIStorageNotFound,
    DBIStoragePurpose,
    DBIStorageTemporaryGrant,
)
from app.dbi.storage_policy import DBIStoragePolicy
from app.dbi.storage_s3 import DBIS3ResolvedTemporaryAccess


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeUploadService:
    def __init__(self, evidence=None, error=None) -> None:
        self.evidence = evidence
        self.error = error
        self.calls = 0

    def register_and_issue_upload(self, *args, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.evidence


class FakeVerificationService:
    def __init__(self, evidence=None, error=None) -> None:
        self.evidence = evidence
        self.error = error
        self.calls = 0

    def confirm(self, *args, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.evidence


class FakeRetirementService:
    def __init__(self, evidence=None, error=None) -> None:
        self.evidence = evidence
        self.error = error
        self.calls = 0

    def retire(self, *args, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.evidence


class FakeStore:
    def __init__(self, access=None, error=None) -> None:
        self.access = access
        self.error = error
        self.calls = 0

    def resolve_temporary_access(self, grant_ref):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.access


def _context() -> DBIAccessContext:
    return DBIAccessContext(principal_ref="principal-1", tenant_ref="tenant-1")


def _upload_fixture():
    asset_id = uuid4()
    farm_id = uuid4()
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref="tenant-1",
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=asset_id,
        ),
        content_type="image/tiff",
        size_bytes=4,
        sha256_hex="a" * 64,
    )
    plan = DBIAssetRegistrationPlan(
        action=DBIAssetRegistrationAction.CREATE,
        metadata=metadata,
        asset_id=asset_id,
        tenant_ref="tenant-1",
        farm_id=farm_id,
        plot_id=None,
        asset_kind="orthophoto",
        status="registered",
        crs="EPSG:32717",
        created_by_ref="principal-1",
    )
    registration = DBIAssetRegistrationEvidence(plan=plan, created=True)
    issued_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
    grant = DBIStorageTemporaryGrant(
        grant_ref="synthetic-grant-ref-1234",
        metadata=metadata,
        mode=DBIStorageAccessMode.WRITE,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=15),
    )
    evidence = DBIAssetUploadEvidence(registration=registration, grant=grant)
    access = DBIS3ResolvedTemporaryAccess(
        grant=grant,
        method="PUT",
        url="https://storage.invalid/private-signed-upload",
        headers=(("content-type", "image/tiff"),),
    )
    payload = DBIAssetUploadRequest(
        organization_ref="org-1",
        farm_id=farm_id,
        asset={
            "asset_id": str(asset_id),
            "asset_kind": "orthophoto",
            "content_type": "image/tiff",
            "size_bytes": 4,
            "sha256": "a" * 64,
            "crs": "EPSG:32717",
        },
    )
    return asset_id, farm_id, payload, evidence, access


def _must_http_error(callable_, status_code: int) -> HTTPException:
    try:
        callable_()
    except HTTPException as error:
        assert error.status_code == status_code
        return error
    raise AssertionError(f"Se esperaba HTTP {status_code}.")


def main() -> None:
    asset_id, farm_id, payload, upload_evidence, access = _upload_fixture()
    session = FakeSession()
    response = Response()
    result = register_asset_upload(
        payload=payload,
        response=response,
        session=session,
        context=_context(),
        store=FakeStore(access=access),
        service=FakeUploadService(evidence=upload_evidence),
    )
    assert response.status_code == 201
    assert session.commits == 1 and session.rollbacks == 0
    assert result.asset_id == asset_id
    assert result.status == "registered"
    assert result.upload.method == "PUT"
    assert "grant_ref" not in result.model_dump()
    assert "object_key" not in result.model_dump()

    denied_session = FakeSession()
    denied_store = FakeStore(access=access)
    _must_http_error(
        lambda: register_asset_upload(
            payload=payload,
            response=Response(),
            session=denied_session,
            context=_context(),
            store=denied_store,
            service=FakeUploadService(error=DBIAccessDenied()),
        ),
        404,
    )
    assert denied_session.commits == 0 and denied_session.rollbacks == 1
    assert denied_store.calls == 0

    oversized_session = FakeSession()
    oversized_store = FakeStore(access=access)
    oversized_error = _must_http_error(
        lambda: register_asset_upload(
            payload=payload,
            response=Response(),
            session=oversized_session,
            context=_context(),
            store=oversized_store,
            service=FakeUploadService(
                error=DBIAssetSynchronousLimitExceeded(
                    size_bytes=64 * 1024 * 1024 + 1,
                    max_size_bytes=64 * 1024 * 1024,
                )
            ),
        ),
        413,
    )
    assert oversized_error.detail == {
        "code": "asset_multipart_required",
        "message": (
            "El activo supera el límite síncrono y requiere carga multipartes."
        ),
        "max_synchronous_size_bytes": 64 * 1024 * 1024,
        "required_flow": "multipart_upload",
    }
    assert oversized_session.commits == 0 and oversized_session.rollbacks == 1
    assert oversized_store.calls == 0

    provider_session = FakeSession()
    _must_http_error(
        lambda: register_asset_upload(
            payload=payload,
            response=Response(),
            session=provider_session,
            context=_context(),
            store=FakeStore(error=DBIStorageNotFound()),
            service=FakeUploadService(evidence=upload_evidence),
        ),
        503,
    )
    assert provider_session.commits == 0 and provider_session.rollbacks == 1

    verified = DBIAssetVerificationEvidence(
        result=DBIAssetVerificationResult(
            decision=DBIAssetVerificationDecision.VERIFIED,
            observed_size_bytes=4,
            observed_sha256="a" * 64,
            content_type_matches=True,
        ),
        changed=True,
    )
    confirm_session = FakeSession()
    confirm_result = confirm_asset_upload(
        asset_id=asset_id,
        payload=DBIAssetConfirmRequest(
            organization_ref="org-1",
            farm_id=farm_id,
        ),
        session=confirm_session,
        context=_context(),
        service=FakeVerificationService(evidence=verified),
    )
    assert confirm_result.status == "verified"
    assert confirm_result.reason == "verified"
    assert confirm_session.commits == 1 and confirm_session.rollbacks == 0

    quarantined = DBIAssetVerificationEvidence(
        result=DBIAssetVerificationResult(
            decision=DBIAssetVerificationDecision.QUARANTINED,
            observed_size_bytes=3,
            observed_sha256="b" * 64,
            content_type_matches=True,
        ),
        changed=True,
    )
    quarantine_result = confirm_asset_upload(
        asset_id=asset_id,
        payload=DBIAssetConfirmRequest(
            organization_ref="org-1",
            farm_id=farm_id,
        ),
        session=FakeSession(),
        context=_context(),
        service=FakeVerificationService(evidence=quarantined),
    )
    assert quarantine_result.status == "quarantined"
    assert quarantine_result.reason == "integrity_mismatch"
    dumped = quarantine_result.model_dump()
    assert "observed_sha256" not in dumped and "object_key" not in dumped

    not_found_session = FakeSession()
    _must_http_error(
        lambda: confirm_asset_upload(
            asset_id=uuid4(),
            payload=DBIAssetConfirmRequest(
                organization_ref="org-1",
                farm_id=farm_id,
            ),
            session=not_found_session,
            context=_context(),
            service=FakeVerificationService(error=DBIAccessDenied()),
        ),
        404,
    )
    assert not_found_session.commits == 0 and not_found_session.rollbacks == 1

    retirement = DBIAssetRetirementEvidence(
        object_changed=True,
        state_changed=True,
    )
    retirement_session = FakeSession()

    retirement_result = retire_asset(
        asset_id=asset_id,
        payload=DBIAssetRetireRequest(
            organization_ref="org-1",
            farm_id=farm_id,
        ),
        session=retirement_session,
        context=_context(),
        service=FakeRetirementService(
            evidence=retirement,
        ),
    )

    assert retirement_result.asset_id == asset_id
    assert retirement_result.status == "retired"
    assert retirement_result.changed is True
    assert retirement_session.commits == 1
    assert retirement_session.rollbacks == 0

    retirement_dump = retirement_result.model_dump()
    assert "object_changed" not in retirement_dump
    assert "state_changed" not in retirement_dump
    assert "object_key" not in retirement_dump

    retry_session = FakeSession()
    retry_result = retire_asset(
        asset_id=asset_id,
        payload=DBIAssetRetireRequest(
            organization_ref="org-1",
            farm_id=farm_id,
        ),
        session=retry_session,
        context=_context(),
        service=FakeRetirementService(
            evidence=DBIAssetRetirementEvidence(
                object_changed=False,
                state_changed=False,
            ),
        ),
    )

    assert retry_result.status == "retired"
    assert retry_result.changed is False
    assert retry_session.commits == 1
    assert retry_session.rollbacks == 0

    retirement_denied_session = FakeSession()
    _must_http_error(
        lambda: retire_asset(
            asset_id=asset_id,
            payload=DBIAssetRetireRequest(
                organization_ref="org-1",
                farm_id=farm_id,
            ),
            session=retirement_denied_session,
            context=_context(),
            service=FakeRetirementService(
                error=DBIAccessDenied(),
            ),
        ),
        404,
    )
    assert retirement_denied_session.commits == 0
    assert retirement_denied_session.rollbacks == 1

    retirement_missing_object_session = FakeSession()
    _must_http_error(
        lambda: retire_asset(
            asset_id=asset_id,
            payload=DBIAssetRetireRequest(
                organization_ref="org-1",
                farm_id=farm_id,
            ),
            session=retirement_missing_object_session,
            context=_context(),
            service=FakeRetirementService(
                error=DBIStorageNotFound(),
            ),
        ),
        409,
    )
    assert retirement_missing_object_session.commits == 0
    assert retirement_missing_object_session.rollbacks == 1

    retirement_provider_session = FakeSession()
    _must_http_error(
        lambda: retire_asset(
            asset_id=asset_id,
            payload=DBIAssetRetireRequest(
                organization_ref="org-1",
                farm_id=farm_id,
            ),
            session=retirement_provider_session,
            context=_context(),
            service=FakeRetirementService(
                error=DBIStorageError(
                    "proveedor no disponible"
                ),
            ),
        ),
        503,
    )
    assert retirement_provider_session.commits == 0
    assert retirement_provider_session.rollbacks == 1

    try:
        DBIAssetConfirmRequest(
            organization_ref="*",
            farm_id=farm_id,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("El comodín organizacional debía rechazarse.")

    try:
        DBIAssetUploadRequest(
            organization_ref="org-1",
            farm_id=farm_id,
            asset=payload.asset,
            tenant_ref="tenant-inyectado",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Los campos extra debían rechazarse.")

    try:
        DBIAssetRetireRequest(
            organization_ref="*",
            farm_id=farm_id,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError(
            "El retiro debía rechazar el comodín organizacional."
        )

    try:
        DBIAssetRetireRequest(
            organization_ref="org-1",
            farm_id=farm_id,
            tenant_ref="tenant-inyectado",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError(
            "El retiro debía rechazar campos extra."
        )

    print("API transaccional de activos DBI aprobada offline.")


if __name__ == "__main__":
    main()
