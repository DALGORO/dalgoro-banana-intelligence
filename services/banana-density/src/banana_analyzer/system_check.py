from __future__ import annotations

import json
import platform
import shutil
import sys
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


# system_check.py se encuentra en:
# automatizacion_banano/src/banana_analyzer/system_check.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_PROJECT_ROOT = PROJECT_ROOT.parent
LOGS_DIRECTORY = PROJECT_ROOT / "logs"


PACKAGE_NAMES = (
    "torch",
    "torchvision",
    "ultralytics",
    "rasterio",
    "geopandas",
    "shapely",
    "pyogrio",
    "opencv-python",
    "PyYAML",
)


def bytes_to_gib(value: int) -> float:
    """Convierte bytes a GiB con dos decimales."""
    return round(value / (1024**3), 2)


def get_package_version(package_name: str) -> str:
    """Obtiene la versión instalada de un paquete."""
    try:
        return version(package_name)
    except PackageNotFoundError:
        return "NO INSTALADO"


def get_disk_information() -> dict[str, Any]:
    """Obtiene información de almacenamiento de la unidad del proyecto."""
    usage = shutil.disk_usage(PROJECT_ROOT.anchor)

    return {
        "unidad": PROJECT_ROOT.anchor,
        "capacidad_gib": bytes_to_gib(usage.total),
        "usado_gib": bytes_to_gib(usage.used),
        "libre_gib": bytes_to_gib(usage.free),
    }


def find_nvidia_smi() -> str | None:
    """Localiza nvidia-smi sin modificar permanentemente el PATH."""
    candidates = (
        shutil.which("nvidia-smi"),
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        r"C:\Windows\System32\nvidia-smi.exe",
    )

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))

    return None


def get_torch_information() -> dict[str, Any]:
    """Obtiene información de PyTorch y CUDA."""
    try:
        import torch
    except Exception as error:
        return {
            "disponible": False,
            "error": str(error),
        }

    cuda_available = torch.cuda.is_available()

    information: dict[str, Any] = {
        "disponible": True,
        "version": torch.__version__,
        "cuda_disponible": cuda_available,
        "cantidad_gpu": torch.cuda.device_count() if cuda_available else 0,
        "gpu": None,
    }

    if cuda_available:
        information["gpu"] = torch.cuda.get_device_name(0)

    return information


def find_existing_models() -> list[str]:
    """
    Comprueba únicamente las ubicaciones derivadas de la auditoría.

    No modifica ni mueve los modelos encontrados.
    """
    candidates = (
        LEGACY_PROJECT_ROOT / "banano_v3" / "weights" / "best.pt",
        LEGACY_PROJECT_ROOT / "banano_v3" / "weights" / "last.pt",
        LEGACY_PROJECT_ROOT
        / "runs"
        / "detect"
        / "banano_v3"
        / "weights"
        / "best.pt",
        LEGACY_PROJECT_ROOT
        / "runs"
        / "detect"
        / "banano_v3"
        / "weights"
        / "last.pt",
    )

    return [str(path) for path in candidates if path.is_file()]


def build_report() -> dict[str, Any]:
    """Construye el informe completo del entorno."""
    return {
        "fecha_revision": datetime.now().isoformat(timespec="seconds"),
        "proyecto_automatizacion": str(PROJECT_ROOT),
        "proyecto_existente": str(LEGACY_PROJECT_ROOT),
        "sistema_operativo": platform.platform(),
        "python": {
            "version": sys.version,
            "ejecutable": sys.executable,
        },
        "almacenamiento": get_disk_information(),
        "paquetes": {
            package_name: get_package_version(package_name)
            for package_name in PACKAGE_NAMES
        },
        "pytorch": get_torch_information(),
        "nvidia_smi": find_nvidia_smi(),
        "modelos_encontrados": find_existing_models(),
    }


def save_report(report: dict[str, Any]) -> Path:
    """Guarda el diagnóstico en formato JSON."""
    LOGS_DIRECTORY.mkdir(parents=True, exist_ok=True)

    output_path = LOGS_DIRECTORY / "system_check.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=4)

    return output_path


def run_system_check() -> int:
    """Ejecuta el diagnóstico y muestra un resumen."""
    report = build_report()
    output_path = save_report(report)

    print("=" * 65)
    print("DIAGNÓSTICO DEL SISTEMA DE ANÁLISIS DE BANANO")
    print("=" * 65)

    print(f"Python: {report['python']['version'].split()[0]}")
    print(f"Ejecutable: {report['python']['ejecutable']}")
    print(f"Unidad: {report['almacenamiento']['unidad']}")
    print(f"Espacio libre: {report['almacenamiento']['libre_gib']} GiB")
    print(f"CUDA disponible: {report['pytorch'].get('cuda_disponible', False)}")
    print(f"nvidia-smi: {report['nvidia_smi'] or 'No localizado'}")

    models = report["modelos_encontrados"]

    if models:
        print("Modelos encontrados:")

        for model in models:
            print(f"  - {model}")
    else:
        print("Modelos encontrados: ninguno en las rutas auditadas")

    print(f"Informe guardado en: {output_path}")
    print("=" * 65)

    return 0


if __name__ == "__main__":
    raise SystemExit(run_system_check())