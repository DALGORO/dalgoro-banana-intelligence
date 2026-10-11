"""Smoke geoespacial real para el conversor de archivos del portal DALGORO."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "banana-density"))
from portal_gis_convert_cli import (  # noqa: E402
    PortalGISConversionError, convert_vector,
)


def should_reject(factory, label: str) -> None:
    try:
        factory()
    except PortalGISConversionError:
        return
    raise AssertionError(f"Debe rechazar: {label}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="dbi-gis-smoke-") as root:
        folder = Path(root)
        source = gpd.GeoDataFrame(
            {
                "densidad": [1485],
                "nombre": ["sector norte"],
                "secret_token": ["NO_PUBLICAR"],
            },
            geometry=[Point(-79.8, -3.3)],
            crs="EPSG:4326",
        ).to_crs("EPSG:32717")
        gpkg = folder / "densidad.gpkg"
        source.to_file(gpkg, layer="plantas", driver="GPKG", engine="pyogrio")
        original_sha = hashlib.sha256(gpkg.read_bytes()).hexdigest()

        output, metadata = convert_vector(gpkg, folder / "convertido")
        result = json.loads(output.read_text(encoding="utf-8"))
        feature = result["features"][0]
        lon, lat = feature["geometry"]["coordinates"]
        assert abs(lon + 79.8) < 1e-5 and abs(lat + 3.3) < 1e-5
        assert feature["properties"]["densidad"] == 1485
        assert feature["properties"]["nombre"] == "sector norte"
        assert "secret_token" not in feature["properties"]
        manifest = json.loads(metadata.read_text(encoding="utf-8"))
        assert manifest["source_sha256"] == original_sha
        assert manifest["captured_at"] is None
        assert manifest["output_crs"] == "EPSG:4326"
        assert manifest["feature_count"] == 1
        assert hashlib.sha256(gpkg.read_bytes()).hexdigest() == original_sha
        output_again, _ = convert_vector(gpkg, folder / "convertido")
        assert output_again == output

        shape_dir = folder / "shp"
        shape_dir.mkdir()
        source.to_file(shape_dir / "plantas.shp", driver="ESRI Shapefile", engine="pyogrio")
        zip_path = folder / "plantas.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(shape_dir.iterdir()):
                archive.write(path, arcname=path.name)
        derived_shape, _ = convert_vector(zip_path, folder / "convertido_shp")
        shape_geojson = json.loads(derived_shape.read_text(encoding="utf-8"))
        assert shape_geojson["features"][0]["geometry"]["type"] == "Point"

        invalid = folder / "invalid.gpkg"
        invalid.write_bytes(b"not a sqlite package")
        should_reject(lambda: convert_vector(invalid, folder / "invalid_output"), "gpkg no válido")

        traversal = folder / "traversal.zip"
        with zipfile.ZipFile(traversal, "w") as archive:
            for sidecar in ("shp", "shx", "dbf", "prj"):
                archive.writestr(f"../escape.{sidecar}", "contenido")
        should_reject(lambda: convert_vector(traversal, folder / "escaped"), "zip traversal")
        assert not (folder / "escape.shp").exists()

        shape_without_prj = folder / "no-prj.zip"
        with zipfile.ZipFile(shape_without_prj, "w") as archive:
            for path in shape_dir.iterdir():
                if path.suffix.lower() != ".prj":
                    archive.write(path, path.name)
        should_reject(lambda: convert_vector(shape_without_prj, folder / "no_prj_out"), "crs ausente")

    print("Conversión GIS DBI GPKG/SHP ZIP: lectura, CRS, huella y defensas aprobadas.")


if __name__ == "__main__":
    main()
