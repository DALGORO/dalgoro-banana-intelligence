"""Valida que Git solo rastree fuentes canónicas y activos aprobados."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath


PROHIBITED_FILENAMES = {
    "codigos.txt",
    "sistema_completo_para_revision.txt",
}
PROHIBITED_MARKERS = ("_antes_", "_respaldo")
PROHIBITED_SUFFIXES = {".7z", ".bak", ".backup", ".rar", ".zip"}
PROHIBITED_DIRECTORIES = {
    "__pycache__",
    "cache",
    "dist",
    "logs",
    "node_modules",
    "outputs",
    "runs",
    "storage",
    "temp",
    "tmp",
}

PRESERVED_BINARY_ASSETS = {
    "apps/platform-web/backend/app/static/templates/BANANERA/ACTA-APR-RHS-01.docx",
    "apps/platform-web/backend/app/static/templates/BANANERA/AGRO-PLAG-01.docx",
    "apps/platform-web/backend/app/static/templates/BANANERA/CAP-01.docx",
    "apps/platform-web/backend/app/static/templates/BANANERA/EMG-01.docx",
    "apps/platform-web/backend/app/static/templates/BANANERA/EPP-01.docx",
    "apps/platform-web/backend/app/static/templates/BANANERA/IPERC-01.xlsx",
    "apps/platform-web/backend/app/static/templates/BANANERA/ORG-COM-01.docx",
    "apps/platform-web/backend/app/static/templates/BANANERA/ORG-DEL-01.docx",
    "apps/platform-web/backend/app/static/templates/BANANERA/PPRL-01.docx",
    "apps/platform-web/backend/app/static/templates/BANANERA/PSICO-01.docx",
    "apps/platform-web/backend/app/static/templates/BANANERA/RHS-01.docx",
    "apps/whatsapp-bot/documentos/SERVICIOS_DALGORO_SAS.pdf",
}


def tracked_paths(repository_root: Path) -> list[PurePosixPath]:
    """Obtiene rutas versionadas sin inspeccionar archivos ignorados."""

    result = subprocess.run(
        ["git", "-C", str(repository_root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [
        PurePosixPath(raw_path)
        for raw_path in result.stdout.decode("utf-8").split("\0")
        if raw_path
    ]


def violation_reason(path: PurePosixPath) -> str | None:
    """Explica por qué una ruta versionada es un artefacto no canónico."""

    lowercase_name = path.name.lower()
    lowercase_parts = {part.lower() for part in path.parts}

    if lowercase_name in PROHIBITED_FILENAMES:
        return "volcado de revisión"
    if lowercase_name.endswith(" copy.py"):
        return "copia directa de Python"
    if any(marker in lowercase_name for marker in PROHIBITED_MARKERS):
        return "respaldo o versión anterior"
    if path.suffix.lower() in PROHIBITED_SUFFIXES:
        return "archivo comprimido o respaldo"
    if lowercase_parts & PROHIBITED_DIRECTORIES:
        return "directorio de salida o ejecución"
    return None


def validate_paths(paths: list[PurePosixPath]) -> tuple[list[str], list[str]]:
    """Devuelve artefactos prohibidos y activos binarios ausentes."""

    tracked = {path.as_posix() for path in paths}
    violations = [
        f"{path.as_posix()}: {reason}"
        for path in paths
        if (reason := violation_reason(path)) is not None
    ]
    missing_assets = sorted(PRESERVED_BINARY_ASSETS - tracked)
    return sorted(violations), missing_assets


def main() -> None:
    """Falla el CI si reaparecen copias o desaparecen activos aprobados."""

    repository_root = Path(__file__).resolve().parents[2]
    paths = tracked_paths(repository_root)
    violations, missing_assets = validate_paths(paths)

    if violations:
        print("Artefactos no canónicos versionados:")
        for violation in violations:
            print(f"- {violation}")

    if missing_assets:
        print("Activos binarios funcionales ausentes:")
        for path in missing_assets:
            print(f"- {path}")

    if violations or missing_assets:
        raise SystemExit(1)

    print(
        "Higiene del repositorio aprobada: "
        f"{len(paths)} rutas canónicas y {len(PRESERVED_BINARY_ASSETS)} "
        "activos binarios preservados."
    )


if __name__ == "__main__":
    main()
