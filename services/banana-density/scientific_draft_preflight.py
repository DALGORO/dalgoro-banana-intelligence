"""CLI offline: verifica archivos REALES del borrador H14 sin permitir publicación."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from banana_analyzer.scientific_reception_draft_preflight import (  # noqa: E402
    DBIScientificDraftPreflightError, inspect_scientific_reception_draft,
)
from banana_analyzer.multispectral_map_preflight import DBIIndexMapPreflightError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validación geoespacial offline de 13 archivos del borrador H14; NUNCA publica.")
    parser.add_argument("--draft", required=True, type=Path, help="JSON exportado por el administrador")
    parser.add_argument("--geospatial-root", required=True, type=Path, help="Carpeta 1 en el equipo del worker")
    parser.add_argument("--multispectral-root", required=True, type=Path, help="Carpeta 2 en el equipo del worker")
    parser.add_argument("--stack-fingerprint-claimed", required=True, help="SHA-256 de fuente declarado, NO verificado contra base DBI")
    parser.add_argument("--output", type=Path, help="Expediente técnico nuevo, nunca sobrescribir")
    args = parser.parse_args(argv)
    try:
        draft_path = args.draft.expanduser().resolve(strict=True)
        if draft_path.stat().st_size > 1024 * 1024:
            raise DBIScientificDraftPreflightError("El borrador no debe superar 1 MiB.")
        data = json.loads(draft_path.read_text(encoding="utf-8"))
        evidence = inspect_scientific_reception_draft(
            draft=data,
            geospatial_root=args.geospatial_root,
            multispectral_root=args.multispectral_root,
            stack_fingerprint_claimed=args.stack_fingerprint_claimed,
        )
        payload = json.dumps(asdict(evidence), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            # Nunca reemplazar archivos fuente ni el borrador.
            out = args.output.expanduser().resolve()
            if (out == draft_path
                    or out.is_relative_to(args.geospatial_root.expanduser().resolve())
                    or out.is_relative_to(args.multispectral_root.expanduser().resolve())):
                raise DBIScientificDraftPreflightError("El reporte no puede reescribir los originales ni el borrador.")
            with args.output.expanduser().open("x", encoding="utf-8") as stream:
                stream.write(payload)
        else:
            sys.stdout.write(payload)
        return 0
    except (DBIScientificDraftPreflightError, DBIIndexMapPreflightError,
            OSError, TypeError, ValueError, UnicodeError) as error:
        print(f"Preflight H14 rechazado: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
