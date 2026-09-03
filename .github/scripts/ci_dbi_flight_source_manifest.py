"""Valida manifiestos de vuelo sin red, almacenamiento ni binarios."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_base import DBIBase  # noqa: E402
from app.dbi import models as dbi_models  # noqa: E402,F401
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.flight_source_manifest import (  # noqa: E402
    DBIFlightSourceAssetSnapshot,
    DBIFlightSourceEntryIntent,
    DBIFlightSourceManifestError,
    DBIFlightSourceManifestPage,
    DBIFlightSourceManifestRecord,
    DBIFlightSourceManifestService,
    DBIFlightSourceManifestUnavailable,
    DBIFlightSourcePersistedManifest,
    build_flight_source_manifest_record,
)


TENANT = "tenant-manifest-ci"
ORG = "organization-manifest-ci"
FARM = UUID("10000000-0000-0000-0000-000000000001")
PLOT = UUID("20000000-0000-0000-0000-000000000001")
MASTER = UUID("30000000-0000-0000-0000-000000000001")
PHOTO = UUID("40000000-0000-0000-0000-000000000001")
AUXILIARY = UUID("50000000-0000-0000-0000-000000000001")
BUNDLE = UUID("60000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc)


def _context(*permissions: DBIPermission) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="principal-manifest-ci",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset({DBIFarmScope(ORG, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORG, FARM, PLOT)}),
        permissions=frozenset(permissions),
    )


def _asset(
    asset_id: UUID,
    kind: str,
    *,
    size_bytes: int,
    content_type: str,
    digest: str,
    status: str = "registered",
) -> DBIFlightSourceAssetSnapshot:
    return DBIFlightSourceAssetSnapshot(
        asset_id=asset_id,
        tenant_ref=TENANT,
        farm_id=FARM,
        plot_id=PLOT,
        asset_kind=kind,
        status=status,
        content_type=content_type,
        size_bytes=size_bytes,
        sha256=digest,
    )


def _assets() -> dict[UUID, DBIFlightSourceAssetSnapshot]:
    return {
        MASTER: _asset(
            MASTER,
            "orthophoto",
            size_bytes=7_000_000_000,
            content_type="image/tiff",
            digest="a" * 64,
        ),
        PHOTO: _asset(
            PHOTO,
            "flight_photo",
            size_bytes=22_000_000,
            content_type="image/jpeg",
            digest="b" * 64,
        ),
        AUXILIARY: _asset(
            AUXILIARY,
            "flight_auxiliary",
            size_bytes=14_000,
            content_type="application/json",
            digest="c" * 64,
        ),
    }


def _entries(*, reverse: bool = False):
    values = [
        DBIFlightSourceEntryIntent(
            asset_id=PHOTO,
            logical_name="DCIM/100MEDIA/DJI_0001.JPG",
            role="source_photo",
            sensor_camera="DJI FC6310R",
            captured_at=NOW,
        ),
        DBIFlightSourceEntryIntent(
            asset_id=AUXILIARY,
            logical_name="metadata/flight-log.json",
            role="auxiliary",
        ),
    ]
    return tuple(reversed(values)) if reverse else tuple(values)


def _record(entries=None, assets=None) -> DBIFlightSourceManifestRecord:
    return build_flight_source_manifest_record(
        bundle_id=BUNDLE,
        tenant_ref=TENANT,
        farm_id=FARM,
        plot_id=PLOT,
        flight_ref="flight-2026-08-03-001",
        master_asset_id=MASTER,
        entries=_entries() if entries is None else entries,
        assets=_assets() if assets is None else assets,
        created_by_ref="principal-manifest-ci",
        created_at=NOW,
    )


class _Repository:
    def __init__(self, assets=None) -> None:
        self.assets = _assets() if assets is None else assets
        self.persisted: DBIFlightSourceManifestRecord | None = None
        self.asset_reads = 0

    def get_assets_for_manifest(self, **kwargs):
        self.asset_reads += 1
        return {
            asset_id: self.assets[asset_id]
            for asset_id in kwargs["asset_ids"]
            if asset_id in self.assets
        }

    def persist_manifest(self, *, record):
        if self.persisted is None:
            self.persisted = record
            return DBIFlightSourcePersistedManifest(record, True)
        if self.persisted.manifest_sha256 != record.manifest_sha256:
            raise DBIFlightSourceManifestError("reintento divergente")
        return DBIFlightSourcePersistedManifest(self.persisted, False)

    def get_manifest_page(self, **kwargs):
        if self.persisted is None or kwargs["bundle_id"] != self.persisted.bundle_id:
            return None
        offset = kwargs["offset"]
        limit = kwargs["limit"]
        values = self.persisted.entries[offset : offset + limit]
        summary = DBIFlightSourceManifestRecord(
            **{
                field: getattr(self.persisted, field)
                for field in (
                    "bundle_id",
                    "tenant_ref",
                    "farm_id",
                    "plot_id",
                    "flight_ref",
                    "master_asset_id",
                    "schema_version",
                    "manifest_sha256",
                    "entry_count",
                    "total_size_bytes",
                    "created_by_ref",
                    "created_at",
                )
            },
            entries=(),
        )
        return DBIFlightSourceManifestPage(
            manifest=summary,
            entries=values,
            offset=offset,
            limit=limit,
            has_more=offset + len(values) < self.persisted.entry_count,
        )


def _raises(expected, action) -> None:
    try:
        action()
    except expected:
        return
    raise AssertionError(f"Se esperaba {expected.__name__}.")


def validate_deterministic_manifest() -> None:
    first = _record()
    second = _record(entries=_entries(reverse=True))
    assert first.schema_version == "flight-source-bundle.v1"
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.entry_count == 2
    assert first.total_size_bytes == 22_014_000
    assert [entry.ordinal for entry in first.entries] == [1, 2]
    assert [entry.logical_name for entry in first.entries] == sorted(
        entry.logical_name for entry in first.entries
    )
    assert "object_key" not in repr(first)


def validate_rejections() -> None:
    _raises(
        DBIFlightSourceManifestError,
        lambda: _record(
            entries=(
                DBIFlightSourceEntryIntent(PHOTO, "../secret.jpg", "source_photo"),
            )
        ),
    )
    _raises(
        DBIFlightSourceManifestError,
        lambda: _record(
            entries=(
                DBIFlightSourceEntryIntent(PHOTO, "a.jpg", "source_photo"),
                DBIFlightSourceEntryIntent(PHOTO, "b.jpg", "source_photo"),
            )
        ),
    )
    _raises(
        DBIFlightSourceManifestUnavailable,
        lambda: _record(
            entries=(
                DBIFlightSourceEntryIntent(PHOTO, "a.jpg", "auxiliary"),
            )
        ),
    )
    quarantined = _assets()
    quarantined[PHOTO] = _asset(
        PHOTO,
        "flight_photo",
        size_bytes=22_000_000,
        content_type="image/jpeg",
        digest="b" * 64,
        status="quarantined",
    )
    _raises(
        DBIFlightSourceManifestUnavailable,
        lambda: _record(assets=quarantined),
    )


def validate_service_and_pagination() -> None:
    repository = _Repository()
    service = DBIFlightSourceManifestService(repository)
    result = service.create(
        _context(DBIPermission.WRITE, DBIPermission.READ),
        organization_ref=ORG,
        farm_id=FARM,
        plot_id=PLOT,
        master_asset_id=MASTER,
        bundle_id=BUNDLE,
        flight_ref="flight-2026-08-03-001",
        entries=_entries(),
        created_at=NOW,
    )
    assert result.created is True
    repeated = service.create(
        _context(DBIPermission.WRITE, DBIPermission.READ),
        organization_ref=ORG,
        farm_id=FARM,
        plot_id=PLOT,
        master_asset_id=MASTER,
        bundle_id=BUNDLE,
        flight_ref="flight-2026-08-03-001",
        entries=_entries(reverse=True),
        created_at=NOW,
    )
    assert repeated.created is False
    first_page = service.inspect(
        _context(DBIPermission.READ),
        organization_ref=ORG,
        farm_id=FARM,
        plot_id=PLOT,
        master_asset_id=MASTER,
        bundle_id=BUNDLE,
        offset=0,
        limit=1,
    )
    assert len(first_page.entries) == 1
    assert first_page.has_more is True
    second_page = service.inspect(
        _context(DBIPermission.READ),
        organization_ref=ORG,
        farm_id=FARM,
        plot_id=PLOT,
        master_asset_id=MASTER,
        bundle_id=BUNDLE,
        offset=1,
        limit=1,
    )
    assert len(second_page.entries) == 1
    assert second_page.has_more is False

    denied_repository = _Repository()
    denied_service = DBIFlightSourceManifestService(denied_repository)
    _raises(
        DBIAccessDenied,
        lambda: denied_service.create(
            _context(DBIPermission.READ),
            organization_ref=ORG,
            farm_id=FARM,
            plot_id=PLOT,
            master_asset_id=MASTER,
            bundle_id=BUNDLE,
            flight_ref="flight-2026-08-03-001",
            entries=_entries(),
            created_at=NOW,
        ),
    )
    assert denied_repository.asset_reads == 0


def validate_models_and_sources() -> None:
    tables = DBIBase.metadata.tables
    assert "dbi_flight_source_bundles" in tables
    assert "dbi_flight_source_entries" in tables
    asset_kind_sql = str(
        next(
            constraint.sqltext
            for constraint in tables["dbi_analysis_input_assets"].constraints
            if constraint.name == "ck_dbi_analysis_input_assets_kind"
        )
    )
    assert "flight_photo" in asset_kind_sql
    assert "flight_auxiliary" in asset_kind_sql
    bundle_constraints = {
        constraint.name
        for constraint in tables["dbi_flight_source_bundles"].constraints
    }
    entry_constraints = {
        constraint.name
        for constraint in tables["dbi_flight_source_entries"].constraints
    }
    assert "fk_dbi_flight_source_bundles_master_tenant" in bundle_constraints
    assert "fk_dbi_flight_source_bundles_plot_farm" in bundle_constraints
    assert "fk_dbi_flight_source_entries_asset_tenant" in entry_constraints
    assert "uq_dbi_flight_source_entries_ordinal" in entry_constraints

    api_source = (
        BACKEND / "app" / "api" / "v1" / "dbi_flight_source_manifests.py"
    ).read_text(encoding="utf-8")
    assert "flight-source-manifests" in api_source
    assert "limit: Annotated[int, Query(ge=1, le=500)]" in api_source
    for forbidden in ("UploadFile", "bytes =", "object_key", "presigned"):
        assert forbidden not in api_source

    scripts = ScriptDirectory.from_config(
        Config(str(BACKEND / "dbi_alembic.ini"))
    )
    assert scripts.get_heads() == ["dbi_0014_analysis_results"]
    revision = scripts.get_revision("dbi_0011_flight_manifest")
    assert revision is not None
    assert revision.down_revision == "dbi_0010_asset_multipart"
    migration_source = (
        BACKEND
        / "dbi_alembic"
        / "versions"
        / "20260803_11_flight_source_manifest.py"
    ).read_text(encoding="utf-8")
    assert "op.drop_table(\"dbi_flight_source_entries\")" in migration_source
    assert "op.drop_table(\"dbi_flight_source_bundles\")" in migration_source
    assert migration_source.rindex(
        'op.drop_table("dbi_flight_source_entries")'
    ) < migration_source.rindex(
        'op.drop_table("dbi_flight_source_bundles")'
    )


def main() -> None:
    validate_deterministic_manifest()
    validate_rejections()
    validate_service_and_pagination()
    validate_models_and_sources()
    print("Manifiesto de fuentes de vuelo DBI: validación offline aprobada.")


if __name__ == "__main__":
    main()
