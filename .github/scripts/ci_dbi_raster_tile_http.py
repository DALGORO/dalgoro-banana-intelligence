"""CI offline para entrega HTTP autorizada de tiles Raster DBI."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_raster_tile_http.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-raster-tile-http-secret")

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.api.v1 import dbi_raster_products, get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.raster.reader import DBIRasterProductMetadata  # noqa: E402
from app.dbi.raster.tile_service import (  # noqa: E402
    DBIRasterTileOutsideExtent,
    DBIRasterTileRenderPayload,
)
from app.dbi.raster.tiles import DBIRasterTileCache  # noqa: E402

ORG = "organization-raster-tile-http"
TENANT = "tenant-raster-tile-http"
FARM = UUID("41000000-0000-4000-8000-000000000041")
PLOT = UUID("42000000-0000-4000-8000-000000000042")
PRODUCT = UUID("43000000-0000-4000-8000-000000000043")
SHA = "b" * 64
PNG = b"\x89PNG\r\n\x1a\nDBI-TILE-CI"


def _context(*, authorized: bool = True) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="principal-raster-tile-http",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG}),
        farm_scopes=(
            frozenset({DBIFarmScope(ORG, FARM)})
            if authorized
            else frozenset()
        ),
        plot_scopes=(
            frozenset({DBIPlotScope(ORG, FARM, PLOT)})
            if authorized
            else frozenset()
        ),
        permissions=frozenset({DBIPermission.READ}),
    )


def _metadata(*, product_kind: str = "rgb_visual") -> DBIRasterProductMetadata:
    scientific = product_kind == "scientific"
    return DBIRasterProductMetadata(
        product_id=PRODUCT,
        product_kind=product_kind,
        profile_version="cog_v1",
        content_type="image/tiff",
        size_bytes=20_000_000,
        sha256=SHA,
        crs="EPSG:32717",
        width=1024,
        height=768,
        band_count=1 if scientific else 3,
        dtype="float32" if scientific else "uint8",
        transform=(0.03, 0.0, 620000.0, 0.0, -0.03, 9640000.0),
        bounds=(620000.0, 9639976.96, 620030.72, 9640000.0),
        nodata=(-9999.0,) if scientific else (None, None, None),
        scales=(1.0,) if scientific else (1.0, 1.0, 1.0),
        offsets=(0.0,) if scientific else (0.0, 0.0, 0.0),
        block_width=512,
        block_height=512,
        compression="deflate",
        overview_levels=(2, 4),
    )


class _FakeReader:
    def __init__(self, *, product_kind: str = "rgb_visual") -> None:
        self.product_kind = product_kind
        self.metadata_calls = 0

    def metadata(self, **kwargs):
        assert kwargs == {
            "product_id": PRODUCT,
            "tenant_ref": TENANT,
            "farm_id": FARM,
            "plot_id": PLOT,
        }
        self.metadata_calls += 1
        return _metadata(product_kind=self.product_kind)


class _FakeRenderer:
    def __init__(self) -> None:
        self.requests = []
        self.outside = False

    def render_tile(self, request):
        self.requests.append(request)
        if self.outside:
            raise DBIRasterTileOutsideExtent("outside")
        return DBIRasterTileRenderPayload(data=PNG)


def _request(renderer=None, cache=None):
    state = SimpleNamespace()
    if renderer is not None:
        state.dbi_raster_tile_renderer = renderer
    if cache is not None:
        state.dbi_raster_tile_cache = cache
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _call(
    *,
    request,
    context=None,
    band=None,
    display_min=None,
    display_max=None,
):
    return dbi_raster_products.get_raster_product_tile(
        ORG,
        FARM,
        PLOT,
        PRODUCT,
        14,
        4558,
        8344,
        request,
        object(),
        context or _context(),
        object(),
        band,
        display_min,
        display_max,
    )


def validate_route_registration() -> None:
    routes = {
        (route.path, method)
        for route in get_api_router().routes
        if "raster-products" in route.path
        for method in route.methods
    }
    path = (
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/"
        "{plot_id}/raster-products/{product_id}/tiles/{z}/{x}/{y}.png"
    )
    assert (path, "GET") in routes


def validate_rgb_delivery_and_cache() -> None:
    reader = _FakeReader()
    renderer = _FakeRenderer()
    cache = DBIRasterTileCache(
        max_entries=8,
        max_bytes=1024 * 1024,
        max_tile_bytes=128 * 1024,
        ttl_seconds=60,
    )
    request = _request(renderer, cache)

    with patch.object(dbi_raster_products, "_reader", return_value=reader):
        first = _call(request=request)
        second = _call(request=request)

    assert first.status_code == 200
    assert first.body == PNG
    assert first.headers["content-type"].startswith("image/png")
    assert first.headers["x-dbi-tile-cache"] == "miss"
    assert second.headers["x-dbi-tile-cache"] == "hit"
    assert first.headers["etag"] == second.headers["etag"]
    assert first.headers["cache-control"] == "private, max-age=60"
    assert len(renderer.requests) == 1
    render_request = renderer.requests[0]
    assert render_request.tenant_ref == TENANT
    assert render_request.product_id == PRODUCT
    assert render_request.style.render_mode == "rgb"
    assert render_request.style.band_indexes == (1, 2, 3)
    assert reader.metadata_calls == 2


def validate_scientific_style_and_validation() -> None:
    reader = _FakeReader(product_kind="scientific")
    renderer = _FakeRenderer()
    cache = DBIRasterTileCache()
    request = _request(renderer, cache)

    with patch.object(dbi_raster_products, "_reader", return_value=reader):
        response = _call(
            request=request,
            band=1,
            display_min=0.0,
            display_max=1.0,
        )

    assert response.status_code == 200
    assert renderer.requests[0].style.render_mode == "single_band"
    assert renderer.requests[0].style.band_indexes == (1,)
    assert renderer.requests[0].style.display_min == 0.0
    assert renderer.requests[0].style.display_max == 1.0

    renderer_invalid = _FakeRenderer()
    invalid_request = _request(renderer_invalid, DBIRasterTileCache())
    with patch.object(dbi_raster_products, "_reader", return_value=reader):
        try:
            _call(request=invalid_request, band=1)
        except HTTPException as error:
            assert error.status_code == 422
        else:
            raise AssertionError("Scientific sin stretch debía fallar.")
    assert renderer_invalid.requests == []


def validate_authorization_precedes_resolution() -> None:
    reader_touched = False
    runtime_touched = False

    def forbidden_reader(*args, **kwargs):
        nonlocal reader_touched
        reader_touched = True
        raise AssertionError("No debe resolverse metadata sin autorización.")

    class _ForbiddenRequest:
        @property
        def app(self):
            nonlocal runtime_touched
            runtime_touched = True
            raise AssertionError("No debe resolverse runtime sin autorización.")

    with patch.object(dbi_raster_products, "_reader", side_effect=forbidden_reader):
        try:
            _call(
                request=_ForbiddenRequest(),
                context=_context(authorized=False),
            )
        except HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError("Scope no autorizado debía ocultarse.")

    assert reader_touched is False
    assert runtime_touched is False


def validate_renderer_fail_closed_and_outside_extent() -> None:
    reader = _FakeReader()
    cache = DBIRasterTileCache()

    with patch.object(dbi_raster_products, "_reader", return_value=reader):
        try:
            _call(request=_request(cache=cache))
        except HTTPException as error:
            assert error.status_code == 503
        else:
            raise AssertionError("Renderer ausente debía responder 503.")

    renderer = _FakeRenderer()
    renderer.outside = True
    with patch.object(dbi_raster_products, "_reader", return_value=reader):
        try:
            _call(request=_request(renderer, DBIRasterTileCache()))
        except HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError("Tile fuera de extent debía ocultarse.")


def validate_static_boundaries() -> None:
    route = (
        BACKEND / "app" / "api" / "v1" / "dbi_raster_products.py"
    ).read_text(encoding="utf-8").lower()
    service = (
        BACKEND / "app" / "dbi" / "raster" / "tile_service.py"
    ).read_text(encoding="utf-8").lower()
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8").lower()

    assert "dbiauthorizationpolicy.require_plot" in route
    assert "x-dbi-tile-cache" in route
    assert "dbi_raster_tile_cache = dbirastertilecache()" in main

    for source in (route, service):
        for forbidden in (
            "import rasterio",
            "from rasterio",
            "import gdal",
            "from osgeo",
            "presigned",
            "signed_url",
        ):
            assert forbidden not in source


def main() -> None:
    validate_route_registration()
    validate_rgb_delivery_and_cache()
    validate_scientific_style_and_validation()
    validate_authorization_precedes_resolution()
    validate_renderer_fail_closed_and_outside_extent()
    validate_static_boundaries()
    print(
        "DBI-RASTER-TILE-001 HTTP aprobado: autorización previa, PNG privado, "
        "cache hit/miss, científico acotado y renderer fail-closed."
    )


if __name__ == "__main__":
    main()
