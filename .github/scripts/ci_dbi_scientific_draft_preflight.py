"""CI H14: 13 fuentes sintéticas REALES, auditoría offline y denegación segura."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "services" / "banana-density"
sys.path.insert(0, str(SERVICE / "src"))

from banana_analyzer.multispectral_indices import SpectralIndex  # noqa: E402
from banana_analyzer.multispectral_map_preflight import DBIIndexMapPreflightError  # noqa: E402
from banana_analyzer.scientific_reception_draft_preflight import (  # noqa: E402
    DBIScientificDraftPreflightError, inspect_scientific_reception_draft,
)
from banana_analyzer.raster_cog import generate_validated_cog  # noqa: E402


CAMPAIGN = "63000000-0000-4000-8000-000000000063"
FP = "b" * 64
TR = from_origin(620000.0, 9640000.0, .25, .25)


def make_rgb(path: Path, transform=TR, bands=3) -> None:
    with rasterio.open(path, "w", driver="GTiff", width=256, height=256,
                       count=bands, dtype="uint8", crs="EPSG:32717",
                       transform=transform, photometric="RGB" if bands == 3 else "MINISBLACK") as ds:
        for idx in range(1, bands + 1):
            ds.write(np.full((256, 256), idx * 30, dtype=np.uint8), idx)


def make_cog(folder: Path, index: str, n: int) -> Path:
    source = folder / (index + "_original.tif")
    target = folder / (index + ".cog.tif")
    data = np.full((256, 256), 0.02 + n * .09, dtype="float32")
    data[:12, :12] = -9999
    with rasterio.open(source, "w", driver="GTiff", count=1, width=256, height=256,
                       dtype="float32", crs="EPSG:32717", nodata=-9999.,
                       transform=TR) as ds:
        ds.write(data, 1)
    generate_validated_cog(source, target, product_kind="scientific", profile_version="h14-ci")
    source.unlink()
    return target


def make_qml(path: Path) -> None:
    path.write_text(
        '<qgis version="3.34"><pipe><rasterrenderer type="singlebandpseudocolor" band="1">'
        '<rastershader><colorrampshader>'
        '<item value="-1" color="#aa1010"/><item value="1" color="#10aa10"/>'
        '</colorrampshader></rastershader></rasterrenderer></pipe></qgis>',
        encoding="utf-8",
    )


def record(folder: Path, path: Path, role: str, index: str | None) -> dict:
    return {
        "folder": "geospatial" if folder.name == "GEO" else "multispectral",
        "role": role, "index": index, "relative_path": folder.name + "/" + path.name,
        "size_bytes": path.stat().st_size, "sha256": None, "file_content_verified": False,
    }


def build(root: Path) -> tuple[dict, dict]:
    geo = root / "GEO"
    multi = root / "MULTI"
    geo.mkdir()
    multi.mkdir()
    rgb = geo / "ORTHO_RGB.tif"
    make_rgb(rgb)
    paths = [rgb]
    files = [record(geo, rgb, "rgb", None)]
    for n, item in enumerate(SpectralIndex, start=1):
        tif = make_cog(multi, item.value, n)
        qml = multi / (item.value + ".qml")
        make_qml(qml)
        files.extend([
            record(multi, tif, "scientific_cog", item.value),
            record(multi, qml, "qml_style", item.value),
        ])
        paths.extend([tif, qml])
    draft = {
        "schema_version": "dbi-h14-scientific-reception-draft.v1",
        "state": "local_metadata_only_not_uploaded",
        "scope": {
            "tenant_ref": "tenant-synthetic", "organization_ref": "org-synthetic",
            "farm_id": "63000000-0000-4000-8000-000000000061",
            "plot_id": "63000000-0000-4000-8000-000000000062",
            "campaign_id": CAMPAIGN,
        },
        "folders": {"geospatial": "GEO", "multispectral": "MULTI"},
        "files": files, "blockers": [], "structural_ready": True,
        "scientific_validated": False, "server_received": False,
        "institutional_approved": False, "published": False,
    }
    return draft, {"geospatial_root": geo, "multispectral_root": multi, "stack_fingerprint_claimed": FP, "paths": paths}


def denied(draft: dict, args: dict, label: str) -> None:
    try:
        inspect_scientific_reception_draft(draft=draft, **args)
    except (DBIScientificDraftPreflightError, DBIIndexMapPreflightError):
        return
    raise AssertionError("Debió rechazar: " + label)


def main() -> None:
    with TemporaryDirectory(prefix="dbi-h14-two-folders-real-files-") as temporary:
        root = Path(temporary)
        draft, settings = build(root)
        originals = {path: sha256(path.read_bytes()).hexdigest() for path in settings["paths"]}
        call = {key: val for key, val in settings.items() if key != "paths"}
        evidence = inspect_scientific_reception_draft(draft=draft, **call)
        assert evidence.schema_version == "dbi-h14-scientific-draft-preflight.v1"
        assert evidence.disposition == "offline_technical_evidence_only_not_published"
        assert evidence.campaign_id_claimed == CAMPAIGN
        assert not evidence.campaign_link_verified
        assert not evidence.source_provenance_verified
        assert not evidence.rgb_semantic_bands_verified
        assert not evidence.institutional_publication_authorized
        assert evidence.rgb_multispectral_extent_intersects
        assert evidence.rgb_source_sha256 == originals[root / "GEO" / "ORTHO_RGB.tif"]
        assert len(evidence.index_map_preflight.indexes) == 6
        assert not evidence.index_map_preflight.campaign_link_verified
        assert not evidence.index_map_preflight.institutional_publication_authorized
        for idx in evidence.index_map_preflight.indexes:
            assert idx.valid_pixels > 0 and idx.crs == "EPSG:32717"
            assert idx.raster_sha256 == originals[root / "MULTI" / (idx.index + ".cog.tif")]
        config = root / "borrador.json"
        config.write_text(json.dumps(draft), encoding="utf-8")
        cli = SERVICE / "scientific_draft_preflight.py"
        args = [
            sys.executable, str(cli), "--draft", str(config),
            "--geospatial-root", str(root / "GEO"), "--multispectral-root", str(root / "MULTI"),
            "--stack-fingerprint-claimed", FP,
        ]
        first = subprocess.run(args, capture_output=True, text=True, check=False)
        assert first.returncode == 0, first.stderr
        assert json.loads(first.stdout) == json.loads(json.dumps(asdict(evidence)))
        out = root / "technical_evidence.json"
        second = subprocess.run(args + ["--output", str(out)], capture_output=True, text=True, check=False)
        assert second.returncode == 0 and out.is_file(), second.stderr
        repeat = subprocess.run(args + ["--output", str(out)], capture_output=True, text=True, check=False)
        assert repeat.returncode == 2 and "rechazado" in repeat.stderr
        rewritten = subprocess.run(args + ["--output", str(root / "GEO" / "report.json")],
                                   capture_output=True, text=True, check=False)
        assert rewritten.returncode == 2 and not (root / "GEO" / "report.json").exists()

        manipulated = deepcopy(draft)
        manipulated["published"] = True
        denied(manipulated, call, "finge publicado")
        manipulated = deepcopy(draft)
        manipulated["files"][1]["sha256"] = "a" * 64
        denied(manipulated, call, "finge sha256 previo")
        manipulated = deepcopy(draft)
        manipulated["files"][1]["relative_path"] = "MULTI/../GEO/ORTHO_RGB.tif"
        denied(manipulated, call, "escape de ruta")
        manipulated = deepcopy(draft)
        manipulated["files"][2]["index"] = "ndvi"
        denied(manipulated, call, "pares duplicados")
        manipulated = deepcopy(draft)
        manipulated["files"][1]["size_bytes"] += 1
        denied(manipulated, call, "archivo modificado")
        manipulated = deepcopy(draft)
        manipulated["files"] = manipulated["files"][:-1]
        denied(manipulated, call, "índice sin estilo")
        manipulated = deepcopy(draft)
        manipulated["scope"]["campaign_id"] = "test"
        denied(manipulated, call, "Campaign falsa")
        manipulated = deepcopy(draft)
        manipulated["folders"]["geospatial"] = "MULTI"
        denied(manipulated, call, "root alterado")
        symlink_path = root / "MULTI" / "symlink.qml"
        symlink_path.symlink_to(root / "MULTI" / "ndvi.qml")
        manipulated = deepcopy(draft)
        manipulated["files"][2]["relative_path"] = "MULTI/symlink.qml"
        denied(manipulated, call, "enlace simbólico")
        symlink_path.unlink()

        with TemporaryDirectory(prefix="dbi-h14-rgb-far-") as other:
            moved = Path(other) / "rgbfar.tif"
            make_rgb(moved, transform=from_origin(200000.0, 9000000.0, .25, .25))
            rgb = root / "GEO" / "ORTHO_RGB.tif"
            oldbytes = rgb.read_bytes()
            rgb.write_bytes(moved.read_bytes())
            altered = deepcopy(draft)
            altered["files"][0]["size_bytes"] = rgb.stat().st_size
            denied(altered, call, "RGB georreferenciada pero fuera de la campaña")
            rgb.write_bytes(oldbytes)
        for path, original in originals.items():
            assert sha256(path.read_bytes()).hexdigest() == original, "Se cambió un original"
    print("H14 PASS: 13 originales RGB/6 COG/6 QML, SHA256, grillas, solape, rutas, CLI y no publicación.")


if __name__ == "__main__":
    main()
