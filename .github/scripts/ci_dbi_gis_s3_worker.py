"""Pruebas sin red del worker GIS productivo apagado por defecto."""
from __future__ import annotations

import importlib.util
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
            (output / "valid.geojson").write_bytes(b"{}")
            (output / "valid.manifest.json").write_bytes(b"{}")
            return SimpleNamespace(returncode=0)

        with patch.dict(os.environ, secret_vars, clear=True):
            with patch.object(worker.subprocess, "run", side_effect=fake_run) as called:
                geojson, manifest = worker.run_isolated_converter(source, output)
                assert geojson.is_file() and manifest.is_file()
                assert called.call_count == 1

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
