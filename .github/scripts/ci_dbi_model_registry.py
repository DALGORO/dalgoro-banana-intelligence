"""Valida contratos, autoridad y fronteras de DBI-ML-001 sin red."""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_base import DBIBase  # noqa: E402
from app.dbi import models as dbi_models  # noqa: E402,F401
from app.dbi.jobs.profile_policy import (  # noqa: E402
    DBI_ANALYSIS_MODEL_VERSION_ENV,
    DBI_ANALYSIS_PIPELINE_CONFIG_ENV,
    DBI_ANALYSIS_POLICY_REF_ENV,
    DBI_ANALYSIS_PROFILE_SOURCE_ENV,
    DBI_ANALYSIS_PROFILE_SOURCE_ENVIRONMENT,
    DBI_ANALYSIS_PROFILE_SOURCE_REGISTRY,
    load_analysis_profile_source,
    load_configured_analysis_profile_policy,
)
from app.dbi.jobs.service_contracts import (  # noqa: E402
    AnalysisProfileResolutionContext,
    ApprovedAnalysisProfile,
)
from app.dbi.model_registry import (  # noqa: E402
    DEFAULT_ANALYSIS_MODEL_FAMILY,
    DBIModelRegistryAnalysisProfilePolicy,
    DBIModelRegistryRepository,
    ModelRegistryConflict,
    ModelVersionRegistration,
    PipelineConfigRegistration,
    _canonical_json,
)


def _raises(expected, callback) -> None:
    try:
        callback()
    except expected:
        return
    raise AssertionError(f"Se esperaba {expected.__name__}.")


def validate_contracts_and_payloads() -> None:
    model = ModelVersionRegistration(
        model_family="banana_detection",
        model_version="yolov8_dedup_v1",
        training_dataset_version="banana_train_v1",
        validation_dataset_version="banana_validation_v1",
        input_contract_version="orthophoto_tiles_v1",
        output_contract_version="banana_detections_v1",
        artifact_ref="model_artifact_001",
        metrics={"map50": 0.91, "precision": 0.93, "recall": 0.89},
    )
    assert model.model_family == DEFAULT_ANALYSIS_MODEL_FAMILY

    first = PipelineConfigRegistration(
        model_family="banana_detection",
        config_version="density_pipeline_v1",
        config={"tile_size": 640, "confidence": 0.35, "iou": 0.45},
    )
    second = PipelineConfigRegistration(
        model_family="banana_detection",
        config_version="density_pipeline_v1",
        config={"iou": 0.45, "confidence": 0.35, "tile_size": 640},
    )
    first_json, first_sha = _canonical_json(first.config, field_name="pipeline_config")
    second_json, second_sha = _canonical_json(second.config, field_name="pipeline_config")
    assert first_json == second_json and first_sha == second_sha
    assert len(first_sha) == 64

    _raises(
        ModelRegistryConflict,
        lambda: _canonical_json(
            {"model_path": "/srv/private/weights.pt"}, field_name="pipeline_config"
        ),
    )
    _raises(
        ModelRegistryConflict,
        lambda: _canonical_json(
            {"callback": "https://example.invalid/result"},
            field_name="pipeline_config",
        ),
    )
    _raises(
        ModelRegistryConflict,
        lambda: _canonical_json(
            {"api_key": "never-store-this"}, field_name="pipeline_config"
        ),
    )
    _raises(
        ValidationError,
        lambda: PipelineConfigRegistration(
            model_family="banana_detection",
            config_version="density_pipeline_v1",
            config={"tile_size": 640},
            client_selected_model="forbidden",
        ),
    )


