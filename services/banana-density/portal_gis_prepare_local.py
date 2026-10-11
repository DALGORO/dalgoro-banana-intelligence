"""Entrada EXCLUSIVA del entorno geoespacial para preparar UN GIS privado.

Pruebas locales/controladas: no inicia tareas en FastAPI ni usa un scheduler
de producción. En producción habrá que configurar el worker independiente
y su almacén compartido persistente antes de activarlo.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from portal_gis_convert_cli import convert_vector  # noqa: E402
from app.dbi.portal_gis_worker_service import DBIPortalGISPreparationWorker  # noqa: E402
from app.dbi.runtime import DBIRuntime  # noqa: E402
from app.dbi.storage_local import DBILocalObjectStore  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Preparar un GIS recibido para revisión, sin publicación.")
    parser.add_argument("--tenant", required=True, help="Tenant DBI explícito autorizado para este worker.")
    args = parser.parse_args()

    if os.environ.get("DBI_ENVIRONMENT", "").strip().lower() not in {"local", "development"}:
        parser.error("Solo admite el entorno GIS local/development; no ejecuta producción.")
    source_root = os.environ.get("DBI_LOCAL_STORAGE_ROOT", "").strip()
    workspace_root = os.environ.get("DBI_GIS_WORKER_ROOT", "").strip()
    if not source_root or not workspace_root:
        parser.error("Configura DBI_LOCAL_STORAGE_ROOT y DBI_GIS_WORKER_ROOT.")
    if not Path(source_root).is_absolute() or not Path(workspace_root).is_absolute():
        parser.error("Las raíces de almacenamiento y procesamiento deben ser absolutas.")
    if Path(source_root).resolve() == Path(workspace_root).resolve():
        parser.error("No se puede utilizar el almacén privado como workspace.")

    try:
        DBIStoragePolicy.tenant_namespace(args.tenant)
    except (ValueError, TypeError) as error:
        parser.error(str(error))
    # Proj nunca descarga transformaciones desde servidores externos.
    os.environ["PROJ_NETWORK"] = "OFF"
    os.environ["GDAL_PAM_ENABLED"] = "NO"

    runtime = DBIRuntime()
    runtime.start()
    try:
        service = DBIPortalGISPreparationWorker(
            runtime.require_session_factory(),
            DBILocalObjectStore(source_root),
            lambda source, dest: convert_vector(source, dest),
            workspace_root=Path(workspace_root),
        )
        result = service.process_one(tenant_ref=args.tenant)
    finally:
        runtime.stop()

    if result == "failed":
        parser.exit(2, "La fuente GIS quedó marcada como fallida; requiere revisión del gestor.\n")
    print({
        None: "No hay archivos GIS pendientes para este tenant.",
        "prepared": "Derivado GIS preparado en privado. Requiere aprobación, no está publicado.",
        "lease_lost": "Otro intento reemplazó este procesamiento; no se aplicó el resultado.",
    }.get(result, "Procesamiento GIS sin publicación."))


if __name__ == "__main__":
    main()
