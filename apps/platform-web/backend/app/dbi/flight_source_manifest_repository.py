"""Persistencia transaccional de manifiestos de fuentes de vuelo DBI."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.flight_source_manifest import (
    DBIFlightSourceAssetSnapshot,
    DBIFlightSourceEntrySnapshot,
    DBIFlightSourceManifestError,
    DBIFlightSourceManifestPage,
    DBIFlightSourceManifestRecord,
    DBIFlightSourcePersistedManifest,
)
from app.dbi.models.assets import AnalysisInputAsset
from app.dbi.models.flight_source_manifest import (
    FlightSourceBundle,
    FlightSourceEntry,
)


def _plot_filter(plot_id: UUID | None):
    return (
        AnalysisInputAsset.plot_id.is_(None)
        if plot_id is None
        else AnalysisInputAsset.plot_id == plot_id
    )


def _asset_snapshot(row: AnalysisInputAsset) -> DBIFlightSourceAssetSnapshot:
    return DBIFlightSourceAssetSnapshot(
        asset_id=row.id,
        tenant_ref=row.tenant_ref,
        farm_id=row.farm_id,
        plot_id=row.plot_id,
        asset_kind=row.asset_kind,
        status=row.status,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
    )


def _entry_snapshot(row: FlightSourceEntry) -> DBIFlightSourceEntrySnapshot:
    return DBIFlightSourceEntrySnapshot(
        asset_id=row.asset_id,
        ordinal=row.ordinal,
        role=row.role,
        logical_name=row.logical_name,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        sensor_camera=row.sensor_camera,
        captured_at=row.captured_at,
    )


def _record(
    bundle: FlightSourceBundle,
    entries: tuple[DBIFlightSourceEntrySnapshot, ...],
) -> DBIFlightSourceManifestRecord:
    return DBIFlightSourceManifestRecord(
        bundle_id=bundle.id,
        tenant_ref=bundle.tenant_ref,
        farm_id=bundle.farm_id,
        plot_id=bundle.plot_id,
        flight_ref=bundle.flight_ref,
        master_asset_id=bundle.master_asset_id,
        schema_version=bundle.schema_version,
        manifest_sha256=bundle.manifest_sha256,
        entry_count=bundle.entry_count,
        total_size_bytes=bundle.total_size_bytes,
        created_by_ref=bundle.created_by_ref,
        created_at=bundle.created_at,
        entries=entries,
    )


def _same_manifest(
    actual: DBIFlightSourceManifestRecord,
    expected: DBIFlightSourceManifestRecord,
) -> bool:
    return (
        actual.bundle_id == expected.bundle_id
        and actual.tenant_ref == expected.tenant_ref
        and actual.farm_id == expected.farm_id
        and actual.plot_id == expected.plot_id
        and actual.flight_ref == expected.flight_ref
        and actual.master_asset_id == expected.master_asset_id
        and actual.schema_version == expected.schema_version
        and actual.manifest_sha256 == expected.manifest_sha256
        and actual.entry_count == expected.entry_count
        and actual.total_size_bytes == expected.total_size_bytes
        and actual.created_by_ref == expected.created_by_ref
        and actual.entries == expected.entries
    )


class DBIFlightSourceManifestRepository:
    """No confirma ni revierte la unidad de trabajo externa."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBIFlightSourceManifestError("session debe ser Session.")
        self._session = session

    def get_assets_for_manifest(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_ids: frozenset[UUID],
    ) -> dict[UUID, DBIFlightSourceAssetSnapshot]:
        if not asset_ids or len(asset_ids) > 10_001:
            raise DBIFlightSourceManifestError("cantidad de activos inválida.")
        rows = self._session.execute(
            select(AnalysisInputAsset)
            .where(
                AnalysisInputAsset.tenant_ref == tenant_ref,
                AnalysisInputAsset.farm_id == farm_id,
                _plot_filter(plot_id),
                AnalysisInputAsset.id.in_(asset_ids),
            )
            .order_by(AnalysisInputAsset.id)
            .with_for_update()
        ).scalars()
        return {row.id: _asset_snapshot(row) for row in rows}

    def persist_manifest(
        self,
        *,
        record: DBIFlightSourceManifestRecord,
    ) -> DBIFlightSourcePersistedManifest:
        if not isinstance(record, DBIFlightSourceManifestRecord):
            raise DBIFlightSourceManifestError("record inválido.")
        inserted = self._session.execute(
            postgresql_insert(FlightSourceBundle)
            .values(
                id=record.bundle_id,
                tenant_ref=record.tenant_ref,
                farm_id=record.farm_id,
                plot_id=record.plot_id,
                flight_ref=record.flight_ref,
                master_asset_id=record.master_asset_id,
                schema_version=record.schema_version,
                manifest_sha256=record.manifest_sha256,
                entry_count=record.entry_count,
                total_size_bytes=record.total_size_bytes,
                created_by_ref=record.created_by_ref,
                created_at=record.created_at,
            )
            .on_conflict_do_nothing()
            .returning(FlightSourceBundle.id)
        ).scalar_one_or_none()
        created = inserted is not None
        if created:
            self._session.execute(
                postgresql_insert(FlightSourceEntry),
                [
                    {
                        "bundle_id": record.bundle_id,
                        "asset_id": entry.asset_id,
                        "tenant_ref": record.tenant_ref,
                        "ordinal": entry.ordinal,
                        "role": entry.role,
                        "logical_name": entry.logical_name,
                        "content_type": entry.content_type,
                        "size_bytes": entry.size_bytes,
                        "sha256": entry.sha256,
                        "sensor_camera": entry.sensor_camera,
                        "captured_at": entry.captured_at,
                    }
                    for entry in record.entries
                ],
            )
            self._session.flush()

        bundle = self._session.execute(
            select(FlightSourceBundle)
            .where(
                FlightSourceBundle.id == record.bundle_id,
                FlightSourceBundle.tenant_ref == record.tenant_ref,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if bundle is None:
            raise DBIFlightSourceManifestError("identidad de manifiesto en conflicto.")
        rows = self._session.execute(
            select(FlightSourceEntry)
            .where(
                FlightSourceEntry.bundle_id == record.bundle_id,
                FlightSourceEntry.tenant_ref == record.tenant_ref,
            )
            .order_by(FlightSourceEntry.ordinal)
        ).scalars()
        actual = _record(bundle, tuple(_entry_snapshot(row) for row in rows))
        if not _same_manifest(actual, record):
            raise DBIFlightSourceManifestError("reintento de manifiesto divergente.")
        return DBIFlightSourcePersistedManifest(manifest=actual, created=created)

    def get_manifest_page(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        master_asset_id: UUID,
        bundle_id: UUID,
        offset: int,
        limit: int,
    ) -> DBIFlightSourceManifestPage | None:
        plot_clause = (
            FlightSourceBundle.plot_id.is_(None)
            if plot_id is None
            else FlightSourceBundle.plot_id == plot_id
        )
        bundle = self._session.execute(
            select(FlightSourceBundle)
            .join(
                AnalysisInputAsset,
                and_(
                    AnalysisInputAsset.id == FlightSourceBundle.master_asset_id,
                    AnalysisInputAsset.tenant_ref == FlightSourceBundle.tenant_ref,
                ),
            )
            .where(
                FlightSourceBundle.id == bundle_id,
                FlightSourceBundle.tenant_ref == tenant_ref,
                FlightSourceBundle.farm_id == farm_id,
                plot_clause,
                FlightSourceBundle.master_asset_id == master_asset_id,
                AnalysisInputAsset.farm_id == farm_id,
                _plot_filter(plot_id),
            )
        ).scalar_one_or_none()
        if bundle is None:
            return None
        rows = self._session.execute(
            select(FlightSourceEntry)
            .where(
                FlightSourceEntry.bundle_id == bundle_id,
                FlightSourceEntry.tenant_ref == tenant_ref,
            )
            .order_by(FlightSourceEntry.ordinal)
            .offset(offset)
            .limit(limit)
        ).scalars()
        page_entries = tuple(_entry_snapshot(row) for row in rows)
        return DBIFlightSourceManifestPage(
            manifest=_record(bundle, ()),
            entries=page_entries,
            offset=offset,
            limit=limit,
            has_more=offset + len(page_entries) < bundle.entry_count,
        )

