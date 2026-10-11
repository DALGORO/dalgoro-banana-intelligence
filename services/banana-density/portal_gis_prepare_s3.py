"""Entrada controlada de UN trabajo GIS en un proceso aislado con storage S3.

No es un daemon ni un endpoint: requiere ejecución explícita del operador/scheduler.
Nunca importa GDAL/Pyogrio en FastAPI y no publica capas automáticamente.
"""
from __future__ import annotations

import argparse
from importlib.util import find_spec
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import load_dbi_database_config  # noqa: E402
from app.dbi.portal_gis_worker_service import (  # noqa: E402
    DBIPortalGISPreparationWorker,
)
from app.dbi.runtime import DBIRuntime  # noqa: E402
from app.dbi.storage_bootstrap import (  # noqa: E402
    create_configured_object_store,
    s3_config_from_environment,
)
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from app.dbi.storage_contracts import DBIStorageConflict  # noqa: E402
from app.dbi.storage_s3 import DBIS3ObjectStore  # noqa: E402

CONVERTER = Path(__file__).resolve().with_name("portal_gis_convert_cli.py")
CONVERSION_TIMEOUT_SECONDS = 120


class GISWorkerPreflightError(RuntimeError):
    pass


def preflight(values: Mapping[str, str]) -> tuple[str, Path]:
    """Verifica ambiente sin abrir DB, crear cliente S3 ni leer credenciales."""
    if values.get("DBI_ENVIRONMENT", "").strip().lower() not in {"staging", "production"}:
        raise GISWorkerPreflightError("El worker S3 exige DBI_ENVIRONMENT staging/production.")
    if values.get("DBI_STORAGE_BACKEND", "").strip().lower() != "s3":
        raise GISWorkerPreflightError("El worker exige DBI_STORAGE_BACKEND=s3.")
    load_dbi_database_config(values)
    s3_config_from_environment(values)

    tenant = values.get("DBI_GIS_WORKER_TENANT", "").strip()
    if not tenant or len(tenant) > 128:
        raise GISWorkerPreflightError("Configura el tenant GIS explícito.")
    try:
        DBIStoragePolicy.tenant_namespace(tenant)
    except (TypeError, ValueError, DBIStorageConflict):
        raise GISWorkerPreflightError("Tenant GIS no canónico.") from None

    root_raw = values.get("DBI_GIS_WORKER_ROOT", "").strip()
    if not root_raw or not Path(root_raw).is_absolute():
        raise GISWorkerPreflightError("DBI_GIS_WORKER_ROOT debe ser una ruta absoluta privada.")
    root = Path(root_raw).resolve()
    if root == Path("/") or root == ROOT or ROOT in root.parents:
        raise GISWorkerPreflightError("El workspace GIS debe estar fuera del repositorio.")
    if Path(root_raw).is_symlink():
        raise GISWorkerPreflightError("Workspace GIS no admite raíz simbólica.")
    if not CONVERTER.is_file():
        raise GISWorkerPreflightError("El conversor GIS no está instalado.")
    if sys.platform != "linux":
        raise GISWorkerPreflightError("Esta entrada exige Linux para aislar CPU y tamaño de archivos.")
    return tenant, root


def _set_limits() -> None:
    # Se ejecuta solamente en el proceso secundario Linux, nunca en FastAPI.
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (80, 80))
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024 ** 3, 4 * 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 ** 2, 4 * 1024 ** 2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))


def _minimal_conversion_environment(output_dir: Path, values: Mapping[str, str]) -> dict[str, str]:
    # Nunca pasa credenciales S3/Postgres ni token de Render al parser GDAL.
    allowed = {"PATH", "LD_LIBRARY_PATH", "PROJ_DATA", "GDAL_DATA", "LANG", "LC_ALL"}
    env = {key: value for key, value in values.items() if key in allowed}
    env.update({
        "HOME": str(output_dir),
        "TMPDIR": str(output_dir),
        "PROJ_NETWORK": "OFF",
        "GDAL_PAM_ENABLED": "NO",
        "GDAL_DISABLE_READDIR_ON_OPEN": "TRUE",
        "PYTHONNOUSERSITE": "1",
    })
    return env


def run_isolated_converter(source: Path, output_dir: Path):
    """Conversión estricta con timeout; salida del parser nunca va al usuario."""
    source = Path(source)
    output_dir = Path(output_dir)
    if source.suffix.lower() not in {".gpkg", ".zip"} or not source.is_file():
        raise RuntimeError("Origen GIS local inválido.")
    if not output_dir.is_dir() or source.parent == output_dir:
        raise RuntimeError("Destino GIS no aislado.")
    try:
        result = subprocess.run(
            [sys.executable, str(CONVERTER), str(source), "--output-dir", str(output_dir)],
            cwd=output_dir,
            env=_minimal_conversion_environment(output_dir, os.environ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=CONVERSION_TIMEOUT_SECONDS,
            check=False,
            start_new_session=True,
            preexec_fn=_set_limits,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Falló o expiró el conversor GIS aislado.") from None
    if result.returncode != 0:
        raise RuntimeError("El conversor GIS rechazó la fuente.")
    derivatives = list(output_dir.glob("*.geojson"))
    manifests = list(output_dir.glob("*.manifest.json"))
    if len(derivatives) != 1 or len(manifests) != 1:
        raise RuntimeError("El conversor GIS no entregó un derivado único.")
    expected_manifest = output_dir / (derivatives[0].name[:-len(".geojson")] + ".manifest.json")
    if manifests[0] != expected_manifest:
        raise RuntimeError("El manifiesto GIS no coincide con el derivado.")
    return derivatives[0], manifests[0]


def run_once(values: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if values is None else values
    tenant, root = preflight(source)
    if source.get("DBI_GIS_WORKER_ENABLED", "") != "1":
        raise GISWorkerPreflightError("El worker GIS está deshabilitado por defecto.")
    # Sin entorno geoespacial completo, NO reclamar ni fallar archivos válidos.
    if any(find_spec(module) is None for module in ("pyogrio", "geopandas", "shapely")):
        raise GISWorkerPreflightError("Faltan dependencias geoespaciales del worker.")
    # No se inicia sesión ni se reclama un archivo sin comprobar el proveedor.
    store = create_configured_object_store(source)
    if not isinstance(store, DBIS3ObjectStore):
        raise GISWorkerPreflightError("No se configuró un almacenamiento S3 válido.")

    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    runtime = DBIRuntime()
    runtime.start()
    try:
        worker = DBIPortalGISPreparationWorker(
            runtime.require_session_factory(),
            store, run_isolated_converter,
            workspace_root=root,
        )
        return worker.process_one(tenant_ref=tenant)
    finally:
        runtime.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Preparar exactamente un GIS privado DBI.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Verificar configuración SIN IO ni claims.")
    group.add_argument("--once", action="store_true", help="Reclamar y procesar hasta una importación.")
    args = parser.parse_args()
    try:
        if args.check:
            preflight(os.environ)
            print("Preflight GIS S3 correcto (no verifica conectividad ni despliegue).")
            return
        result = run_once()
    except (GISWorkerPreflightError, ValueError) as error:
        parser.exit(2, f"Preflight GIS: {error}\n")
    if result == "failed":
        parser.exit(2, "Importación GIS fallida; no se publicó ninguna capa.\n")
    print({
        None: "Sin importaciones GIS pendientes.",
        "prepared": "Vista previa GIS privada preparada; requiere aprobación MANAGE.",
        "lease_lost": "El claim venció; el resultado no se guardó.",
    }.get(result, "Resultado GIS pendiente de revisión."))


if __name__ == "__main__":
    main()
