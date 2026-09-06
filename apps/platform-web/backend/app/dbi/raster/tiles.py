"""Contratos puros y caché privada regenerable para tiles Raster DBI.

La autorización ocurre antes de construir/consultar estas claves. Este módulo no
abre COG, no conoce object keys ni URLs y no convierte la caché en autoridad.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
import math
import re
import time
from typing import Callable, Literal
from uuid import UUID

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_STYLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_ZOOM = 22


class DBIRasterTileError(RuntimeError):
    """El pedido o la caché de tile no cumple la política DBI."""


@dataclass(frozen=True, slots=True)
class DBIRasterTileCoordinate:
    z: int
    x: int
    y: int

    def __post_init__(self) -> None:
        if not isinstance(self.z, int) or isinstance(self.z, bool):
            raise DBIRasterTileError("z debe ser entero.")
        if self.z < 0 or self.z > _MAX_ZOOM:
            raise DBIRasterTileError("z queda fuera de la política DBI.")
        limit = 1 << self.z
        for name, value in (("x", self.x), ("y", self.y)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise DBIRasterTileError(f"{name} debe ser entero.")
            if value < 0 or value >= limit:
                raise DBIRasterTileError(f"{name} queda fuera del rango para z.")


@dataclass(frozen=True, slots=True)
class DBIRasterTileStyle:
    """Estilo visual versionado; nunca sustituye los valores científicos."""

    style_id: str
    render_mode: Literal["rgb", "single_band"]
    output_format: Literal["png"] = "png"
    band_indexes: tuple[int, ...] = (1, 2, 3)
    display_min: float | None = None
    display_max: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.style_id, str) or not _STYLE_RE.fullmatch(self.style_id):
            raise DBIRasterTileError("style_id no es canónico.")
        if self.output_format != "png":
            raise DBIRasterTileError("Este perfil inicial sólo admite PNG.")
        if self.render_mode == "rgb":
            if len(self.band_indexes) != 3 or self.display_min is not None or self.display_max is not None:
                raise DBIRasterTileError("rgb requiere tres bandas y no usa stretch científico.")
        elif self.render_mode == "single_band":
            if len(self.band_indexes) != 1:
                raise DBIRasterTileError("single_band requiere exactamente una banda.")
            if self.display_min is None or self.display_max is None:
                raise DBIRasterTileError("single_band requiere display_min/display_max explícitos.")
            if (
                not isinstance(self.display_min, (int, float))
                or isinstance(self.display_min, bool)
                or not isinstance(self.display_max, (int, float))
                or isinstance(self.display_max, bool)
                or not math.isfinite(float(self.display_min))
                or not math.isfinite(float(self.display_max))
                or float(self.display_max) <= float(self.display_min)
            ):
                raise DBIRasterTileError("El stretch científico no es válido.")
        else:
            raise DBIRasterTileError("render_mode no soportado.")
        if any(
            not isinstance(index, int) or isinstance(index, bool) or index <= 0
            for index in self.band_indexes
        ):
            raise DBIRasterTileError("band_indexes debe contener índices positivos.")

    @property
    def fingerprint(self) -> str:
        material = (
            f"dbi:raster-tile-style:v1:{self.style_id}:{self.render_mode}:"
            f"{self.output_format}:{','.join(str(value) for value in self.band_indexes)}:"
            f"{self.display_min!r}:{self.display_max!r}"
        )
        return sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DBIRasterTileCacheIdentity:
    """Identidad opaca de caché; el digest evita serializar tenant en la key."""

    digest: str
    product_id: UUID
    product_sha256: str
    profile_version: str
    style_fingerprint: str
    coordinate: DBIRasterTileCoordinate


def build_tile_cache_identity(
    *,
    tenant_ref: str,
    product_id: UUID,
    product_sha256: str,
    profile_version: str,
    style: DBIRasterTileStyle,
    coordinate: DBIRasterTileCoordinate,
) -> DBIRasterTileCacheIdentity:
    if (
        not isinstance(tenant_ref, str)
        or not tenant_ref
        or tenant_ref != tenant_ref.strip()
        or "*" in tenant_ref
        or any(ord(char) < 32 or ord(char) == 127 for char in tenant_ref)
    ):
        raise DBIRasterTileError("tenant_ref no es canónico.")
    if not isinstance(product_id, UUID):
        raise DBIRasterTileError("product_id debe ser UUID.")
    if not isinstance(product_sha256, str) or not _SHA_RE.fullmatch(product_sha256):
        raise DBIRasterTileError("product_sha256 debe ser SHA-256 canónico.")
    if not isinstance(profile_version, str) or not _STYLE_RE.fullmatch(profile_version):
        raise DBIRasterTileError("profile_version no es canónico.")
    if not isinstance(style, DBIRasterTileStyle):
        raise DBIRasterTileError("style debe ser DBIRasterTileStyle.")
    if not isinstance(coordinate, DBIRasterTileCoordinate):
        raise DBIRasterTileError("coordinate debe ser DBIRasterTileCoordinate.")

    material = (
        f"dbi:raster-tile-cache:v1:{tenant_ref}:{product_id}:{product_sha256}:"
        f"{profile_version}:{style.fingerprint}:{coordinate.z}:"
        f"{coordinate.x}:{coordinate.y}"
    )
    return DBIRasterTileCacheIdentity(
        digest=sha256(material.encode("utf-8")).hexdigest(),
        product_id=product_id,
        product_sha256=product_sha256,
        profile_version=profile_version,
        style_fingerprint=style.fingerprint,
        coordinate=coordinate,
    )


@dataclass(frozen=True, slots=True)
class DBIRasterTileCacheValue:
    data: bytes
    content_type: Literal["image/png"] = "image/png"

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise DBIRasterTileError("El tile cacheado debe contener bytes.")
        if self.content_type != "image/png":
            raise DBIRasterTileError("content_type no soportado por este perfil.")


@dataclass(frozen=True, slots=True)
class DBIRasterTileCacheStats:
    hits: int
    misses: int
    expired: int
    evictions: int
    entries: int
    bytes_used: int


@dataclass(slots=True)
class _CacheEntry:
    identity: DBIRasterTileCacheIdentity
    value: DBIRasterTileCacheValue
    expires_at: float


class DBIRasterTileCache:
    """LRU/TTL privado, acotado e invalidable. Totalmente regenerable."""

    def __init__(
        self,
        *,
        max_entries: int = 512,
        max_bytes: int = 32 * 1024 * 1024,
        max_tile_bytes: int = 512 * 1024,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for name, value in (
            ("max_entries", max_entries),
            ("max_bytes", max_bytes),
            ("max_tile_bytes", max_tile_bytes),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise DBIRasterTileError(f"{name} debe ser entero positivo.")
        if max_tile_bytes > max_bytes:
            raise DBIRasterTileError("max_tile_bytes no puede superar max_bytes.")
        if (
            not isinstance(ttl_seconds, (int, float))
            or isinstance(ttl_seconds, bool)
            or not math.isfinite(float(ttl_seconds))
            or float(ttl_seconds) <= 0
        ):
            raise DBIRasterTileError("ttl_seconds debe ser positivo y finito.")
        if not callable(clock):
            raise DBIRasterTileError("clock debe ser callable.")

        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._max_tile_bytes = max_tile_bytes
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._bytes_used = 0
        self._hits = 0
        self._misses = 0
        self._expired = 0
        self._evictions = 0

    def get(self, identity: DBIRasterTileCacheIdentity) -> DBIRasterTileCacheValue | None:
        if not isinstance(identity, DBIRasterTileCacheIdentity):
            raise DBIRasterTileError("identity inválida.")
        entry = self._entries.get(identity.digest)
        if entry is None:
            self._misses += 1
            return None
        if entry.identity != identity:
            raise DBIRasterTileError("Colisión de identidad de caché detectada.")
        if self._clock() >= entry.expires_at:
            self._remove(identity.digest)
            self._expired += 1
            self._misses += 1
            return None
        self._entries.move_to_end(identity.digest)
        self._hits += 1
        return entry.value

    def put(
        self,
        identity: DBIRasterTileCacheIdentity,
        value: DBIRasterTileCacheValue,
    ) -> None:
        if not isinstance(identity, DBIRasterTileCacheIdentity):
            raise DBIRasterTileError("identity inválida.")
        if not isinstance(value, DBIRasterTileCacheValue):
            raise DBIRasterTileError("value inválido.")
        size = len(value.data)
        if size > self._max_tile_bytes:
            raise DBIRasterTileError("El tile excede max_tile_bytes.")
        existing = self._entries.get(identity.digest)
        if existing is not None:
            if existing.identity != identity:
                raise DBIRasterTileError("Colisión de identidad de caché detectada.")
            self._remove(identity.digest)

        self._entries[identity.digest] = _CacheEntry(
            identity=identity,
            value=value,
            expires_at=self._clock() + self._ttl_seconds,
        )
        self._bytes_used += size
        self._entries.move_to_end(identity.digest)
        self._evict_to_limits()

    def invalidate_product(self, product_id: UUID) -> int:
        if not isinstance(product_id, UUID):
            raise DBIRasterTileError("product_id debe ser UUID.")
        keys = [
            key
            for key, entry in self._entries.items()
            if entry.identity.product_id == product_id
        ]
        for key in keys:
            self._remove(key)
        return len(keys)

    def stats(self) -> DBIRasterTileCacheStats:
        return DBIRasterTileCacheStats(
            hits=self._hits,
            misses=self._misses,
            expired=self._expired,
            evictions=self._evictions,
            entries=len(self._entries),
            bytes_used=self._bytes_used,
        )

    def _remove(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes_used -= len(entry.value.data)

    def _evict_to_limits(self) -> None:
        while len(self._entries) > self._max_entries or self._bytes_used > self._max_bytes:
            key, entry = self._entries.popitem(last=False)
            self._bytes_used -= len(entry.value.data)
            self._evictions += 1
