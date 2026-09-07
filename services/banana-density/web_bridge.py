"""Adaptador CLI mínimo para reutilizar exactamente la configuración de la GUI estable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from interfaz_banano import (
    ALL_EXCLUSION_LAYERS,
    atomic_write_yaml,
    build_pipeline_config,
    validate_values,
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("La solicitud web debe ser un objeto JSON.")
    return payload


def prepare(request_path: Path, config_path: Path) -> int:
    values = _read_json(request_path)
    if str(values.get("exclusions_gpkg") or "").strip():
        values["exclusions_layer"] = ALL_EXCLUSION_LAYERS
    else:
        values["exclusions_gpkg"] = ""
        values["exclusions_layer"] = ""

    validate_values(values)
    config = build_pipeline_config(values)
    atomic_write_yaml(config_path, config)
    print(
        json.dumps(
            {
                "success": True,
                "config_path": str(config_path),
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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "prepare":
        return prepare(args.request_path, args.config_path)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
