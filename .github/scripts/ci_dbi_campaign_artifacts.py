"""Barrera estática del catálogo técnico Campaign sin tocar Density."""

from __future__ import annotations

import ast
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"

import sys

sys.path.insert(0, str(BACKEND))

from app.dbi.campaigns.artifacts import (  # noqa: E402
    DBICampaignArtifactRegistration,
    DBICampaignArtifactSourceKind,
    DBICampaignArtifactType,
    _ANALYSIS_ROLE_BY_TYPE,
)

EXPECTED_TYPES = {
    "orthophoto_source",
    "boundary",
    "validated_inventory",
    "density_hexagons",
    "planting_candidates",
    "operational_priority",
    "kde",
    "exclusions",
    "technical_report",
    "sampling_plan",
    "sampling_points",
    "field_observations",
}
FROZEN_STAGES = (
    "validate_environment",
    "validate_raster",
    "validate_boundary",
    "clip_raster",
    "generate_tiles",
    "run_yolo",
    "georeference_detections",
    "export_raw_gis",
    "deduplicate_detections",
    "calculate_statistics",
    "analyze_spatial_pattern",
    "generate_hex_density",
    "detect_planting_opportunities",
    "prioritize_planting_opportunities",
    "generate_kde_density",
    "generate_cartographic_package",
    "generate_technical_report",
)


def _density_stage_keys() -> tuple[str, ...]:
    path = BACKEND / "app" / "api" / "v1" / "dbi_density_local.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "STAGES" for target in node.targets):
                values: list[str] = []
                if isinstance(node.value, (ast.Tuple, ast.List)):
                    for item in node.value.elts:
                        if isinstance(item, (ast.Tuple, ast.List)) and item.elts:
                            key = item.elts[0]
                            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                values.append(key.value)
                return tuple(values)
    raise AssertionError("No se encontró STAGES en dbi_density_local.py")


def main() -> None:
    assert {item.value for item in DBICampaignArtifactType} == EXPECTED_TYPES
    assert {item.value for item in DBICampaignArtifactSourceKind} == {
        "input_asset",
        "analysis_artifact",
        "domain_record",
    }

    assert "pipeline_state" not in set(_ANALYSIS_ROLE_BY_TYPE.values())
    assert "pipeline_manifest" not in set(_ANALYSIS_ROLE_BY_TYPE.values())
    assert DBICampaignArtifactType.PLANTING_CANDIDATES not in _ANALYSIS_ROLE_BY_TYPE
    assert _ANALYSIS_ROLE_BY_TYPE[DBICampaignArtifactType.OPERATIONAL_PRIORITY] == "planting_priority"

    valid = DBICampaignArtifactRegistration(
        artifact_type="technical_report",
        source_kind="analysis_artifact",
        source_ref="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        sha256="a" * 64,
        version=1,
    )
    assert valid.version == 1

    for invalid in (
        {**valid.model_dump(), "sha256": "no-es-sha"},
        {**valid.model_dump(), "version": 0},
    ):
        try:
            DBICampaignArtifactRegistration.model_validate(invalid)
        except ValidationError:
            pass
        else:
            raise AssertionError("Contrato de CampaignArtifact aceptó datos inválidos.")

    assert _density_stage_keys() == FROZEN_STAGES

    bridge = ROOT / "services" / "banana-density" / "web_bridge.py"
    bridge_source = bridge.read_text(encoding="utf-8")
    assert "campaign_artifact" not in bridge_source.lower()

    print("Campaign artifacts: contrato final, aislamiento y 17 etapas aprobados.")


if __name__ == "__main__":
    main()
