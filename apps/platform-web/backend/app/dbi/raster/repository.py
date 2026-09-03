"""Persistencia idempotente de productos COG DBI."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.models.raster_products import DBIRasterProduct
from app.dbi.raster.contracts import (
    DBIRasterConflict,
    DBIRasterProductCandidate,
    DBIRasterSource,
    canonical_json,
    validate_candidate,
)


class DBIRasterProductRepository:
    """Repository corto y puro; sólo opera sobre la sesión recibida."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBIRasterConflict("session debe ser Session.")
        self._session = session

    def persist_ready(
        self,
        source: DBIRasterSource,
        candidate: DBIRasterProductCandidate,
        *,
        object_key: str,
    ) -> tuple[DBIRasterProduct, bool]:
        prepared = validate_candidate(candidate)
        transform_json = canonical_json(prepared.transform)
        bounds_json = canonical_json(prepared.bounds)
        nodata_json = canonical_json(prepared.nodata)
        scales_json = canonical_json(prepared.scales)
        offsets_json = canonical_json(prepared.offsets)
        overview_levels_json = canonical_json(prepared.overview_levels)

        inserted = self._session.execute(
            postgresql_insert(DBIRasterProduct)
            .values(
                id=prepared.object_id,
                tenant_ref=source.tenant_ref,
                farm_id=source.farm_id,
                plot_id=source.plot_id,
                source_kind=prepared.source_kind.value,
                source_ref=prepared.source_ref,
                source_sha256=prepared.source_sha256,
                product_kind=prepared.product_kind.value,
                profile_version=prepared.profile_version,
                generator_version=prepared.generator_version,
                object_key=object_key,
                content_type=prepared.content_type,
                size_bytes=prepared.size_bytes,
                sha256=prepared.sha256,
                crs=prepared.crs,
                width=prepared.width,
                height=prepared.height,
                band_count=prepared.band_count,
                dtype=prepared.dtype,
                transform_json=transform_json,
                bounds_json=bounds_json,
                nodata_json=nodata_json,
                scales_json=scales_json,
                offsets_json=offsets_json,
                block_width=prepared.block_width,
                block_height=prepared.block_height,
                compression=prepared.compression.lower(),
                overview_levels_json=overview_levels_json,
                status="ready",
                retired_at=None,
            )
            .on_conflict_do_nothing()
            .returning(DBIRasterProduct.id)
        ).scalar_one_or_none()

        rows = self._session.execute(
            select(DBIRasterProduct).where(
                or_(
                    DBIRasterProduct.id == prepared.object_id,
                    DBIRasterProduct.object_key == object_key,
                )
            )
        ).scalars().all()
        if len(rows) != 1:
            raise DBIRasterConflict(
                "La identidad Raster colisiona con más de un producto persistido."
            )
        row = rows[0]
        exact = (
            row.id == prepared.object_id
            and row.tenant_ref == source.tenant_ref
            and row.farm_id == source.farm_id
            and row.plot_id == source.plot_id
            and row.source_kind == prepared.source_kind.value
            and row.source_ref == prepared.source_ref
            and row.source_sha256 == prepared.source_sha256
            and row.product_kind == prepared.product_kind.value
            and row.profile_version == prepared.profile_version
            and row.generator_version == prepared.generator_version
            and row.object_key == object_key
            and row.content_type == prepared.content_type
            and row.size_bytes == prepared.size_bytes
            and row.sha256 == prepared.sha256
            and row.crs == prepared.crs
            and row.width == prepared.width
            and row.height == prepared.height
            and row.band_count == prepared.band_count
            and row.dtype == prepared.dtype
            and row.transform_json == transform_json
            and row.bounds_json == bounds_json
            and row.nodata_json == nodata_json
            and row.scales_json == scales_json
            and row.offsets_json == offsets_json
            and row.block_width == prepared.block_width
            and row.block_height == prepared.block_height
            and row.compression == prepared.compression.lower()
            and row.overview_levels_json == overview_levels_json
            and row.status == "ready"
            and row.retired_at is None
        )
        if not exact:
            raise DBIRasterConflict(
                "La identidad Raster ya representa metadata COG divergente."
            )
        if inserted is not None and inserted != row.id:
            raise DBIRasterConflict("La identidad insertada del producto diverge.")
        return row, inserted is not None

    def get_ready(self, product_id):
        return self._session.execute(
            select(DBIRasterProduct).where(
                DBIRasterProduct.id == product_id,
                DBIRasterProduct.status == "ready",
            )
        ).scalar_one_or_none()
