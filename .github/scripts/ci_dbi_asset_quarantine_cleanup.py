"""Valida la limpieza compensatoria de activos DBI en cuarentena."""

from __future__ import annotations

import ast
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.dbi.asset_quarantine_cleanup_service import (  # noqa: E402
    DBIAssetQuarantineCleanupService,
)
from app.dbi.asset_registration import (  # noqa: E402
    DBIAssetRegistrationConflict,
)
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.models.assets import AnalysisInputAsset  # noqa: E402
from app.dbi.storage_contracts import (  # noqa: E402
    DBIStorageError,
    DBIStorageNotFound,
    DBIStoragePurpose,
)
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402


ASSET_ID = UUID("11111111-1111-4111-8111-111111111111")
FARM_ID = UUID("22222222-2222-4222-8222-222222222222")
PLOT_ID = UUID("33333333-3333-4333-8333-333333333333")
CLEANED_AT = datetime(2026, 8, 3, 15, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self, row: AnalysisInputAsset | None) -> None:
        self.row = row
        self.get_calls: list[tuple[object, object, object]] = []

    def get_for_update(
        self,
        *,
        tenant_ref,
        farm_id,
        asset_id,
    ):
        self.get_calls.append(
            (tenant_ref, farm_id, asset_id)
        )
        return self.row


class FakeStore:
    def __init__(
        self,
        *,
        result: object = True,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, datetime]] = []

    def retire(
        self,
        address,
        *,
        retired_at,
    ):
        self.calls.append((address, retired_at))

        if self.error is not None:
            raise self.error

        return self.result


def _context(
    *,
    write: bool = True,
    include_plot: bool = True,
) -> DBIAccessContext:
    farm_scope = DBIFarmScope(
        organization_ref="org-1",
        farm_id=FARM_ID,
    )

    plot_scopes = (
        frozenset(
            {
                DBIPlotScope(
                    organization_ref="org-1",
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                )
            }
        )
        if include_plot
        else frozenset()
    )

    return DBIAccessContext(
        principal_ref="principal-1",
        tenant_ref="tenant-1",
        organization_refs=frozenset({"org-1"}),
        farm_scopes=frozenset({farm_scope}),
        plot_scopes=plot_scopes,
        permissions=frozenset(
            {
                DBIPermission.WRITE
                if write
                else DBIPermission.READ
            }
        ),
    )


def _row(
    *,
    status: str = "quarantined",
    plot_id: UUID | None = None,
) -> AnalysisInputAsset:
    address = DBIStoragePolicy.build_address(
        tenant_ref="tenant-1",
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=ASSET_ID,
    )

    return AnalysisInputAsset(
        id=ASSET_ID,
        tenant_ref="tenant-1",
        farm_id=FARM_ID,
        plot_id=plot_id,
        asset_kind="orthophoto",
        status=status,
        object_key=address.object_key,
        content_type="image/tiff",
        size_bytes=4096,
        sha256="a" * 64,
        crs="EPSG:32717",
        created_by_ref="principal-1",
        verified_at=None,
    )


def _must_raise(expected, callable_) -> None:
    try:
        callable_()
    except expected:
        return

    raise AssertionError(
        f"Se esperaba la excepción {expected.__name__}."
    )


def validate_success_retries_and_absence() -> None:
    row = _row()
    repository = FakeRepository(row)
    store = FakeStore(result=True)

    evidence = DBIAssetQuarantineCleanupService(
        repository,
        store,
    ).cleanup(
        _context(),
        organization_ref="org-1",
        farm_id=FARM_ID,
        asset_id=ASSET_ID,
        cleaned_at=CLEANED_AT,
    )

    assert evidence.object_changed is True
    assert row.status == "quarantined"
    assert len(repository.get_calls) == 1
    assert len(store.calls) == 1

    address, timestamp = store.calls[0]
    assert address.object_id == ASSET_ID
    assert address.tenant_ref == "tenant-1"
    assert address.purpose is DBIStoragePurpose.ANALYSIS_INPUT
    assert address.object_key == row.object_key
    assert timestamp == CLEANED_AT

    retry_row = _row()
    retry_repository = FakeRepository(retry_row)
    retry_store = FakeStore(result=False)

    retry_evidence = DBIAssetQuarantineCleanupService(
        retry_repository,
        retry_store,
    ).cleanup(
        _context(),
        organization_ref="org-1",
        farm_id=FARM_ID,
        asset_id=ASSET_ID,
        cleaned_at=CLEANED_AT,
    )

    assert retry_evidence.object_changed is False
    assert retry_row.status == "quarantined"
    assert len(retry_store.calls) == 1

    missing_row = _row()
    missing_repository = FakeRepository(missing_row)
    missing_store = FakeStore(
        error=DBIStorageNotFound()
    )

    missing_evidence = DBIAssetQuarantineCleanupService(
        missing_repository,
        missing_store,
    ).cleanup(
        _context(),
        organization_ref="org-1",
        farm_id=FARM_ID,
        asset_id=ASSET_ID,
        cleaned_at=CLEANED_AT,
    )

    assert missing_evidence.object_changed is False
    assert missing_row.status == "quarantined"
    assert len(missing_store.calls) == 1


