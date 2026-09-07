"""Adaptador CLI mínimo para reutilizar la configuración de la GUI estable."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("La solicitud web debe ser un objeto JSON.")
    return payload


def _load_interface(engine_root: Path) -> ModuleType:
    interface_path = engine_root / "interfaz_banano.py"
    if not interface_path.is_file():
        raise FileNotFoundError(
            f"No existe la interfaz estable del analizador: {interface_path}"
        )
    spec = importlib.util.spec_from_file_location(
        "dalgoro_density_stable_interface",
        interface_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("No se pudo cargar la interfaz estable del analizador.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ensure_geotiff_alias(values: dict[str, Any], config_path: Path) -> None:
    """Da al motor estable una ruta .tif sin duplicar la ortofoto privada DBI.

    El object store DBI usa claves opacas sin extensión. La GUI estable valida que
    la ortofoto termine en .tif/.tiff antes de abrirla. Como storage y jobs viven
    bajo LOCALAPPDATA en el mismo volumen local, un hard link ofrece una vista
    compatible del mismo archivo sin copiar varios GB.
    """

    raw = str(values.get("orthophoto") or "").strip()
    if not raw:
        return
    source = Path(raw).expanduser().resolve(strict=False)
    if source.suffix.lower() in {".tif", ".tiff"}:
        return
    if not source.is_file():
        return

    alias = config_path.parent / "inputs" / "ortofoto.tif"
    alias.parent.mkdir(parents=True, exist_ok=True)
    if alias.exists():
        try:
            if os.path.samefile(source, alias):
                values["orthophoto"] = str(alias)
                return
        except OSError:
            pass
        alias.unlink()

    try:
        os.link(source, alias)
    except OSError as error:
        raise RuntimeError(
            "No se pudo crear la vista .tif de la ortofoto privada DBI sin duplicar el archivo."
        ) from error

    values["orthophoto"] = str(alias)


def prepare(request_path: Path, config_path: Path, engine_root: Path) -> int:
    root = engine_root.expanduser().resolve(strict=False)
    interface = _load_interface(root)
    values = _read_json(request_path)

    _ensure_geotiff_alias(values, config_path)

    all_layers = str(getattr(interface, "ALL_EXCLUSION_LAYERS"))
    if str(values.get("exclusions_gpkg") or "").strip():
        values["exclusions_layer"] = all_layers
    else:
        values["exclusions_gpkg"] = ""
        values["exclusions_layer"] = ""

    interface.validate_values(values)
    config = interface.build_pipeline_config(values)

    # Las configuraciones cartográficas/técnicas deben provenir del mismo motor
    # que Darwin ya usa en producción local, no de una copia paralela del repo web.
    config["configs"] = {
        "spatial_analysis": str(root / "config" / "spatial_analysis.yaml"),
        "cartography": str(root / "config" / "cartography.yaml"),
        "report": str(root / "config" / "report.yaml"),
    }
    interface.atomic_write_yaml(config_path, config)
    print(
        json.dumps(
            {
                "success": True,
                "config_path": str(config_path),
                "engine_root": str(root),
                "exclusions_layer": config["analysis"].get("exclusions_layer"),
            },
            ensure_ascii=False,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="banana-density-web-bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("request_path", type=Path)
    prepare_parser.add_argument("config_path", type=Path)
    prepare_parser.add_argument("engine_root", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "prepare":
        return prepare(args.request_path, args.config_path, args.engine_root)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
