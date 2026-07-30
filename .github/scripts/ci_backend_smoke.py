"""Smoke test del backend sin conexiones externas ni migraciones."""

from __future__ import annotations

import os


def main() -> None:
    """Importa FastAPI y comprueba los endpoints exentos de base de datos."""
    os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
    os.environ["JWT_SECRET"] = "dbi-ci-placeholder"
    os.environ["ENABLE_DOCS"] = "0"

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        health_response = client.get("/api/v1/health")
        root_response = client.get("/")

    assert health_response.status_code == 200, health_response.text
    assert health_response.json() == {"status": "ok"}
    assert root_response.status_code == 200, root_response.text

    print("Backend smoke test: importación y healthcheck aprobados.")


if __name__ == "__main__":
    main()
