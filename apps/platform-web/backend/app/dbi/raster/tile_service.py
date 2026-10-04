"""Aplicación HTTP-neutral para entregar tiles Raster DBI autorizados.

FastAPI autoriza y resuelve metadata antes de entrar aquí. El renderer pesado es
un puerto aislado: este módulo no importa Rasterio/GDAL, no conoce object keys,
URLs privadas ni rutas locales.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol
from uuid import UUID

from app.dbi.raster.reader import DBIRasterProductMetadata
from app.dbi.raster.tiles import (
    DBIRasterTileCache,
    DBIRasterTileCacheValue,
    DBIRasterTileCoordinate,
    DBIRasterTileStyle,
    build_tile_cache_identity,
)

_TILE_HTTP_PROFILE_VERSION = "tile-http-v1"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class DBIRasterTileRequestError(RuntimeError):
    """La solicitud de visualización no cumple el contrato público."""


class DBIRasterTileIntegrityError(RuntimeError):
    """La metadata o la respuesta del renderer viola el contrato DBI."""


class DBIRasterTileRendererUnavailable(RuntimeError):
    """El renderer aislado no puede atender el tile."""


class DBIRasterTileOutsideExtent(RuntimeError):
    """La coordenada autorizada no intersecta el producto."""


@dataclass(frozen=True, slots=True)
class DBIRasterTileRenderRequest:
    tenant_ref: str
    farm_id: UUID
    plot_id: UUID
    product_id: UUID
    product_kind: str
    product_sha256: str
    source_profile_version: str
    coordinate: DBIRasterTileCoordinate
    style: DBIRasterTileStyle


@dataclass(frozen=True, slots=True)
class DBIRasterTileRenderPayload:
    data: bytes
    content_type: str = "image/png"


class DBIRasterTileRendererPort(Protocol):
    """Puerto server-side hacia el proceso/servicio geoespacial aislado."""

    def render_tile(
        self,
        request: DBIRasterTileRenderRequest,
    ) -> DBIRasterTileRenderPayload:
        ...


@dataclass(frozen=True, slots=True)
class DBIRasterTileDelivery:
    data: bytes
    content_type: str
    etag: str
    cache_hit: bool


def _finite_optional(value: float | None, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DBIRasterTileRequestError(f"{field_name} debe ser numérico.")
    number = float(value)
    if not math.isfinite(number):
        raise DBIRasterTileRequestError(f"{field_name} debe ser finito.")
    return number


def build_public_tile_style(
    metadata: DBIRasterProductMetadata,
    *,
    band: int | None,
    display_min: float | None,
    display_max: float | None,
) -> DBIRasterTileStyle:
    """Convierte parámetros públicos acotados en un estilo versionado seguro."""

    if not isinstance(metadata, DBIRasterProductMetadata):
        raise DBIRasterTileIntegrityError("metadata Raster inválida.")

    if metadata.product_kind == "rgb_visual":
        if band is not None or display_min is not None or display_max is not None:
            raise DBIRasterTileRequestError(
                "rgb_visual no admite band/display_min/display_max."
            )
        if metadata.band_count < 3 or metadata.dtype != "uint8":
            raise DBIRasterTileIntegrityError(
                "rgb_visual persistido no cumple el perfil visual esperado."
            )
        return DBIRasterTileStyle(
            style_id="rgb-natural-v1",
            render_mode="rgb",
            band_indexes=(1, 2, 3),
        )

    if metadata.product_kind == "scientific":
        if not isinstance(band, int) or isinstance(band, bool):
            raise DBIRasterTileRequestError(
                "scientific requiere band entero explícito."
            )
        if band <= 0 or band > metadata.band_count:
            raise DBIRasterTileRequestError(
                "band queda fuera del producto científico."
            )
        minimum = _finite_optional(display_min, field_name="display_min")
        maximum = _finite_optional(display_max, field_name="display_max")
        if minimum is None or maximum is None or maximum <= minimum:
            raise DBIRasterTileRequestError(
                "scientific requiere display_min/display_max válidos."
            )
        return DBIRasterTileStyle(
            style_id="scientific-gray-v1",
            render_mode="single_band",
            band_indexes=(band,),
            display_min=minimum,
            display_max=maximum,
        )

    raise DBIRasterTileIntegrityError("product_kind Raster no soportado.")


class DBIRasterTileApplication:
    """Coordina cache privada y renderer sin resolver almacenamiento en FastAPI."""

    def __init__(
        self,
        renderer: DBIRasterTileRendererPort,
        cache: DBIRasterTileCache,
    ) -> None:
        render_method = getattr(renderer, "render_tile", None)
        if render_method is None or not callable(render_method):
            raise DBIRasterTileRendererUnavailable(
                "renderer Raster no configurado."
            )
        if not isinstance(cache, DBIRasterTileCache):
            raise DBIRasterTileRendererUnavailable(
                "cache Raster no configurada."
            )
        self._renderer = renderer
        self._cache = cache

    def deliver(
        self,
        *,
        metadata: DBIRasterProductMetadata,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        coordinate: DBIRasterTileCoordinate,
        style: DBIRasterTileStyle,
    ) -> DBIRasterTileDelivery:
        identity = build_tile_cache_identity(
            tenant_ref=tenant_ref,
            product_id=metadata.product_id,
            product_sha256=metadata.sha256,
            profile_version=(
                f"{metadata.profile_version}:{_TILE_HTTP_PROFILE_VERSION}"
            ),
            style=style,
            coordinate=coordinate,
        )

        cached = self._cache.get(identity)
        if cached is not None:
            return DBIRasterTileDelivery(
                data=cached.data,
                content_type=cached.content_type,
                etag=f'"tile:{identity.digest}"',
                cache_hit=True,
            )

        request = DBIRasterTileRenderRequest(
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            product_id=metadata.product_id,
            product_kind=metadata.product_kind,
            product_sha256=metadata.sha256,
            source_profile_version=metadata.profile_version,
            coordinate=coordinate,
            style=style,
        )

        try:
            rendered = self._renderer.render_tile(request)
        except (DBIRasterTileOutsideExtent, DBIRasterTileRendererUnavailable):
            raise
        except Exception as error:
            raise DBIRasterTileRendererUnavailable(
                "renderer Raster no pudo entregar el tile."
            ) from error

        if not isinstance(rendered, DBIRasterTileRenderPayload):
            raise DBIRasterTileIntegrityError(
                "renderer Raster devolvió un contrato inválido."
            )
        if (
            rendered.content_type != "image/png"
            or not isinstance(rendered.data, bytes)
            or not rendered.data.startswith(_PNG_SIGNATURE)
        ):
            raise DBIRasterTileIntegrityError(
                "renderer Raster devolvió un PNG inválido."
            )

        value = DBIRasterTileCacheValue(
            data=rendered.data,
            content_type="image/png",
        )
        self._cache.put(identity, value)

        return DBIRasterTileDelivery(
            data=value.data,
            content_type=value.content_type,
            etag=f'"tile:{identity.digest}"',
            cache_hit=False,
        )