def validate_authorization_and_guards() -> None:
    denied_repository = FakeRepository(_row())
    denied_store = FakeStore()

    _must_raise(
        DBIAccessDenied,
        lambda: DBIAssetQuarantineCleanupService(
            denied_repository,
            denied_store,
        ).cleanup(
            _context(write=False),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            cleaned_at=CLEANED_AT,
        ),
    )

    assert denied_repository.get_calls == []
    assert denied_store.calls == []

    plot_repository = FakeRepository(
        _row(plot_id=PLOT_ID)
    )
    plot_store = FakeStore()

    _must_raise(
        DBIAccessDenied,
        lambda: DBIAssetQuarantineCleanupService(
            plot_repository,
            plot_store,
        ).cleanup(
            _context(include_plot=False),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            cleaned_at=CLEANED_AT,
        ),
    )

    assert len(plot_repository.get_calls) == 1
    assert plot_store.calls == []

    for status in (
        "registered",
        "verified",
        "retired",
    ):
        row = _row(status=status)
        repository = FakeRepository(row)
        store = FakeStore()

        _must_raise(
            DBIAssetRegistrationConflict,
            lambda: DBIAssetQuarantineCleanupService(
                repository,
                store,
            ).cleanup(
                _context(),
                organization_ref="org-1",
                farm_id=FARM_ID,
                asset_id=ASSET_ID,
                cleaned_at=CLEANED_AT,
            ),
        )

        assert row.status == status
        assert store.calls == []

    divergent_identity = _row()
    divergent_identity.tenant_ref = "tenant-2"
    identity_repository = FakeRepository(
        divergent_identity
    )
    identity_store = FakeStore()

    _must_raise(
        DBIAssetRegistrationConflict,
        lambda: DBIAssetQuarantineCleanupService(
            identity_repository,
            identity_store,
        ).cleanup(
            _context(),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            cleaned_at=CLEANED_AT,
        ),
    )

    assert identity_store.calls == []

    divergent_address = _row()
    divergent_address.object_key = (
        "tenant-1/analysis-inputs/divergent-object"
    )
    address_repository = FakeRepository(
        divergent_address
    )
    address_store = FakeStore()

    _must_raise(
        DBIAssetRegistrationConflict,
        lambda: DBIAssetQuarantineCleanupService(
            address_repository,
            address_store,
        ).cleanup(
            _context(),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            cleaned_at=CLEANED_AT,
        ),
    )

    assert address_store.calls == []

    naive_repository = FakeRepository(_row())
    naive_store = FakeStore()

    _must_raise(
        DBIAssetRegistrationConflict,
        lambda: DBIAssetQuarantineCleanupService(
            naive_repository,
            naive_store,
        ).cleanup(
            _context(),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            cleaned_at=datetime(2026, 8, 3, 15),
        ),
    )

    assert naive_repository.get_calls == []
    assert naive_store.calls == []


def validate_provider_failures() -> None:
    row = _row()
    repository = FakeRepository(row)
    store = FakeStore(
        error=DBIStorageError(
            "proveedor no disponible"
        )
    )

    _must_raise(
        DBIStorageError,
        lambda: DBIAssetQuarantineCleanupService(
            repository,
            store,
        ).cleanup(
            _context(),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            cleaned_at=CLEANED_AT,
        ),
    )

    assert row.status == "quarantined"
    assert len(store.calls) == 1

    invalid_row = _row()
    invalid_repository = FakeRepository(invalid_row)
    invalid_store = FakeStore(result="invalid")

    _must_raise(
        TypeError,
        lambda: DBIAssetQuarantineCleanupService(
            invalid_repository,
            invalid_store,
        ).cleanup(
            _context(),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            cleaned_at=CLEANED_AT,
        ),
    )

    assert invalid_row.status == "quarantined"
    assert len(invalid_store.calls) == 1


def validate_static_boundaries() -> None:
    path = (
        BACKEND_ROOT
        / "app"
        / "dbi"
        / "asset_quarantine_cleanup_service.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(
                alias.name.partition(".")[0]
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])

    assert {
        "fastapi",
        "boto3",
        "botocore",
        "requests",
        "httpx",
    }.isdisjoint(roots)

    for forbidden in (
        ".commit(",
        ".rollback(",
        ".flush(",
        "SessionLocal",
        "DATABASE_URL",
        "HTTPException",
        "apply_verification",
        "apply_retirement",
    ):
        assert forbidden not in source

    status_index = source.index(
        'row.status != "quarantined"'
    )
    retirement_index = source.index(
        "self._store.retire("
    )

    assert status_index < retirement_index
    assert "except DBIStorageNotFound" in source
    assert ".status =" not in source
    assert "DBIPermission.WRITE" in source
    assert "require_farm(" in source
    assert "require_plot(" in source


def main() -> None:
    validate_success_retries_and_absence()
    validate_authorization_and_guards()
    validate_provider_failures()
    validate_static_boundaries()

    print(
        "Limpieza compensatoria de activos DBI en cuarentena aprobada offline."
    )


if __name__ == "__main__":
    main()
