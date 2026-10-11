"""Pruebas offline de configuración S3 opt-in del portal DALGORO.

Ninguna conexión real, cuenta AWS, Render ni material secreto durante CI.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_s3_bootstrap.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-s3-bootstrap")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from app.dbi.storage_bootstrap import (  # noqa: E402
    DBIStorageBootstrapError,
    create_configured_object_store,
    s3_config_from_environment,
)
from app.main import app  # noqa: E402

SECRETS = {
    "DBI_STORAGE_BACKEND": "s3",
    "DBI_ENVIRONMENT": "production",
    "DBI_S3_ENDPOINT_URL": "https://private-objects.example",
    "DBI_S3_BUCKET": "dalgoro-private-objects",
    "DBI_S3_REGION": "us-east-1",
    "DBI_S3_ACCESS_KEY_ID": "fake-KEY-WITH-SENTINEL",
    "DBI_S3_SECRET_ACCESS_KEY": "fake-SECRET-WITH-SENTINEL",
}
sentinel = "SENTINEL"


def fails(values, expected: str):
    try:
        create_configured_object_store(values, s3_factory=lambda x: x, local_factory=lambda p: p)
    except DBIStorageBootstrapError as error:
        assert expected in str(error)
        assert sentinel not in str(error)
    else:
        raise AssertionError("Configuración insegura permitida.")


def run():
    config = s3_config_from_environment(SECRETS)
    assert config.endpoint_url == "https://private-objects.example"
    assert config.verify_tls is True
    assert config.max_object_size_bytes == 64 * 1024 * 1024
    assert sentinel not in repr(config)
    factory_config = create_configured_object_store(SECRETS, s3_factory=lambda x: x)
    assert factory_config is not None and factory_config.bucket == "dalgoro-private-objects"
    assert create_configured_object_store({"DBI_ENVIRONMENT": "production"}) is None
    assert create_configured_object_store({"DBI_ENVIRONMENT": "staging"}) is None
    fails({**SECRETS, "DBI_S3_ENDPOINT_URL": "http://127.0.0.1:9000"}, "HTTPS")
    fails({**SECRETS, "DBI_S3_SECRET_ACCESS_KEY": ""}, "Faltan")
    fails({**SECRETS, "DBI_LOCAL_STORAGE_ROOT": "/tmp/private"}, "mezcles")
    fails({"DBI_ENVIRONMENT": "production", "DBI_LOCAL_STORAGE_ROOT": "/tmp/private"}, "efímero")
    fails({"DBI_ENVIRONMENT": "production", "DBI_STORAGE_BACKEND": "local"}, "prohibido")
    fails({"DBI_ENVIRONMENT": "production", "DBI_STORAGE_BACKEND": "memory"}, "debe")
    assert create_configured_object_store({
        "DBI_ENVIRONMENT": "development", "DBI_STORAGE_BACKEND": "local",
        "DBI_LOCAL_STORAGE_ROOT": "/tmp/development-private",
    }, local_factory=lambda p: p) == Path("/tmp/development-private")
    assert create_configured_object_store({
        "DBI_ENVIRONMENT": "development", "LOCALAPPDATA": "/tmp/win-profile",
    }, local_factory=lambda p: p) == Path("/tmp/win-profile/DALGORO/DBI/storage")

    # Startup S3 sin IO; la aplicación enlaza exactamente el puerto inyectado.
    with patch.dict(os.environ, SECRETS, clear=True):
        with patch("app.dbi.runtime.DBIRuntime.start"), patch("app.dbi.runtime.DBIRuntime.stop"):
            with patch("app.main.create_configured_object_store", return_value=object()) as binding:
                with TestClient(app) as client:
                    assert hasattr(client.app.state, "dbi_object_store")
                    assert not hasattr(client.app.state, "dbi_raster_tile_renderer")
                assert binding.call_count == 1
                assert not hasattr(app.state, "dbi_object_store")

    # Configuración defectuosa no permite arrancar ni dejar runtime colgado.
    with patch.dict(os.environ, {**SECRETS, "DBI_S3_ENDPOINT_URL": "http://invalid"}, clear=True):
        # Parchar solamente el runtime de base, no la selección del S3.
        with patch("app.dbi.runtime.DBIRuntime.start"), patch("app.dbi.runtime.DBIRuntime.stop") as stopped:
            try:
                with TestClient(app):
                    pass
            except DBIStorageBootstrapError:
                pass
            else:
                raise AssertionError("Arranque S3 inseguro admitido.")
            assert stopped.call_count == 1

    print("S3 DBI: selección opt-in, HTTPS, secretos, aislamiento Render, lifespan/cleanup OK.")


if __name__ == "__main__":
    run()
