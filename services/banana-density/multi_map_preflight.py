"""CLI local del preflight de seis mapas científicos; no publica datos."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from banana_analyzer.multispectral_map_preflight import (  # noqa: E402
    DBIIndexMapPreflightError,
    inspect_six_index_maps,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prevalidar 6 COG Float32/QML (no publica ni autoriza una Campaign)."
    )
    parser.add_argument("--input", required=True, type=Path, help="JSON local con campaign_id, stack_fingerprint y files")
    parser.add_argument("--output", type=Path, help="Guardar evidencia JSON nueva (no sobrescribir)")
    args = parser.parse_args(argv)
    try:
        config_path = args.input.expanduser().resolve()
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or set(config) != {"campaign_id", "stack_fingerprint", "files"}:
            raise DBIIndexMapPreflightError("Configuración requiere campaign_id, stack_fingerprint y files.")
        files = config["files"]
        if not isinstance(files, dict):
            raise DBIIndexMapPreflightError("files debe ser un objeto por índice.")
        resolved_files = {}
        for key, spec in files.items():
            if not isinstance(spec, dict) or set(spec) != {"raster", "qml"}:
                raise DBIIndexMapPreflightError("Cada índice exige raster y qml.")
            if not all(isinstance(value, str) and value for value in spec.values()):
                raise DBIIndexMapPreflightError("raster y qml deben ser rutas locales.")
            resolved_files[key] = {
                prop: str((config_path.parent / value).resolve())
                for prop, value in spec.items()
            }
        result = inspect_six_index_maps(
            campaign_id=UUID(config["campaign_id"]),
            stack_fingerprint=config["stack_fingerprint"],
            files=resolved_files,
        )
        payload = json.dumps(asdict(result), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            with args.output.expanduser().open("x", encoding="utf-8") as stream:
                stream.write(payload)
        else:
            sys.stdout.write(payload)
        return 0
    except (DBIIndexMapPreflightError, OSError, TypeError, ValueError) as error:
        print(f"Preflight rechazado: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
