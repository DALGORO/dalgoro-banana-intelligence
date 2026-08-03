"""Valida el retiro lógico coordinado de activos DBI offline."""

from __future__ import annotations

import ast
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.dbi.asset_registration import (  # noqa: E402
    DBIAssetRegistrationConflict,
)
from app.dbi.asset_retirement_service import (  # noqa: E402
    DBIAssetRetirementService,
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
RETIRED_AT = datetime(2026, 8, 3, 3, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self, row: AnalysisInputAsset | None) -> None:
        self.row = row
        self.get_calls = 0
        self.apply_calls: list[tuple[AnalysisInputAsset, datetime]] = []

    def get_for_update(
        self,
        *,
        tenant_ref,
        farm_id,
        asset_id,
    ):
        self.get_calls += 1
        return self.row

    def apply_retirement(
        self,
        *,
        row,
        retired_at,
    ):
        self.apply_calls.append((row, retired_at))

        if row.status == "retired":
            return False

        row.status = "retired"
        row.updated_at = retired_at
        return True


class FakeStore:
    def __init__(
        self,
        *,
        result: bool = True,
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
    status: str = "registered",
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


def validate_success_and_retries() -> None:
    row = _row()
    repository = FakeRepository(row)
    store = FakeStore(result=True)

    evidence = DBIAssetRetirementService(
        repository,
        store,
    ).retire(
        _context(),
        organization_ref="org-1",
        farm_id=FARM_ID,
        asset_id=ASSET_ID,
        retired_at=RETIRED_AT,
    )

    assert evidence.object_changed is True
    assert evidence.state_changed is True
    assert row.status == "retired"
    assert row.updated_at == RETIRED_AT
    assert repository.get_calls == 1
    assert len(repository.apply_calls) == 1
    assert len(store.calls) == 1

    address, timestamp = store.calls[0]
    assert address.object_id == ASSET_ID
    assert address.tenant_ref == "tenant-1"
    assert address.purpose is DBIStoragePurpose.ANALYSIS_INPUT
    assert timestamp == RETIRED_AT

    retry_row = _row()
    retry_repository = FakeRepository(retry_row)
    retry_store = FakeStore(result=False)

    retry_evidence = DBIAssetRetirementService(
        retry_repository,
        retry_store,
    ).retire(
        _context(),
        organization_ref="org-1",
        farm_id=FARM_ID,
        asset_id=ASSET_ID,
        retired_at=RETIRED_AT,
    )

    assert retry_evidence.object_changed is False
    assert retry_evidence.state_changed is True
    assert retry_row.status == "retired"

    retired_row = _row(status="retired")
    retired_repository = FakeRepository(retired_row)
    retired_store = FakeStore(result=False)

    retired_evidence = DBIAssetRetirementService(
        retired_repository,
        retired_store,
    ).retire(
        _context(),
        organization_ref="org-1",
        farm_id=FARM_ID,
        asset_id=ASSET_ID,
        retired_at=RETIRED_AT,
    )

    assert retired_evidence.object_changed is False
    assert retired_evidence.state_changed is False
    assert len(retired_repository.apply_calls) == 1
    assert len(retired_store.calls) == 1

    missing_row = _row()
    missing_repository = FakeRepository(missing_row)
    missing_store = FakeStore(error=DBIStorageNotFound())
    missing_evidence = DBIAssetRetirementService(
        missing_repository,
        missing_store,
    ).retire(
        _context(),
        organization_ref="org-1",
        farm_id=FARM_ID,
        asset_id=ASSET_ID,
        retired_at=RETIRED_AT,
    )

    assert missing_evidence.object_changed is False
    assert missing_evidence.state_changed is True
    assert missing_row.status == "retired"
    assert len(missing_repository.apply_calls) == 1
    assert len(missing_store.calls) == 1


def validate_authorization_and_guards() -> None:
    denied_repository = FakeRepository(_row())
    denied_store = FakeStore()

    _must_raise(
        DBIAccessDenied,
        lambda: DBIAssetRetirementService(
            denied_repository,
            denied_store,
        ).retire(
            _context(write=False),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            retired_at=RETIRED_AT,
        ),
    )

    assert denied_repository.get_calls == 0
    assert denied_repository.apply_calls == []
    assert denied_store.calls == []

    plot_repository = FakeRepository(
        _row(plot_id=PLOT_ID)
    )
    plot_store = FakeStore()

    _must_raise(
        DBIAccessDenied,
        lambda: DBIAssetRetirementService(
            plot_repository,
            plot_store,
        ).retire(
            _context(include_plot=False),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            retired_at=RETIRED_AT,
        ),
    )

    assert plot_repository.get_calls == 1
    assert plot_repository.apply_calls == []
    assert plot_store.calls == []

    invalid_repository = FakeRepository(
        _row(status="invalid")
    )
    invalid_store = FakeStore()

    _must_raise(
        DBIAssetRegistrationConflict,
        lambda: DBIAssetRetirementService(
            invalid_repository,
            invalid_store,
        ).retire(
            _context(),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            retired_at=RETIRED_AT,
        ),
    )

    assert invalid_repository.apply_calls == []
    assert invalid_store.calls == []

    divergent_row = _row()
    divergent_row.object_key = (
        "tenant-1/analysis-inputs/divergent-object"
    )
    divergent_repository = FakeRepository(divergent_row)
    divergent_store = FakeStore()

    _must_raise(
        DBIAssetRegistrationConflict,
        lambda: DBIAssetRetirementService(
            divergent_repository,
            divergent_store,
        ).retire(
            _context(),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            retired_at=RETIRED_AT,
        ),
    )

    assert divergent_repository.apply_calls == []
    assert divergent_store.calls == []

    naive_repository = FakeRepository(_row())
    naive_store = FakeStore()

    _must_raise(
        DBIAssetRegistrationConflict,
        lambda: DBIAssetRetirementService(
            naive_repository,
            naive_store,
        ).retire(
            _context(),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            retired_at=datetime(2026, 8, 3, 3),
        ),
    )

    assert naive_repository.get_calls == 0
    assert naive_repository.apply_calls == []
    assert naive_store.calls == []


def validate_storage_failures() -> None:
    row = _row()
    repository = FakeRepository(row)
    store = FakeStore(
        error=DBIStorageError("proveedor no disponible")
    )

    _must_raise(
        DBIStorageError,
        lambda: DBIAssetRetirementService(
            repository,
            store,
        ).retire(
            _context(),
            organization_ref="org-1",
            farm_id=FARM_ID,
            asset_id=ASSET_ID,
            retired_at=RETIRED_AT,
        ),
    )

    assert row.status == "registered"
    assert repository.apply_calls == []
    assert len(store.calls) == 1


def validate_static_boundaries() -> None:
    path = (
        BACKEND_ROOT
        / "app"
        / "dbi"
        / "asset_retirement_service.py"
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
        "SessionLocal",
        "DATABASE_URL",
        "HTTPException",
    ):
        assert forbidden not in source

    retire_index = source.index(
        "self._store.retire("
    )
    persistence_index = source.index(
        "self._repository.apply_retirement("
    )

    assert retire_index < persistence_index
    assert "except DBIStorageNotFound" in source
    assert "DBIPermission.WRITE" in source
    assert "require_farm(" in source
    assert "require_plot(" in source


def main() -> None:
    validate_success_and_retries()
    validate_authorization_and_guards()
    validate_storage_failures()
    validate_static_boundaries()

    print(
        "Retiro lógico coordinado de activos DBI aprobado offline."
    )


if __name__ == "__main__":
    main()
