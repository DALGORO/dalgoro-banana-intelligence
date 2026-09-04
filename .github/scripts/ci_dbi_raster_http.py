"""Valida la frontera HTTP mínima de productos Raster sin DB ni red."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.api.v1 import dbi_raster_products, get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.raster.reader import (  # noqa: E402
    DBIRasterProductMetadata,
    DBIRasterRangeSlice,
)
from app.dbi.storage_contracts import MAX_STORAGE_RANGE_BYTES  # noqa: E402

ORG = "organization-raster-http"
TENANT = "tenant-raster-http"
FARM = UUID("10000000-0000-4000-8000-000000000001")
PLOT = UUID("20000000-0000-4000-8000-000000000001")
PRODUCT = UUID("30000000-0000-4000-8000-000000000001")
SHA = "a" * 64


def _context(*, authorized: bool = True) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="principal-raster-http",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset(),
        plot_scopes=(
            frozenset({DBIPlotScope(ORG, FARM, PLOT)})
            if authorized
            else frozenset()
        ),
        permissions=frozenset({DBIPermission.READ}),
    )


def _metadata() -> DBIRasterProductMetadata:
    return DBIRasterProductMetadata(
        product_id=PRODUCT,
        product_kind="rgb_visual",
        profile_version="cog_v1",
        content_type="image/tiff",
        size_bytes=20_000_000,
        sha256=SHA,
        crs="EPSG:32717",
        width=1024,
        height=768,
        band_count=3,
        dtype="uint8",
        transform=(0.03, 0.0, 620000.0, 0.0, -0.03, 9640000.0),
        bounds=(620000.0, 9639976.96, 620030.72, 9640000.0),
        nodata=(None, None, None),
        scales=(1.0, 1.0, 1.0),
        offsets=(0.0, 0.0, 0.0),
        block_width=512,
        block_height=512,
        compression="deflate",
        overview_levels=(2, 4),
    )


class _FakeReader:
    def __init__(self) -> None:
        self.metadata_calls = 0
        self.range_calls: list[tuple[int, int]] = []

    def metadata(self, **kwargs):
        assert kwargs == {
            "product_id": PRODUCT,
            "tenant_ref": TENANT,
            "farm_id": FARM,
            "plot_id": PLOT,
        }
        self.metadata_calls += 1
        return _metadata()

    def read_range(self, **kwargs):
        start = kwargs.pop("start")
        end_exclusive = kwargs.pop("end_exclusive")
        assert kwargs == {
            "product_id": PRODUCT,
            "tenant_ref": TENANT,
            "farm_id": FARM,
            "plot_id": PLOT,
        }
        self.range_calls.append((start, end_exclusive))
        return DBIRasterRangeSlice(
            product_id=PRODUCT,
            start=start,
            end_exclusive=end_exclusive,
            total_size_bytes=_metadata().size_bytes,
            content_type="image/tiff",
            data=b"x" * (end_exclusive - start),
        )


def _raises_value(value: str | None, total_size: int) -> None:
    try:
        dbi_raster_products.parse_single_http_range(
            value,
            total_size=total_size,
        )
    except ValueError:
        return
    raise AssertionError("El Range inválido debía ser rechazado.")


def validate_range_parser() -> None:
    assert dbi_raster_products.parse_single_http_range(
        "bytes=10-19", total_size=100
    ) == (10, 20)
    assert dbi_raster_products.parse_single_http_range(
        "bytes=90-", total_size=100
    ) == (90, 100)
    assert dbi_raster_products.parse_single_http_range(
        "bytes=-10", total_size=100
    ) == (90, 100)
    assert dbi_raster_products.parse_single_http_range(
        "bytes=-500", total_size=100
    ) == (0, 100)

    for invalid in (
        None,
        "",
        "items=0-1",
        "bytes=",
        "bytes=1-2,4-5",
        "bytes=-0",
        "bytes=20-10",
        "bytes=100-100",
        "bytes=1-a",
        "bytes= 1-2",
    ):
        _raises_value(invalid, 100)

    _raises_value(f"bytes=0-{MAX_STORAGE_RANGE_BYTES}", 20_000_000)
    assert dbi_raster_products.parse_single_http_range(
        f"bytes=0-{MAX_STORAGE_RANGE_BYTES - 1}",
        total_size=20_000_000,
    ) == (0, MAX_STORAGE_RANGE_BYTES)


def validate_router_and_safe_metadata() -> None:
    routes = {
        (route.path, method)
        for route in get_api_router().routes
        if "raster-products" in route.path
        for method in route.methods
    }
    metadata_path = (
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/"
        "{plot_id}/raster-products/{product_id}"
    )
    assert (metadata_path, "GET") in routes
    assert (metadata_path + "/content", "GET") in routes

    fake = _FakeReader()
    with patch.object(dbi_raster_products, "_reader", return_value=fake):
        response = dbi_raster_products.get_raster_product_metadata(
            ORG,
            FARM,
            PLOT,
            PRODUCT,
            object(),
            _context(),
            object(),
        )
    payload = response.model_dump(mode="json")
    assert payload["product_id"] == str(PRODUCT)
    assert payload["overview_levels"] == [2, 4]
    for forbidden in ("object_key", "bucket", "url", "local_path", "credentials"):
        assert forbidden not in payload
    assert fake.metadata_calls == 1


def validate_partial_response() -> None:
    fake = _FakeReader()
    with patch.object(dbi_raster_products, "_reader", return_value=fake):
        response = dbi_raster_products.get_raster_product_range(
            ORG,
            FARM,
            PLOT,
            PRODUCT,
            object(),
            _context(),
            object(),
            "bytes=1024-2047",
        )
    assert response.status_code == 206
    assert response.body == b"x" * 1024
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 1024-2047/20000000"
    assert response.headers["content-length"] == "1024"
    assert response.headers["etag"] == f'"sha256:{SHA}"'
    assert response.headers["cache-control"] == "private, max-age=60"
    assert fake.range_calls == [(1024, 2048)]


def validate_authorization_precedes_resolution() -> None:
    touched = False

    def forbidden_reader(*args, **kwargs):
        nonlocal touched
        touched = True
        raise AssertionError("No se debe resolver Raster antes de autorización.")

    with patch.object(dbi_raster_products, "_reader", side_effect=forbidden_reader):
        try:
            dbi_raster_products.get_raster_product_metadata(
                ORG,
                FARM,
                PLOT,
                PRODUCT,
                object(),
                _context(authorized=False),
                object(),
            )
        except HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError("El lote no autorizado debía ocultarse.")
    assert touched is False


def validate_static_boundaries() -> None:
    source = (
        BACKEND / "app" / "api" / "v1" / "dbi_raster_products.py"
    ).read_text(encoding="utf-8").lower()
    assert "max_storage_range_bytes" in source
    assert "206_partial_content" in source
    assert "content-range" in source
    assert "dbiauthorizationpolicy.require_plot" in source
    for forbidden in (
        "rasterio",
        "gdal",
        "open_read(",
        "copy_to(",
        "object_key",
        "presigned",
        "signed_url",
        "bucket",
    ):
        assert forbidden not in source


def main() -> None:
    validate_range_parser()
    validate_router_and_safe_metadata()
    validate_partial_response()
    validate_authorization_precedes_resolution()
    validate_static_boundaries()
    print("DBI-RASTER-001 HTTP aprobado: metadata segura, autorización y Range acotado.")


if __name__ == "__main__":
    main()
