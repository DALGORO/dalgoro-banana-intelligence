"""Pruebas offline de arranque S3: opt-in, secretos y limpieza segura."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_s3_bootstrap.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-s3-bootstrap")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "platform-web" / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from app.dbi.storage_bootstrap import (  # noqa: E402
    DBIStorageBootstrapError, resolve_dbi_object_store,
)
from app.main import app  # noqa: E402

S3_INPUT = {
    "DBI_STORAGE_PROVIDER": "s3",
    "DBI_ENVIRONMENT": "staging",
    "DBI_DATABASE_URL": "postgresql+psycopg://ci@localhost/dbi",
    "DBI_S3_ENDPOINT_URL": "https://objects.example.org",
    "DBI_S3_BUCKET": "dalgoro-gis-private",
    "DBI_S3_REGION": "us-east-1",
    "DBI_S3_ACCESS_KEY_ID": "ci-example-access",
    "DBI_S3_SECRET_ACCESS_KEY": "S3-SECRET-NEVER-LOG-THIS",
}


def expect_invalid(config, fragment=None):
    try:
        resolve_dbi_object_store(config, lambda: object(), s3_provider=lambda c: object())
    except DBIStorageBootstrapError as error:
        if fragment:
            assert fragment in str(error), str(error)
        assert S3_INPUT["DBI_S3_SECRET_ACCESS_KEY"] not in str(error)
    else:
        raise AssertionError("Configuración privada S3 inválida fue admitida")


def validate_selection():
    called = []
    local = object()
    def local_factory():
        called.append(True)
        return local

    assert resolve_dbi_object_store({}, local_factory) is local
    assert len(called) == 1
    assert resolve_dbi_object_store({"DBI_STORAGE_PROVIDER": "disabled"}, local_factory) is None
    assert len(called) == 1
    assert resolve_dbi_object_store({
        "DBI_STORAGE_PROVIDER": "local", "DBI_ENVIRONMENT": "development",
    }, local_factory) is local
    assert len(called) == 2
    expect_invalid({"DBI_STORAGE_PROVIDER": "local", "DBI_ENVIRONMENT": "production"}, "local")
    expect_invalid({"DBI_STORAGE_PROVIDER": "no-such-provider"}, "proveedor")
    expect_invalid({"DBI_STORAGE_PROVIDER": "s3", "DBI_ENVIRONMENT": "production"}, "Faltan")

    created = []
    def s3_factory(config):
        created.append(config)
        return object()
    provider = resolve_dbi_object_store(S3_INPUT, local_factory, s3_provider=s3_factory)
    assert provider is not None
    assert len(created) == 1
    config = created[0]
    assert config.endpoint_url == "https://objects.example.org"
    assert config.bucket == "dalgoro-gis-private"
    assert config.verify_tls is True
    assert config.max_object_size_bytes == 64 * 1024 * 1024
    assert len(called) == 2  # S3 nunca cae al proveedor local.

    expect_invalid({**S3_INPUT, "DBI_S3_ENDPOINT_URL": "http://objects.example.org"}, "HTTPS")
    expect_invalid({**S3_INPUT, "DBI_S3_BUCKET": ""}, "DBI_S3_BUCKET")
    expect_invalid({**S3_INPUT, "DBI_S3_SECRET_ACCESS_KEY": ""}, "DBI_S3_SECRET_ACCESS_KEY")
    expect_invalid({**S3_INPUT, "DBI_DATABASE_URL": ""}, "DBI_DATABASE_URL")
    expect_invalid({**S3_INPUT, "DBI_S3_ENDPOINT_URL": "https://user:pass@objects.example.org"}, "política")


def validate_lifespan_cleanup():
    class Runtime:
        def __init__(self):
            self.started = self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    runtime = Runtime()
    provider = object()
    with patch("app.main.DBIRuntime", return_value=runtime):
        with patch("app.main.resolve_dbi_object_store", return_value=provider):
            with TestClient(app) as client:
                assert client.app.state.dbi_object_store is provider
                assert not hasattr(client.app.state, "dbi_raster_tile_renderer")
                assert runtime.started is True
                assert runtime.stopped is False
    assert runtime.stopped is True
    assert not hasattr(app.state, "dbi_object_store")

    broken = Runtime()
    with patch("app.main.DBIRuntime", return_value=broken):
        with patch("app.main.resolve_dbi_object_store", side_effect=DBIStorageBootstrapError("invalid")):
            try:
                with TestClient(app):
                    pass
            except DBIStorageBootstrapError:
                pass
            else:
                raise AssertionError("S3 inválido no bloqueó arranque")
    assert broken.started and broken.stopped
    assert not hasattr(app.state, "dbi_object_store")


if __name__ == "__main__":
    validate_selection()
    validate_lifespan_cleanup()
    print("Bootstrap S3 DBI: opt-in, HTTPS, sin fallback, secretos y cleanup aprobados.")
