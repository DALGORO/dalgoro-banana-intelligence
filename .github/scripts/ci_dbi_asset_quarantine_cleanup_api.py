"""Pruebas offline de la frontera HTTP de limpieza de cuarentena DBI."""

from __future__ import annotations

import os
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "dbi-ci-placeholder")
os.environ.setdefault("ENABLE_DOCS", "0")

from app.api.v1.dbi_assets import cleanup_quarantined_asset
from app.dbi.asset_api_schemas import DBIAssetQuarantineCleanupRequest
from app.dbi.asset_quarantine_cleanup_service import (
    DBIAssetQuarantineCleanupEvidence,
)
from app.dbi.asset_registration import DBIAssetRegistrationConflict
from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.storage_contracts import DBIStorageError


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeCleanupService:
    def __init__(self, *, evidence=None, error=None) -> None:
        self.evidence = evidence
        self.error = error
        self.calls = 0

    def cleanup(self, *args, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.evidence


def _context() -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="principal-1",
        tenant_ref="tenant-1",
    )


def _must_http_error(callable_, status_code: int) -> None:
    try:
        callable_()
    except HTTPException as error:
        assert error.status_code == status_code
        return
    raise AssertionError(f"Se esperaba HTTP {status_code}.")


def main() -> None:
    asset_id = uuid4()
    farm_id = uuid4()
    payload = DBIAssetQuarantineCleanupRequest(
        organization_ref="org-1",
        farm_id=farm_id,
    )

    changed_session = FakeSession()
    changed_service = FakeCleanupService(
        evidence=DBIAssetQuarantineCleanupEvidence(
            object_changed=True,
        )
    )
    changed_result = cleanup_quarantined_asset(
        asset_id=asset_id,
        payload=payload,
        session=changed_session,
        context=_context(),
        service=changed_service,
    )

    assert changed_result.asset_id == asset_id
    assert changed_result.status == "quarantined"
    assert changed_result.changed is True
    assert changed_session.commits == 1
    assert changed_session.rollbacks == 0
    assert changed_service.calls == 1

    changed_dump = changed_result.model_dump()
    assert "object_changed" not in changed_dump
    assert "object_key" not in changed_dump
    assert "tenant_ref" not in changed_dump

    retry_session = FakeSession()
    retry_result = cleanup_quarantined_asset(
        asset_id=asset_id,
        payload=payload,
        session=retry_session,
        context=_context(),
        service=FakeCleanupService(
            evidence=DBIAssetQuarantineCleanupEvidence(
                object_changed=False,
            )
        ),
    )

    assert retry_result.status == "quarantined"
    assert retry_result.changed is False
    assert retry_session.commits == 1
    assert retry_session.rollbacks == 0

    denied_session = FakeSession()
    _must_http_error(
        lambda: cleanup_quarantined_asset(
            asset_id=asset_id,
            payload=payload,
            session=denied_session,
            context=_context(),
            service=FakeCleanupService(
                error=DBIAccessDenied(),
            ),
        ),
        404,
    )
    assert denied_session.commits == 0
    assert denied_session.rollbacks == 1

    conflict_session = FakeSession()
    _must_http_error(
        lambda: cleanup_quarantined_asset(
            asset_id=asset_id,
            payload=payload,
            session=conflict_session,
            context=_context(),
            service=FakeCleanupService(
                error=DBIAssetRegistrationConflict(
                    "estado incompatible"
                ),
            ),
        ),
        404,
    )
    assert conflict_session.commits == 0
    assert conflict_session.rollbacks == 1

    provider_session = FakeSession()
    _must_http_error(
        lambda: cleanup_quarantined_asset(
            asset_id=asset_id,
            payload=payload,
            session=provider_session,
            context=_context(),
            service=FakeCleanupService(
                error=DBIStorageError(
                    "proveedor no disponible"
                ),
            ),
        ),
        503,
    )
    assert provider_session.commits == 0
    assert provider_session.rollbacks == 1

    try:
        DBIAssetQuarantineCleanupRequest(
            organization_ref="*",
            farm_id=farm_id,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError(
            "La limpieza debía rechazar el comodín organizacional."
        )

    try:
        DBIAssetQuarantineCleanupRequest(
            organization_ref="org-1",
            farm_id=farm_id,
            tenant_ref="tenant-inyectado",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError(
            "La limpieza debía rechazar campos extra."
        )

    print("API de limpieza de cuarentena DBI aprobada offline.")


if __name__ == "__main__":
    main()
