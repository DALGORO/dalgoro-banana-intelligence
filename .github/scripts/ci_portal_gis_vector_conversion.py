"""CI del conversor offline GPKG/ZIP SHP para el portal, sin datos privados."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import geopandas as gpd
from shapely.geometry import Point, Polygon
from banana_analyzer.portal_vector_convert import (
    PortalConversionError, convert_vector_for_portal,
)


def expect_error(operation, message: str) -> None:
    try:
        operation()
    except PortalConversionError as error:
        assert message.lower() in str(error).lower(), str(error)
        return
    raise AssertionError("La conversión insegura debería haberse rechazado.")


def check_conversion() -> None:
    with TemporaryDirectory(prefix="ci-dbi-portal-vector-") as tmp:
        root = Path(tmp)
        gpkg = root / "valid.gpkg"
        input_data = gpd.GeoDataFrame(
            {
                "densidad": [1423, 1532],
                "categoria": ["Media", "Alta"],
                "object_key": ["private/a", "private/b"],
            },
            geometry=[Point(-79.8, -3.3), Point(-79.81, -3.31)],
            crs="EPSG:4326",
        )
        input_data.to_file(gpkg, layer="plantas", driver="GPKG", engine="pyogrio")
        out = root / "converted.geojson"
        result = convert_vector_for_portal(gpkg, out)
        data = json.loads(out.read_text("utf-8"))
        assert result["feature_count"] == 2
        assert result["input_format"] == "geopackage"
        assert result["original_crs"] == "EPSG:4326"
        assert data["type"] == "FeatureCollection"
        assert data["features"][0]["properties"] == {"densidad": 1423, "categoria": "Media"}
        assert len(result["source_sha256"]) == 64
        assert result["source_sha256"] == hashlib.sha256(gpkg.read_bytes()).hexdigest()
        assert result["output_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
        assert out.with_suffix(".manifest.json").is_file()
        expect_error(lambda: convert_vector_for_portal(gpkg, out), "ya existen")

        # GPKG multicapas obliga a seleccionar explícitamente para evitar error humano.
        input_data.to_file(gpkg, layer="densidad", driver="GPKG", engine="pyogrio", mode="a")
        expect_error(
            lambda: convert_vector_for_portal(gpkg, root / "missing.geojson"),
            "varias capas",
        )
        selected = convert_vector_for_portal(gpkg, root / "selected.geojson", layer="densidad")
        assert selected["input_layer"] == "densidad"

        # SHP requiere todos los componentes y CRS confiable.
        shape_dir = root / "shp"
        shape_dir.mkdir()
        shp = shape_dir / "bloque.shp"
        input_data.drop(columns=["object_key"]).to_file(
            shp, driver="ESRI Shapefile", engine="pyogrio"
        )
        with ZipFile(root / "bloque.zip", "w") as archive:
            for p in shape_dir.iterdir():
                archive.write(p, arcname=f"bloque/{p.name}")
        shapefile_output = root / "shape.geojson"
        from_shape = convert_vector_for_portal(root / "bloque.zip", shapefile_output)
        assert from_shape["input_format"] == "shapefile_zip"
        assert from_shape["feature_count"] == 2

        with ZipFile(root / "traversal.zip", "w") as archive:
            archive.writestr("../escape.shp", b"x")
        expect_error(
            lambda: convert_vector_for_portal(root / "traversal.zip", root / "escaped.geojson"),
            "insegura",
        )

        with ZipFile(root / "incomplete.zip", "w") as archive:
            archive.write(shp, arcname="bloque.shp")
        expect_error(
            lambda: convert_vector_for_portal(root / "incomplete.zip", root / "incomplete.geojson"),
            "faltan",
        )

        # Un CRS de trabajo UTM se convierte a EPSG:4326 y no se inventa.
        metric = gpd.GeoDataFrame(
            {"conteo": [3]},
            geometry=[Point(-79.8, -3.3)], crs="EPSG:4326",
        ).to_crs("EPSG:32717")
        metric.to_file(root / "utm.gpkg", driver="GPKG", engine="pyogrio")
        metric_result = convert_vector_for_portal(root / "utm.gpkg", root / "utm.geojson")
        assert metric_result["original_crs"] != "EPSG:4326"
        point = json.loads((root / "utm.geojson").read_text())["features"][0]["geometry"]["coordinates"]
        assert abs(point[0] + 79.8) < 0.0001 and abs(point[1] + 3.3) < 0.0001

        # Geometría autocruzada debe ser rechazada, no reparada silenciosamente.
        invalid = gpd.GeoDataFrame(
            {"valor": [1]},
            geometry=[Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])],
            crs="EPSG:4326",
        )
        invalid.to_file(root / "invalid.gpkg", driver="GPKG", engine="pyogrio")
        expect_error(
            lambda: convert_vector_for_portal(root / "invalid.gpkg", root / "invalid.geojson"),
            "inválidas",
        )
        print("Importador GIS DALGORO: SHP, GPKG, CRS, SHA y seguridad ZIP aprobados.")


if __name__ == "__main__":
    check_conversion()
