from __future__ import annotations
import argparse, importlib.util, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
INTERFACE_FILE = PROJECT_ROOT / "interfaz_banano.py"

def load_module():
    if not INTERFACE_FILE.is_file():
        raise FileNotFoundError(f"No existe: {INTERFACE_FILE}")
    spec = importlib.util.spec_from_file_location("dalgoro_gui_repair", INTERFACE_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError("No se pudo cargar interfaz_banano.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def main() -> int:
    parser = argparse.ArgumentParser(description="Repara exclusiones múltiples en una ejecución fallida.")
    parser.add_argument("run_directory")
    args = parser.parse_args()
    run_dir = Path(args.run_directory).expanduser().resolve(strict=False)
    try:
        module = load_module()
        snapshot, message = module.repair_resume_snapshot(run_dir)
        config = module.read_yaml(snapshot)
        analysis = config["analysis"]
        print("=" * 72)
        print("REPARACIÓN DE EXCLUSIONES COMPLETADA")
        print("=" * 72)
        print(f"Ejecución: {run_dir}")
        print(f"GeoPackage: {analysis.get('exclusions_gpkg')}")
        print(f"Capa: {analysis.get('exclusions_layer')}")
        print(message or "La configuración ya estaba correcta.")
        print("=" * 72)
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
