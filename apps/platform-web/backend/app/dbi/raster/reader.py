"""Lectura parcial de productos COG listos sin revelar ubicación privada."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.models.raster_products import DBIRasterProduct
from app.dbi.raster.contracts import DBIRasterConflict
from app.dbi.storage_contracts import (
    DBIPrivateObjectStore,
    DBIStorageError,
    DBIStorageNotFound,
    DBIStorageObjectState,
    DBIStoragePurpose,
    MAX_STORAGE_RANGE_BYTES,
)
from app.dbi.storage_policy import DBIStoragePolicy


class DBIRasterProductUnavailable(DBIRasterConflict):
    """El producto solicitado no es visible o no está listo."""


@dataclass(frozen=True, slots=True)
class DBIRasterProductMetadata:
    product_id: UUID
    product_kind: str
    profile_version: str
    content_type: str
    size_bytes: int
    sha256: str
    crs: str
    width: int
    height: int
    band_count: int
    dtype: str
    transform: tuple[float, float, float, float, float, float]
    bounds: tuple[float, float, float, float]
    nodata: tuple[float | None, ...]
    scales: tuple[float, ...]
    offsets: tuple[float, ...]
    block_width: int
    block_height: int
    compression: str
    overview_levels: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DBIRasterRangeSlice:
    product_id: UUID
    start: int
    end_exclusive: int
    total_size_bytes: int
    content_type: str
    data: bytes = field(repr=False)

    @property
    def length(self) -> int:
        return self.end_exclusive - self.start


def _decoded_list(value: str, *, field_name: str) -> list[object]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as error:
        raise DBIRasterConflict(
            f"Metadata Raster persistida inválida: {field_name}."
        ) from error
    if not isinstance(decoded, list):
        raise DBIRasterConflict(
            f"Metadata Raster persistida inválida: {field_name}."
        )
    return decoded


def _float_tuple(
    value: str,
    *,
    field_name: str,
    expected_length: int | None = None,
    allow_none: bool = False,
) -> tuple[float | None, ...]:
    decoded = _decoded_list(value, field_name=field_name)
    if expected_length is not None and len(decoded) != expected_length:
        raise DBIRasterConflict(
            f"Metadata Raster persistida inválida: {field_name}."
        )
    converted: list[float | None] = []
    for item in decoded:
        if item is None and allow_none:
            converted.append(None)
            continue
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise DBIRasterConflict(
                f"Metadata Raster persistida inválida: {field_name}."
            )
        converted.append(float(item))
    return tuple(converted)


def _overview_tuple(value: str) -> tuple[int, ...]:
    decoded = _decoded_list(value, field_name="overview_levels")
    result: list[int] = []
    for item in decoded:
        if isinstance(item, bool) or not isinstance(item, int) or item <= 1:
            raise DBIRasterConflict(
                "Metadata Raster persistida inválida: overview_levels."
            )
        result.append(item)
    if result != sorted(set(result)):
        raise DBIRasterConflict(
            "Metadata Raster persistida inválida: overview_levels."
        )
    return tuple(result)


class DBIRasterProductReader:
    """Reader interno; la capa HTTP debe autorizar antes de invocarlo."""

    def __init__(self, session: Session, object_store: DBIPrivateObjectStore) -> None:
        if not isinstance(session, Session):
            raise DBIRasterConflict("session debe ser Session.")
        self._session = session
        self._store = object_store

    def _ready_row(
        self,
        *,
        product_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBIRasterProduct:
        if not isinstance(product_id, UUID):
            raise DBIRasterConflict("product_id debe ser UUID.")
        if not isinstance(farm_id, UUID) or not isinstance(plot_id, UUID):
            raise DBIRasterConflict("farm_id y plot_id deben ser UUID.")
        if (
            not isinstance(tenant_ref, str)
            or not tenant_ref
            or tenant_ref.strip() != tenant_ref
        ):
            raise DBIRasterConflict("tenant_ref no es canónico.")
        row = self._session.execute(
            select(DBIRasterProduct).where(
                DBIRasterProduct.id == product_id,
                DBIRasterProduct.tenant_ref == tenant_ref,
                DBIRasterProduct.farm_id == farm_id,
                DBIRasterProduct.plot_id == plot_id,
                DBIRasterProduct.status == "ready",
            )
        ).scalar_one_or_none()
        if row is None:
            raise DBIRasterProductUnavailable("Producto Raster no disponible.")
        return row

    def _verified_row(
        self,
        *,
        product_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBIRasterProduct:
        row = self._ready_row(
            product_id=product_id,
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        address = DBIStoragePolicy.build_address(
            tenant_ref=row.tenant_ref,
            purpose=DBIStoragePurpose.RASTER_PRODUCT,
            object_id=row.id,
        )
        if row.object_key != address.object_key:
            raise DBIRasterConflict("La clave persistida del producto no es canónica.")
        expected = DBIStoragePolicy.build_metadata(
            address=address,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            sha256_hex=row.sha256,
        )
        try:
            record = self._store.stat(address)
        except DBIStorageNotFound as error:
            raise DBIRasterProductUnavailable("Producto Raster no disponible.") from error
        except DBIStorageError as error:
            raise DBIRasterConflict("Storage rechazó el producto Raster.") from error
        if record.state is not DBIStorageObjectState.ACTIVE or record.metadata != expected:
            raise DBIRasterProductUnavailable("Producto Raster no disponible.")
        return row

    def metadata(
        self,
        *,
        product_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBIRasterProductMetadata:
        row = self._verified_row(
            product_id=product_id,
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        transform = _float_tuple(
            row.transform_json,
            field_name="transform",
            expected_length=6,
        )
        bounds = _float_tuple(
            row.bounds_json,
            field_name="bounds",
            expected_length=4,
        )
        nodata = _float_tuple(
            row.nodata_json,
            field_name="nodata",
            expected_length=row.band_count,
            allow_none=True,
        )
        scales = _float_tuple(
            row.scales_json,
            field_name="scales",
            expected_length=row.band_count,
        )
        offsets = _float_tuple(
            row.offsets_json,
            field_name="offsets",
            expected_length=row.band_count,
        )
        return DBIRasterProductMetadata(
            product_id=row.id,
            product_kind=row.product_kind,
            profile_version=row.profile_version,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            sha256=row.sha256,
            crs=row.crs,
            width=row.width,
            height=row.height,
            band_count=row.band_count,
            dtype=row.dtype,
            transform=tuple(transform),  # type: ignore[arg-type]
            bounds=tuple(bounds),  # type: ignore[arg-type]
            nodata=nodata,
            scales=tuple(scales),  # type: ignore[arg-type]
            offsets=tuple(offsets),  # type: ignore[arg-type]
            block_width=row.block_width,
            block_height=row.block_height,
            compression=row.compression,
            overview_levels=_overview_tuple(row.overview_levels_json),
        )

    def read_range(
        self,
        *,
        product_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        start: int,
        end_exclusive: int,
    ) -> DBIRasterRangeSlice:
        row = self._verified_row(
            product_id=product_id,
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end_exclusive, int)
            or isinstance(end_exclusive, bool)
            or start < 0
            or end_exclusive <= start
            or end_exclusive > row.size_bytes
            or end_exclusive - start > MAX_STORAGE_RANGE_BYTES
        ):
            raise DBIRasterConflict("El rango solicitado queda fuera de política.")

        address = DBIStoragePolicy.build_address(
            tenant_ref=row.tenant_ref,
            purpose=DBIStoragePurpose.RASTER_PRODUCT,
            object_id=row.id,
        )
        expected = DBIStoragePolicy.build_metadata(
            address=address,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            sha256_hex=row.sha256,
        )
        try:
            result = self._store.read_range(
                address,
                start=start,
                end_exclusive=end_exclusive,
            )
        except DBIStorageNotFound as error:
            raise DBIRasterProductUnavailable("Producto Raster no disponible.") from error
        except DBIStorageError as error:
            raise DBIRasterConflict("Storage rechazó la lectura parcial Raster.") from error
        if result.record.metadata != expected:
            raise DBIRasterConflict("Storage diverge del producto Raster registrado.")
        if (
            result.start != start
            or result.end_exclusive != end_exclusive
            or len(result.data) != end_exclusive - start
        ):
            raise DBIRasterConflict("Storage devolvió un rango Raster divergente.")
        return DBIRasterRangeSlice(
            product_id=row.id,
            start=start,
            end_exclusive=end_exclusive,
            total_size_bytes=row.size_bytes,
            content_type=row.content_type,
            data=result.data,
        )
