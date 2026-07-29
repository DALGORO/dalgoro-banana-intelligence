"""Valida el contrato cartográfico sin bases ni servicios externos."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import ValidationError


EXPECTED_LAYER_TYPES = {
    "rgb",
    "ndvi",
    "ndre",
    "density",
    "anomalies",
    "inspections",
    "production",
    "sst",
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def validate_contract() -> None:
    """Comprueba versión, catálogo, vacío inicial y campos estrictos."""

    from app.schemas.dbi_map import (
        FarmMapTimelineResponse,
        build_empty_farm_map_timeline,
    )

    response = build_empty_farm_map_timeline("farm-contract-check")
    payload = response.model_dump(mode="json")

    assert payload["schema_version"] == "farm-map-timeline.v1"
    assert payload["farm_id"] == "farm-contract-check"
    assert payload["status"] == "awaiting_data"
    assert payload["timeline"] == []
    assert payload["comparison"] == {
        "minimum_dates": 2,
        "available_dates": [],
        "enabled": False,
    }
    assert {
        item["layer_type"] for item in payload["available_layers"]
    } == EXPECTED_LAYER_TYPES

    serialized = response.model_dump_json()
    for forbidden in ("http://", "https://", "file://", "localhost", "\\"):
        assert forbidden not in serialized

    try:
        FarmMapTimelineResponse.model_validate(
            {**payload, "unexpected_contract_field": True}
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("El contrato aceptó un campo desconocido.")


def validate_endpoint() -> None:
    """Comprueba autenticación, validación del ID y respuesta HTTP."""

    os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
    os.environ["JWT_SECRET"] = "dbi-map-ci-placeholder"
    os.environ["ENABLE_DOCS"] = "0"

    from fastapi.testclient import TestClient

    from app.api.deps import current_user
    from app.main import app

    with TestClient(app) as anonymous_client:
        anonymous = anonymous_client.get(
            "/api/v1/dbi/farms/farm-contract-check/map/timeline"
        )
    assert anonymous.status_code in {401, 403}, anonymous.text

    app.dependency_overrides[current_user] = lambda: object()
    try:
        with TestClient(app) as client:
            valid = client.get(
                "/api/v1/dbi/farms/farm-contract-check/map/timeline"
            )
            invalid = client.get(
                "/api/v1/dbi/farms/farm%20with%20spaces/map/timeline"
            )
    finally:
        app.dependency_overrides.clear()

    assert valid.status_code == 200, valid.text
    assert valid.json()["timeline"] == []
    assert invalid.status_code == 422, invalid.text


def validate_frontend_contract() -> None:
    """Evita divergencia entre el contrato Python y su consumidor TypeScript."""

    feature_path = (
        REPOSITORY_ROOT
        / "apps"
        / "platform-web"
        / "frontend"
        / "src"
        / "features"
        / "mapTimeline.ts"
    )
    page_path = (
        REPOSITORY_ROOT
        / "apps"
        / "platform-web"
        / "frontend"
        / "src"
        / "pages"
        / "FarmMapTimeline.tsx"
    )
    feature_source = feature_path.read_text(encoding="utf-8")
    page_source = page_path.read_text(encoding="utf-8")

    assert "farm-map-timeline.v1" in feature_source
    for layer_type in EXPECTED_LAYER_TYPES:
        assert f'"{layer_type}"' in feature_source

    assert "sources: {}" in page_source
    for forbidden in ("http://", "https://", "file://"):
        assert forbidden not in page_source


def main() -> None:
    """Ejecuta todas las barreras cartográficas."""

    validate_contract()
    validate_endpoint()
    validate_frontend_contract()
    print("Contrato de mapa cronológico: validación offline aprobada.")


if __name__ == "__main__":
    main()
