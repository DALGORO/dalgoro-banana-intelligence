"""Extensión S3-compatible para lecturas parciales privadas de COG."""

from __future__ import annotations

from app.dbi.storage_contracts import (
    MAX_STORAGE_RANGE_BYTES,
    DBIStorageAddress,
    DBIStorageIntegrityError,
    DBIStorageRangeRead,
)
from app.dbi.storage_s3 import DBIS3ObjectStore


def _validated_range(*, size_bytes: int, start: int, end_exclusive: int) -> tuple[int, int]:
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end_exclusive, int)
        or isinstance(end_exclusive, bool)
        or start < 0
        or end_exclusive <= start
        or end_exclusive > size_bytes
        or end_exclusive - start > MAX_STORAGE_RANGE_BYTES
    ):
        raise DBIStorageIntegrityError("rango S3 fuera de política.")
    return start, end_exclusive


class DBIRangedS3ObjectStore(DBIS3ObjectStore):
    """Añade Range GET exacto sin alterar escritura/grants del adaptador base."""

    def read_range(
        self,
        address: DBIStorageAddress,
        *,
        start: int,
        end_exclusive: int,
    ) -> DBIStorageRangeRead:
        record = self.stat(address)
        begin, end = _validated_range(
            size_bytes=record.metadata.size_bytes,
            start=start,
            end_exclusive=end_exclusive,
        )
        expected_length = end - begin
        response = self._call(
            "get_object",
            Bucket=self._config.bucket,
            Key=record.metadata.address.object_key,
            Range=f"bytes={begin}-{end - 1}",
        )
        body = response.get("Body")
        read = getattr(body, "read", None)
        if not callable(read):
            raise DBIStorageIntegrityError("El proveedor no devolvió un rango binario.")
        try:
            data = read(expected_length + 1)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        if not isinstance(data, bytes) or len(data) != expected_length:
            raise DBIStorageIntegrityError("El proveedor devolvió un rango truncado o excedido.")

        declared_length = response.get("ContentLength")
        if declared_length is not None and int(declared_length) != expected_length:
            raise DBIStorageIntegrityError("ContentLength del rango S3 es divergente.")
        expected_content_range = (
            f"bytes {begin}-{end - 1}/{record.metadata.size_bytes}"
        )
        declared_content_range = response.get("ContentRange")
        if (
            declared_content_range is not None
            and declared_content_range != expected_content_range
        ):
            raise DBIStorageIntegrityError("ContentRange S3 no coincide con la solicitud.")

        return DBIStorageRangeRead(
            record=record,
            start=begin,
            end_exclusive=end,
            data=data,
        )
