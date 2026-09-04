"""CLI local de DBI-RASTER-001 para validar la primera ortofoto real.

Uso desde ``services/banana-density``::

    python flight_test_cog.py ORTOFOTO.tif salida/ortofoto.cog.tif

Este comando es una herramienta operativa local/worker-side. No acepta URLs,
buckets ni credenciales y no sustituye la API autorizada DBI.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from banana_analyzer.raster_cog import (  # noqa: E402
    RasterCOGError,
    generate_validated_cog,
    write_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera y valida un COG DBI a partir de un GeoTIFF local.",
    )
    parser.add_argument("source", help="GeoTIFF/ortomosaico local de entrada")
    parser.add_argument("cog", help="COG TIFF nuevo de salida")
    parser.add_argument(
        "--product-kind",
        choices=("rgb_visual", "scientific"),
        default="rgb_visual",
    )
    parser.add_argument("--profile-version", default="cog_v1")
    parser.add_argument(
        "--manifest",
        default=None,
        help="Ruta opcional del manifiesto JSON; por defecto <cog>.manifest.json",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest_path = (
        Path(args.manifest)
        if args.manifest
        else Path(str(args.cog) + ".manifest.json")
    )
    try:
        manifest = generate_validated_cog(
            args.source,
            args.cog,
            product_kind=args.product_kind,
            profile_version=args.profile_version,
        )
        written_manifest = write_manifest(manifest, manifest_path)
    except RasterCOGError as error:
        print(f"ERROR DBI Raster: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"ERROR DBI Raster inesperado: {error.__class__.__name__}", file=sys.stderr)
        return 3

    summary = {
        "status": "validated",
        "schema_version": manifest.schema_version,
        "product_kind": manifest.product_kind,
        "source_sha256": manifest.source_sha256,
        "cog_sha256": manifest.cog_sha256,
        "cog_size_bytes": manifest.cog_size_bytes,
        "crs": manifest.descriptor.crs,
        "width": manifest.descriptor.width,
        "height": manifest.descriptor.height,
        "bands": manifest.descriptor.band_count,
        "overviews": manifest.descriptor.overview_levels,
        "manifest": written_manifest.name,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
