"""Prueba offline de la entrada GIS S3, sin S3/PostGIS ni credenciales reales."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "banana-density"))
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from portal_gis_prepare_s3 import (  # noqa: E402
    DBIGISWorkerConfigurationError, run_one, validate_worker_config,
)

BASE = {
    "DBI_ENVIRONMENT": "staging",
    "DBI_STORAGE_BACKEND": "s3",
    "DBI_DATABASE_URL": "postgresql+psycopg://worker@example.internal/dbi_staging",
    "DBI_S3_ENDPOINT_URL": "https://objects.example.internal",
    "DBI_S3_BUCKET": "private-gis",
    "DBI_S3_REGION": "us-east-1",
    "DBI_S3_ACCESS_KEY_ID": "test-only",
    "DBI_S3_SECRET_ACCESS_KEY": "test-only",
}


def rejected(env, *, tenant="tenant-one"):
    try:
        validate_worker_config(env, tenant)
    except DBIGISWorkerConfigurationError:
        return
    raise AssertionError("Worker GIS aceptó un entorno no autorizado.")


def run():
    with TemporaryDirectory(prefix="gis-workspace-test-") as root:
        path = Path(root)
        if os.name == "posix":
            path.chmod(0o700)
        env = {**BASE, "DBI_GIS_WORKER_ROOT": root}
        assert validate_worker_config(env, "tenant-one") == path.resolve()

        rejected({**env, "DBI_ENVIRONMENT": "development"})
        rejected({**env, "DBI_ENVIRONMENT": "local"})
        rejected({**env, "DBI_STORAGE_BACKEND": "local"})
        rejected({**env, "DBI_STORAGE_BACKEND": ""})
        rejected({**env, "DBI_DATABASE_URL": ""})
        rejected({**env, "DBI_LOCAL_STORAGE_ROOT": "/tmp/not-shared"})
        rejected({**env, "DBI_GIS_WORKER_ROOT": "relative/work"})
        rejected({**env, "DBI_GIS_WORKER_ROOT": root + "/nonexistent"})
        rejected(env, tenant="*")
        rejected(env, tenant="all")

        symlink = path.parent / ("dbi-symlink-" + path.name)
        try:
            symlink.symlink_to(path, target_is_directory=True)
            rejected({**env, "DBI_GIS_WORKER_ROOT": str(symlink)})
        finally:
            symlink.unlink(missing_ok=True)

        if os.name == "posix":
            path.chmod(0o755)
            rejected(env)
            path.chmod(0o700)
            assert stat.S_IMODE(path.stat().st_mode) == 0o700

        events: list[tuple] = []
        store = object()
        factory = object()
        class FakeRuntime:
            def start(self):
                events.append(("start",))

            def require_session_factory(self):
                events.append(("db",))
                return factory

            def stop(self):
                events.append(("stop",))

        class FakeWorker:
            def __init__(self, session_factory, object_store, converter, *, workspace_root):
                assert session_factory is factory
                assert object_store is store
                assert converter is mock_converter
                assert workspace_root == path
                events.append(("worker",))

            def process_one(self, *, tenant_ref):
                assert tenant_ref == "tenant-one"
                events.append(("claim",))
                return "prepared"

        def mock_converter(source, output_dir):
            raise AssertionError("En bootstrap no se convierte un archivo real.")

        def store_factory(values):
            assert values["DBI_STORAGE_BACKEND"] == "s3"
            assert values["DBI_GIS_WORKER_ROOT"] == root
            events.append(("store",))
            return store

        outcome = run_one(
            tenant_ref="tenant-one", environ=env,
            runtime_factory=FakeRuntime, store_factory=store_factory,
            worker_factory=FakeWorker, converter=mock_converter,
        )
        assert outcome == "prepared"
        assert events == [("store",), ("start",), ("db",), ("worker",), ("claim",), ("stop",)]
        assert os.environ.get("PROJ_NETWORK") == "OFF"
        assert os.environ.get("GDAL_PAM_ENABLED") == "NO"

        events.clear()
        class BrokenWorker(FakeWorker):
            def process_one(self, *, tenant_ref):
                raise RuntimeError("worker failure (controlled)")

        try:
            run_one(
                tenant_ref="tenant-one", environ=env, runtime_factory=FakeRuntime,
                store_factory=store_factory, worker_factory=BrokenWorker, converter=mock_converter,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("Se esperaba propagar el error del worker.")
        assert events[-1] == ("stop",)

        events.clear()
        try:
            run_one(
                tenant_ref="tenant-one", environ=env, runtime_factory=FakeRuntime,
                store_factory=lambda _: None, worker_factory=FakeWorker, converter=mock_converter,
            )
        except DBIGISWorkerConfigurationError:
            pass
        else:
            raise AssertionError("No puede ejecutar sin almacén S3")
        assert events == []

    print("Worker GIS S3: entorno, tenant, workspace, provider, limpieza y no publicación aprobados.")


if __name__ == "__main__":
    run()
