"""Ejecutor independiente (una iteración) de GIS privado usando S3 y PostGIS.

Se ejecuta EXCLUSIVAMENTE en un proceso GIS dedicado, NUNCA desde FastAPI.
No programa tareas, no otorga permisos y NO publica capas.
"""
from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import Callable, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.dbi.portal_gis_worker_service import DBIPortalGISPreparationWorker  # noqa: E402
from app.dbi.runtime import DBIRuntime  # noqa: E402
from app.dbi.storage_bootstrap import create_configured_object_store  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402


class DBIGISWorkerConfigurationError(ValueError):
    """Falla antes de descargar fuentes privadas o acceder a PostgreSQL."""


def _workspace(values: Mapping[str, str]) -> Path:
    raw = values.get("DBI_GIS_WORKER_ROOT", "")
    if not raw or not Path(raw).is_absolute():
        raise DBIGISWorkerConfigurationError(
            "DBI_GIS_WORKER_ROOT debe ser una carpeta absoluta y privada."
        )
    requested = Path(raw)
    if requested.is_symlink() or not requested.is_dir():
        raise DBIGISWorkerConfigurationError(
            "Prepara DBI_GIS_WORKER_ROOT como directorio existente, no symlink."
        )
    resolved = requested.resolve(strict=True)
    # El procesador crea temporales 0700 debajo de un directorio privado.
    if os.name == "posix":
        info = resolved.stat()
        if (
            info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise DBIGISWorkerConfigurationError(
                "DBI_GIS_WORKER_ROOT debe pertenecer al usuario y tener permisos 0700."
            )
    return resolved


def validate_worker_config(values: Mapping[str, str], tenant_ref: str) -> Path:
    if values.get("DBI_ENVIRONMENT", "").strip().lower() not in {"staging", "production"}:
        raise DBIGISWorkerConfigurationError("El worker S3 admite solo staging/production.")
    if values.get("DBI_STORAGE_BACKEND", "").strip().lower() != "s3":
        raise DBIGISWorkerConfigurationError("El worker GIS remoto requiere DBI_STORAGE_BACKEND=s3.")
    if values.get("DBI_LOCAL_STORAGE_ROOT", "").strip():
        raise DBIGISWorkerConfigurationError("Un worker remoto nunca usa almacenamiento local.")
    if not values.get("DBI_DATABASE_URL", "").strip():
        raise DBIGISWorkerConfigurationError("DBI_DATABASE_URL es obligatorio.")
    try:
        DBIStoragePolicy.tenant_namespace(tenant_ref)
    except (ValueError, TypeError) as error:
        raise DBIGISWorkerConfigurationError("El tenant GIS no es canónico.") from None
    return _workspace(values)


def run_one(
    *,
    tenant_ref: str,
    environ: Mapping[str, str] | None = None,
    runtime_factory: Callable[[], object] = DBIRuntime,
    store_factory: Callable[..., object] = create_configured_object_store,
    worker_factory: Callable[..., object] = DBIPortalGISPreparationWorker,
    converter: Callable | None = None,
) -> str | None:
    """Una sola conversión por invocación; no deja threads ni loops activos."""
    env = dict(os.environ if environ is None else environ)
    workspace = validate_worker_config(env, tenant_ref)

    # PROJ no realiza descargas de grids; GDAL no crea sidecars de metadata.
    # La importación de Pyogrio se hace después de configurar estas políticas.
    os.environ["PROJ_NETWORK"] = "OFF"
    os.environ["GDAL_PAM_ENABLED"] = "NO"
    if converter is None:
        from portal_gis_convert_cli import convert_vector
        converter = convert_vector

    # Configuración explícita compartida con FastAPI; jamás fallback a disco.
    store = store_factory(env)
    if store is None:
        raise DBIGISWorkerConfigurationError("El almacén S3 privado no está disponible.")
    runtime = runtime_factory()
    try:
        runtime.start()
        worker = worker_factory(
            runtime.require_session_factory(),
            store,
            converter,
            workspace_root=workspace,
        )
        return worker.process_one(tenant_ref=tenant_ref)
    finally:
        runtime.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preparar un original GPKG/SHP privado con S3 (una iteración; no publica)."
    )
    parser.add_argument("--tenant", required=True, help="Referencia exacta del tenant DBI habilitado.")
    args = parser.parse_args()
    try:
        outcome = run_one(tenant_ref=args.tenant)
    except DBIGISWorkerConfigurationError as error:
        parser.exit(2, f"Configuración de worker GIS rechazada: {error}\n")
    if outcome == "failed":
        parser.exit(2, "La conversión falló. El original privado no se publicó.\n")
    if outcome == "lease_lost":
        parser.exit(3, "La ejecución perdió su lease; no publicó resultados.\n")
    print({
        None: "Sin originales GIS pendientes para este tenant.",
        "prepared": "Vista previa GIS preparada de forma privada; requiere revisión y aprobación MANAGE.",
    }.get(outcome, "Iteración GIS terminada sin publicación."))


if __name__ == "__main__":
    main()
