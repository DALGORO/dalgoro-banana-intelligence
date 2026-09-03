"""Valida contratos puros y fronteras de DBI-RASTER-001 sin base ni red."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.raster.contracts import (  # noqa: E402
    DBIRasterConflict,
    DBIRasterProductKind,
    DBIRasterSourceKind,
    raster_product_id,
)
from app.dbi.raster.manifest import prepare_candidate_from_manifest  # noqa: E402

SOURCE_REF = UUID("11111111-1111-4111-8111-111111111111")
SOURCE_SHA = "a" * 64
COG_SHA = "b" * 64


def _manifest(**overrides) -> str:
    payload = {
        "schema_version": "dbi-raster-flight-test.v1",
        "product_kind": "rgb_visual",
        "profile_version": "cog_v1",
        "generator": "rasterio-1.4.4:gdal-3.10.3",
        "source_name": "ortofoto.tif",
        "source_size_bytes": 10_000,
        "source_sha256": SOURCE_SHA,
        "cog_name": "ortofoto.cog.tif",
        "cog_size_bytes": 8_000,
        "cog_sha256": COG_SHA,
        "descriptor": {
            "width": 1024,
            "height": 768,
            "band_count": 3,
            "dtypes": ["uint8", "uint8", "uint8"],
            "crs": "EPSG:32717",
            "transform": [0.03, 0.0, 620000.0, 0.0, -0.03, 9640000.0],
            "bounds": [620000.0, 9639976.96, 620030.72, 9640000.0],
            "nodata": [None, None, None],
            "scales": [1.0, 1.0, 1.0],
            "offsets": [0.0, 0.0, 0.0],
            "tiled": True,
            "block_shapes": [[512, 512], [512, 512], [512, 512]],
            "compression": "deflate",
            "overview_levels": [2],
        },
    }
    payload.update(overrides)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _raises(callback) -> None:
    try:
        callback()
    except DBIRasterConflict:
        return
    raise AssertionError("Se esperaba DBIRasterConflict.")


def validate_manifest_and_identity() -> None:
    candidate = prepare_candidate_from_manifest(
        _manifest(),
        source_kind=DBIRasterSourceKind.INPUT_ASSET,
        source_ref=SOURCE_REF,
    )
    expected = raster_product_id(
        source_kind=DBIRasterSourceKind.INPUT_ASSET,
        source_ref=SOURCE_REF,
        source_sha256=SOURCE_SHA,
        product_kind=DBIRasterProductKind.RGB_VISUAL,
        profile_version="cog_v1",
    )
    assert candidate.object_id == expected
    assert candidate.object_id == prepare_candidate_from_manifest(
        _manifest(),
        source_kind=DBIRasterSourceKind.INPUT_ASSET,
        source_ref=SOURCE_REF,
    ).object_id
    assert candidate.block_width == 512 and candidate.block_height == 512
    assert candidate.compression == "deflate"
    assert candidate.overview_levels == (2,)

    _raises(
        lambda: prepare_candidate_from_manifest(
            _manifest(source_name="/tmp/ortofoto.tif"),
            source_kind=DBIRasterSourceKind.INPUT_ASSET,
            source_ref=SOURCE_REF,
        )
    )
    payload = json.loads(_manifest())
    payload["presigned_url"] = "https://forbidden.invalid/cog"
    _raises(
        lambda: prepare_candidate_from_manifest(
            json.dumps(payload),
            source_kind=DBIRasterSourceKind.INPUT_ASSET,
            source_ref=SOURCE_REF,
        )
    )
    payload = json.loads(_manifest())
    payload["descriptor"]["tiled"] = False
    _raises(
        lambda: prepare_candidate_from_manifest(
            json.dumps(payload),
            source_kind=DBIRasterSourceKind.INPUT_ASSET,
            source_ref=SOURCE_REF,
        )
    )


def validate_boundaries() -> None:
    service = (BACKEND / "app" / "dbi" / "raster" / "service.py").read_text(
        encoding="utf-8"
    ).lower()
    repository = (BACKEND / "app" / "dbi" / "raster" / "repository.py").read_text(
        encoding="utf-8"
    ).lower()
    for forbidden in (
        ".commit(",
        ".rollback(",
        "rasterio",
        "subprocess",
        "requests.",
        "httpx.",
        "open_read(",
        "copy_to(",
    ):
        assert forbidden not in service
        assert forbidden not in repository
    assert ".stat(" in service
    assert "dbistoragepurpose.raster_product" in service
    assert "asset.status != \"verified\"" in service
    assert "on_conflict_do_nothing" in repository


def main() -> None:
    validate_manifest_and_identity()
    validate_boundaries()
    print("DBI-RASTER-001 contratos aprobados: identidad, manifiesto y fronteras cerradas.")


if __name__ == "__main__":
    main()
