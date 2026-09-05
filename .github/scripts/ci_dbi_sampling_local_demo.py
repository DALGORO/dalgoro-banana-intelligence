"""Valida que la demo local Sampling siga siendo reproducible y segura."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
SCRIPTS = BACKEND / "scripts"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(SCRIPTS))

from dbi_sampling_local_demo import (  # noqa: E402
    build_demo_feature_collection,
    write_demo,
)


def validate_determinism_and_geojson() -> None:
    first = build_demo_feature_collection()
    second = build_demo_feature_collection()
    assert first == second
    assert first["type"] == "FeatureCollection"
    assert first["metadata"]["schema_version"] == "dbi-sampling-plan.v1"
    assert first["metadata"]["profile_version"] == "sampling-local-demo-v1"
    budget = first["metadata"]["budget"]
    assert budget["primary_count"] == 26
    assert budget["reserve_count"] == 10
    assert budget["target_status"] == "within_target"

    boundaries = [
        item
        for item in first["features"]
        if item["properties"]["feature_kind"] == "boundary"
    ]
    exclusions = [
        item
        for item in first["features"]
        if item["properties"]["feature_kind"] == "exclusion"
    ]
    points = [
        item
        for item in first["features"]
        if item["properties"]["feature_kind"] == "sampling_point"
    ]
    assert len(boundaries) == 1
    assert len(exclusions) == 1
    assert len(points) == 36
    assert sum(item["properties"]["role"] == "primary" for item in points) == 26
    assert sum(item["properties"]["role"] == "reserve" for item in points) == 10

    for point in points:
        assert point["geometry"]["type"] == "Point"
        longitude, latitude = point["geometry"]["coordinates"]
        assert -180 <= longitude <= 180
        assert -90 <= latitude <= 90
        assert point["properties"]["status"] == "planned"


def validate_file_output() -> None:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "sampling-demo.geojson"
        expected = write_demo(output)
        assert output.is_file()
        loaded = json.loads(output.read_text(encoding="utf-8"))
        assert loaded == expected


def validate_static_boundaries() -> None:
    source = (SCRIPTS / "dbi_sampling_local_demo.py").read_text(
        encoding="utf-8"
    ).lower()
    for forbidden in (
        "requests.",
        "httpx.",
        "boto3",
        "create_engine",
        "sessionmaker",
        "database_url",
        "dbi_database_url",
        "subprocess",
        "credential",
        "presigned",
        "signed_url",
        "object_key",
    ):
        assert forbidden not in source
    assert "tmp" in source
    assert "build_sampling_plan" in source


def main() -> None:
    validate_determinism_and_geojson()
    validate_file_output()
    validate_static_boundaries()
    print("DBI-DEV-001 aprobado: demo local Sampling reproducible y segura.")


if __name__ == "__main__":
    main()
