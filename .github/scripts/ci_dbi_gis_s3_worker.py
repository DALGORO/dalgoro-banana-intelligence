"""Pruebas sin red del worker GIS productivo apagado por defecto."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_gis_s3_worker.db")
os.environ.setdefault("JWT_SECRET", "ci-only-gis-s3-worker")
ROOT = Path(__file__).resolve().parents[2]
script = ROOT / "services" / "banana-density" / "portal_gis_prepare_s3.py"
spec = importlib.util.spec_from_file_location("portal_gis_prepare_s3", script)
assert spec and spec.loader
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

VALUES = {
    "DBI_ENVIRONMENT": "staging",
    "DBI_DATABASE_URL": "postgresql+psycopg://stage_user:example@localhost:5432/dbi_staging",
    "DBI_STORAGE_BACKEND": "s3",
    "DBI_S3_ENDPOINT_URL": "https://private-s3.example",
    "DBI_S3_BUCKET": "dalgoro-private-gis",
    "DBI_S3_REGION": "us-east-1",
    "DBI_S3_ACCESS_KEY_ID": "secret-example-key",
    "DBI_S3_SECRET_ACCESS_KEY": "secret-example-value",
    "DBI_GIS_WORKER_TENANT": "tenant-ci",
    "DBI_GIS_WORKER_ROOT": "/tmp/dalgoro-private-ci",
}
SECRET = "secret-example"


def check_fail(data, phrase):
    try:
        worker.preflight(data)
    except (worker.GISWorkerPreflightError, RuntimeError) as error:
        assert phrase in str(error)
        assert SECRET not in str(error)
    else:
        raise AssertionError("Preflight S3 inseguro permitido")


def tests():
    tenant, root = worker.preflight(VALUES)
    assert tenant == "tenant-ci" and str(root) == "/tmp/dalgoro-private-ci"

    with TemporaryDirectory(prefix="dbi-gis-permissions-") as folder:
        private_values = {**VALUES, "DBI_GIS_WORKER_ROOT": folder}
        Path(folder).chmod(0o700)
        assert worker.preflight(private_values)[1] == Path(folder).resolve()
        Path(folder).chmod(0o755)
        check_fail(private_values, "0700")
        Path(folder).chmod(0o700)
        link = Path(folder) / "linked"
        link.symlink_to(folder, target_is_directory=True)
        check_fail({**private_values, "DBI_GIS_WORKER_ROOT": str(link)}, "simbólica")
    check_fail({**VALUES, "DBI_STORAGE_BACKEND": "local"}, "s3")
    check_fail({**VALUES, "DBI_ENVIRONMENT": "development"}, "staging")
    check_fail({**VALUES, "DBI_S3_ENDPOINT_URL": "http://127.0.0.1:9000"}, "HTTPS")
    check_fail({**VALUES, "DBI_GIS_WORKER_ROOT": "relative/path"}, "absoluta")
    check_fail({**VALUES, "DBI_GIS_WORKER_TENANT": ""}, "tenant")
    try:
        worker.run_once(VALUES)
    except worker.GISWorkerPreflightError as error:
        assert "deshabilitado" in str(error)
    else:
        raise AssertionError("Worker sin opt-in no debe ejecutar nada.")

    with patch.object(worker, "find_spec", return_value=None):
        try:
            worker.run_once({**VALUES, "DBI_GIS_WORKER_ENABLED": "1"})
        except worker.GISWorkerPreflightError as error:
            assert "geoespaciales" in str(error)
        else:
            raise AssertionError("Faltan módulos GIS y no debe reclamarse un trabajo.")

    with TemporaryDirectory(prefix="dbi-gis-s3-worker-test-") as folder:
        source = Path(folder) / "source.gpkg"
        source.write_bytes(b"SQLite format 3\x00" + b"synthetic")
        output = Path(folder) / "out"
        output.mkdir()
        secret_vars = {
            **os.environ,
            "DBI_S3_SECRET_ACCESS_KEY": SECRET,
            "DBI_DATABASE_URL": "postgresql://user:private@host/db",
        }

        def fake_run(argv, **kwargs):
            assert argv[0] == sys.executable
            assert str(worker.CONVERTER) == argv[1]
            assert kwargs["timeout"] == 120
            assert kwargs["start_new_session"] is True
            assert callable(kwargs["preexec_fn"])
            assert kwargs["env"]["PROJ_NETWORK"] == "OFF"
            assert kwargs["env"]["GDAL_PAM_ENABLED"] == "NO"
            assert "DBI_DATABASE_URL" not in kwargs["env"]
            assert "DBI_S3_SECRET_ACCESS_KEY" not in kwargs["env"]
            assert SECRET not in repr(kwargs["env"])
            if "--list-layers" in argv:
                kwargs["stdout"].write(json.dumps({"layers": ["unica"]}).encode("utf-8"))
            else:
                (output / "valid.geojson").write_bytes(b"{}")
                (output / "valid.manifest.json").write_bytes(b"{}")
            return SimpleNamespace(returncode=0)

        with patch.dict(os.environ, secret_vars, clear=True):
            with patch.object(worker.subprocess, "run", side_effect=fake_run) as called:
                geojson, manifest = worker.run_isolated_converter(source, output)
                assert geojson.is_file() and manifest.is_file()
                assert called.call_count == 2

        # GPKG multicapa: detener conversión y no crear ninguna vista previa.
        def discover_two(argv, **kwargs):
            assert "--list-layers" in argv
            kwargs["stdout"].write(json.dumps({"layers": ["plantas", "limites"]}).encode("utf-8"))
            return SimpleNamespace(returncode=0)

        with patch.object(worker.subprocess, "run", side_effect=discover_two) as called:
            choices = worker.run_isolated_converter(source, output)
            assert choices == worker.GISLayersPendingSelection(("plantas", "limites"))
            assert called.call_count == 1
            assert not (output / ".gis-layer-options.json").exists()

        # La respuesta malformada o con múltiples nombres iguales es rechazada.
        for invalid in ({"layers": ["duplicada", "duplicada"]},
                        {"layers": ["a\\nsecreta", "otra"]},
                        {"not_layers": ["a", "b"]}):
            def discover_invalid(argv, **kwargs):
                kwargs["stdout"].write(json.dumps(invalid).encode("utf-8"))
                return SimpleNamespace(returncode=0)
            with patch.object(worker.subprocess, "run", side_effect=discover_invalid):
                try:
                    worker.run_isolated_converter(source, output)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("Se admitieron opciones multicapa inválidas")

        # Un parser con error no publica ni entrega metadatos del proveedor.
        with patch.object(worker.subprocess, "run", return_value=SimpleNamespace(returncode=2)):
            try:
                worker.run_isolated_converter(source, output)
            except RuntimeError as error:
                assert "rechazó" in str(error)
            else:
                raise AssertionError("Conversión fallida no fue rechazada")
        with patch.object(worker.subprocess, "run", side_effect=subprocess.TimeoutExpired("gis", 120)):
            try:
                worker.run_isolated_converter(source, output)
            except RuntimeError as error:
                assert "expiró" in str(error)
            else:
                raise AssertionError("Timeout no fue rechazado")

    print("Worker GIS S3: opt-in, staging, tenant, subprocess acotado y secretos fuera del parser OK.")


if __name__ == "__main__":
    tests()
