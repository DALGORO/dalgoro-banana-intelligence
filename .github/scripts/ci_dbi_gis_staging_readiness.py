"""Regresión de preflight GIS staging que nunca acredita despliegue real."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import os
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "banana-density"))

import portal_gis_staging_readiness as readiness  # noqa: E402

FAKE_VALUES = {
    "DBI_ENVIRONMENT": "staging",
    "DBI_DATABASE_URL": "postgresql+psycopg://fake_user:very_sensitive@localhost:5432/dbi_staging",
    "DBI_STORAGE_BACKEND": "s3",
    "DBI_S3_ENDPOINT_URL": "https://private-s3.example",
    "DBI_S3_BUCKET": "fake-private-gis",
    "DBI_S3_REGION": "us-east-1",
    "DBI_S3_ACCESS_KEY_ID": "fake-key-id",
    "DBI_S3_SECRET_ACCESS_KEY": "MY_SYNTHETIC_SECRET",
    "DBI_GIS_WORKER_TENANT": "tenant-ci",
    "DBI_GIS_WORKER_ROOT": "/tmp/dbi-staging-offline-expected-missing",
}


def call(values):
    sink = StringIO()
    with redirect_stdout(sink):
        result = readiness.main(["--offline"], values)
    output = sink.getvalue()
    assert output.count("\n") == 1
    assert "MY_SYNTHETIC_SECRET" not in output
    assert "very_sensitive" not in output
    assert "private-s3.example" not in output
    assert "fake-private-gis" not in output
    assert "tenant-ci" not in output
    assert "/tmp/" not in output
    return result, json.loads(output)


def blocked(values, reason):
    status, info = call(values)
    assert status == 2 and info["reason"] == reason, info
    assert info["deployment_readiness"] == "NOT_VERIFIED"
    assert info["offline_configuration"] == "blocked"


def run():
    # No se debe intentar abrir socket, conectar DB/S3 ni activar un claim.
    with patch.object(socket, "socket", side_effect=AssertionError("se intentó red")):
        status, info = call(FAKE_VALUES)
    assert status == 0
    assert info["offline_configuration"] == "validated"
    assert info["deployment_readiness"] == "NOT_VERIFIED"
    assert info["environment"] == "staging"
    assert info["mode"] == "offline_no_network"
    assert info["required_gis_revision"] == readiness.REQUIRED_GIS_REVISION
    assert isinstance(info["migration_code_head"], str)
    assert len(info["unverified_gates"]) == 5
    assert "staging_migration_execution_path_not_authorized" in info["unverified_gates"]

    blocked({**FAKE_VALUES, "DBI_ENVIRONMENT": "production"}, "staging_only")
    blocked({**FAKE_VALUES, "DBI_ENVIRONMENT": "development"}, "staging_only")
    blocked({**FAKE_VALUES, "DBI_GIS_WORKER_ENABLED": "1"}, "worker_must_remain_disabled")
    blocked({**FAKE_VALUES, "DBI_GIS_WORKER_ENABLED": "true"}, "worker_must_remain_disabled")
    blocked({**FAKE_VALUES, "DBI_STORAGE_BACKEND": "local"},
            "invalid_or_missing_staging_configuration")
    blocked({**FAKE_VALUES, "DBI_DATABASE_URL": FAKE_VALUES["DBI_DATABASE_URL"].replace(
        "dbi_staging", "dbi_production")},
            "invalid_or_missing_staging_configuration")
    blocked({**FAKE_VALUES, "DBI_S3_ENDPOINT_URL": "http://private-s3.example"},
            "invalid_or_missing_staging_configuration")
    blocked({**FAKE_VALUES, "DBI_S3_SECRET_ACCESS_KEY": ""},
            "invalid_or_missing_staging_configuration")
    blocked({**FAKE_VALUES, "DBI_GIS_WORKER_ROOT": "relative/path"},
            "invalid_or_missing_staging_configuration")

    with TemporaryDirectory(prefix="dbi-gis-readiness-") as folder:
        private = Path(folder) / "private"
        private.mkdir(mode=0o700)
        config = {**FAKE_VALUES, "DBI_GIS_WORKER_ROOT": str(private)}
        assert call(config)[0] == 0
        private.chmod(0o755)
        blocked(config, "invalid_or_missing_staging_configuration")
        private.chmod(0o700)
        # Nunca aceptar un grafo sin DBI 26, con forks o ciclos.
        versions = Path(folder) / "versions"
        versions.mkdir()
        with patch.object(readiness, "VERSIONS_DIR", versions):
            blocked(FAKE_VALUES, "migration_graph_invalid")
            (versions / "v1.py").write_text(
                'revision = "one"\ndown_revision = None\n', encoding="utf-8",
            )
            blocked(FAKE_VALUES, "migration_graph_invalid")
            (versions / "v2.py").write_text(
                'revision = "dbi_0026_gpkg_layer_choice"\ndown_revision = "one"\n',
                encoding="utf-8",
            )
            assert readiness.migration_head() == "dbi_0026_gpkg_layer_choice"
            (versions / "fork.py").write_text(
                'revision = "fork"\ndown_revision = "one"\n', encoding="utf-8",
            )
            blocked(FAKE_VALUES, "migration_graph_invalid")
            (versions / "fork.py").unlink()
            (versions / "v1.py").write_text(
                'revision = "one"\ndown_revision = "dbi_0026_gpkg_layer_choice"\n',
                encoding="utf-8",
            )
            blocked(FAKE_VALUES, "migration_graph_invalid")
    print("Readiness staging GIS: offline, secretos ocultos, HEAD DBI, bloqueos reales OK.")


if __name__ == "__main__":
    run()