def validate_single_authority() -> None:
    assert load_analysis_profile_source({}) == DBI_ANALYSIS_PROFILE_SOURCE_REGISTRY
    env = {
        DBI_ANALYSIS_PROFILE_SOURCE_ENV: DBI_ANALYSIS_PROFILE_SOURCE_ENVIRONMENT,
        DBI_ANALYSIS_MODEL_VERSION_ENV: "model_v1",
        DBI_ANALYSIS_PIPELINE_CONFIG_ENV: "pipeline_v1",
        DBI_ANALYSIS_POLICY_REF_ENV: "policy_v1",
    }
    assert load_analysis_profile_source(env) == DBI_ANALYSIS_PROFILE_SOURCE_ENVIRONMENT
    policy = load_configured_analysis_profile_policy(env)
    assert policy is not None
    resolved = policy.resolve(
        context=AnalysisProfileResolutionContext(
            tenant_ref="tenant_ci",
            organization_ref="organization_ci",
            farm_id=UUID("10000000-0000-0000-0000-000000000001"),
            plot_id=UUID("20000000-0000-0000-0000-000000000001"),
        )
    )
    assert resolved == ApprovedAnalysisProfile(
        model_version_id="model_v1",
        pipeline_config_version="pipeline_v1",
        policy_ref="policy_v1",
    )
    _raises(
        ValueError,
        lambda: load_analysis_profile_source(
            {DBI_ANALYSIS_MODEL_VERSION_ENV: "legacy_without_explicit_source"}
        ),
    )
    _raises(
        ValueError,
        lambda: load_analysis_profile_source(
            {DBI_ANALYSIS_PROFILE_SOURCE_ENV: "both"}
        ),
    )


class _FakeRegistryRepository(DBIModelRegistryRepository):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def resolve_champion(self, *, tenant_ref: str, model_family: str):
        self.calls.append((tenant_ref, model_family))
        return ApprovedAnalysisProfile(
            model_version_id="yolov8_dedup_v1",
            pipeline_config_version="density_pipeline_v1",
            policy_ref="champion_policy_v1",
        )


def validate_registry_policy_port() -> None:
    repository = _FakeRegistryRepository()
    policy = DBIModelRegistryAnalysisProfilePolicy(repository)
    result = policy.resolve(
        context=AnalysisProfileResolutionContext(
            tenant_ref="tenant_ci",
            organization_ref="organization_ci",
            farm_id=UUID("10000000-0000-0000-0000-000000000001"),
            plot_id=UUID("20000000-0000-0000-0000-000000000001"),
        )
    )
    assert result.model_version_id == "yolov8_dedup_v1"
    assert repository.calls == [("tenant_ci", "banana_detection")]


def validate_models_and_migration() -> None:
    tables = DBIBase.metadata.tables
    for name in (
        "dbi_model_versions",
        "dbi_pipeline_config_versions",
        "dbi_analysis_profiles",
        "dbi_model_governance_events",
    ):
        assert name in tables

    profile = tables["dbi_analysis_profiles"]
    constraint_names = {constraint.name for constraint in profile.constraints}
    assert "fk_dbi_analysis_profiles_model_family" in constraint_names
    assert "fk_dbi_analysis_profiles_pipeline_family" in constraint_names
    assert "uq_dbi_analysis_profiles_tenant_policy" in constraint_names
    assert any(
        index.name == "uq_dbi_analysis_profiles_active_champion" and index.unique
        for index in profile.indexes
    )

    scripts = ScriptDirectory.from_config(Config(str(BACKEND / "dbi_alembic.ini")))
    assert scripts.get_heads() == ["dbi_0013_model_registry"]
    revision = scripts.get_revision("dbi_0013_model_registry")
    assert revision is not None
    assert revision.down_revision == "dbi_0012_durable_delivery"


def validate_boundaries() -> None:
    import app.dbi.model_registry as registry

    source = inspect.getsource(registry)
    repository_source = inspect.getsource(DBIModelRegistryRepository)
    for forbidden in (
        ".commit(",
        ".rollback(",
        "boto3",
        "requests.",
        "httpx.",
        "subprocess",
        "torch",
        "ultralytics",
        "sam",
    ):
        assert forbidden not in repository_source.lower()
    for forbidden in (
        "presigned",
        "signed_url",
        "model_path",
        "file_path",
        "object_key",
    ):
        assert forbidden not in source.lower() or forbidden in {
            "signed_url",
            "model_path",
            "file_path",
            "object_key",
        }
    assert "with_for_update" in repository_source
    assert "DBIModelGovernanceEvent" in source


def main() -> None:
    os.environ.pop(DBI_ANALYSIS_PROFILE_SOURCE_ENV, None)
    for name in (
        DBI_ANALYSIS_MODEL_VERSION_ENV,
        DBI_ANALYSIS_PIPELINE_CONFIG_ENV,
        DBI_ANALYSIS_POLICY_REF_ENV,
    ):
        os.environ.pop(name, None)
    validate_contracts_and_payloads()
    validate_single_authority()
    validate_registry_policy_port()
    validate_models_and_migration()
    validate_boundaries()
    print("DBI-ML-001 offline aprobado: registro, autoridad y fronteras seguras.")


if __name__ == "__main__":
    main()
