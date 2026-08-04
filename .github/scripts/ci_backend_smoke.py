"""Smoke test del backend sin conexiones externas ni migraciones."""

from __future__ import annotations

import os

from ci_dbi_admin_actor import main as validate_dbi_admin_actor
from ci_dbi_admin_mutation_routes import (
    main as validate_dbi_admin_mutation_routes,
)
from ci_dbi_admin_principal_routes import (
    main as validate_dbi_admin_principal_routes,
)
from ci_dbi_admin_routes import main as validate_dbi_admin_routes
from ci_dbi_admin_schemas import main as validate_dbi_admin_schemas
from ci_dbi_asset_api import main as validate_dbi_asset_api
from ci_dbi_asset_multipart_persistence import (
    main as validate_dbi_asset_multipart_persistence,
)
from ci_dbi_asset_multipart_application import (
    main as validate_dbi_asset_multipart_application,
)
from ci_dbi_asset_multipart_lifecycle_service import (
    main as validate_dbi_asset_multipart_lifecycle_service,
)
from ci_dbi_asset_multipart_api import (
    main as validate_dbi_asset_multipart_api,
)
from ci_dbi_asset_multipart_policy import (
    main as validate_dbi_asset_multipart_policy,
)
from ci_dbi_asset_multipart_provider import (
    main as validate_dbi_asset_multipart_provider,
)
from ci_dbi_asset_multipart_repository import (
    main as validate_dbi_asset_multipart_repository,
)
from ci_dbi_asset_multipart_s3 import main as validate_dbi_asset_multipart_s3
from ci_dbi_asset_multipart_upload_service import (
    main as validate_dbi_asset_multipart_upload_service,
)
from ci_dbi_asset_quarantine_cleanup_api import (
    main as validate_dbi_asset_quarantine_cleanup_api,
)
from ci_dbi_asset_registration import main as validate_dbi_asset_registration
from ci_dbi_asset_repository import main as validate_dbi_asset_repository
from ci_dbi_asset_quarantine_cleanup import (
    main as validate_dbi_asset_quarantine_cleanup,
)
from ci_dbi_asset_retirement_service import (
    main as validate_dbi_asset_retirement_service,
)
from ci_dbi_asset_service import main as validate_dbi_asset_service
from ci_dbi_asset_upload_service import main as validate_dbi_asset_upload_service
from ci_dbi_asset_verification import main as validate_dbi_asset_verification
from ci_dbi_flight_source_manifest import (
    main as validate_dbi_flight_source_manifest,
)
from ci_dbi_storage_contracts import main as validate_dbi_storage_contracts
from ci_dbi_storage_memory import main as validate_dbi_storage_memory
from ci_dbi_storage_metrics import main as validate_dbi_storage_metrics
from ci_dbi_storage_s3 import main as validate_dbi_storage_s3
from ci_dbi_storage_sdk_dependencies import (
    main as validate_dbi_storage_sdk_dependencies,
)


def main() -> None:
    """Valida administración, activos y almacenamiento sin servicios externos."""

    validate_dbi_admin_actor()
    validate_dbi_admin_schemas()
    validate_dbi_admin_routes()
    validate_dbi_admin_mutation_routes()
    validate_dbi_admin_principal_routes()
    validate_dbi_asset_registration()
    validate_dbi_asset_multipart_policy()
    validate_dbi_asset_multipart_persistence()
    validate_dbi_asset_multipart_repository()
    validate_dbi_asset_multipart_application()
    validate_dbi_asset_multipart_provider()
    validate_dbi_asset_multipart_s3()
    validate_dbi_asset_multipart_upload_service()
    validate_dbi_asset_multipart_lifecycle_service()
    validate_dbi_asset_multipart_api()
    validate_dbi_asset_repository()
    validate_dbi_asset_quarantine_cleanup()
    validate_dbi_asset_quarantine_cleanup_api()
    validate_dbi_asset_retirement_service()
    validate_dbi_asset_service()
    validate_dbi_asset_upload_service()
    validate_dbi_asset_verification()
    validate_dbi_asset_api()
    validate_dbi_flight_source_manifest()
    validate_dbi_storage_contracts()
    validate_dbi_storage_memory()
    validate_dbi_storage_metrics()
    validate_dbi_storage_sdk_dependencies()
    validate_dbi_storage_s3()

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
