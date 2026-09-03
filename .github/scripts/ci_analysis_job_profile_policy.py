"""Valida la política provisional server-side de perfiles DBI-JOB-003."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from pydantic import ValidationError  # noqa: E402
from app.dbi.jobs.profile_policy import (  # noqa: E402
    DBI_ANALYSIS_MODEL_VERSION_ENV,
    DBI_ANALYSIS_PIPELINE_CONFIG_ENV,
    DBI_ANALYSIS_POLICY_REF_ENV,
    DBIConfiguredAnalysisProfilePolicy,
    load_configured_analysis_profile_policy,
)
from app.dbi.jobs.service_contracts import (  # noqa: E402
    AnalysisJobCreateRequest,
    AnalysisProfileResolutionContext,
)

FARM_ID = UUID("71000000-0000-4000-8000-000000000001")
PLOT_ID = UUID("72000000-0000-4000-8000-000000000001")
ORTHO_ID = UUID("73000000-0000-4000-8000-000000000001")
BOUNDARY_ID = UUID("74000000-0000-4000-8000-000000000001")


def main() -> None:
    assert load_configured_analysis_profile_policy({}) is None

    try:
        load_configured_analysis_profile_policy(
            {DBI_ANALYSIS_MODEL_VERSION_ENV: "model-ci-v1"}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Un perfil parcial debía fallar cerrado.")

    environment = {
        DBI_ANALYSIS_MODEL_VERSION_ENV: "banana-density-ci-v1",
        DBI_ANALYSIS_PIPELINE_CONFIG_ENV: "pipeline-ci-v1",
        DBI_ANALYSIS_POLICY_REF_ENV: "manual-approved-ci-v1",
    }
    policy = load_configured_analysis_profile_policy(environment)
    assert isinstance(policy, DBIConfiguredAnalysisProfilePolicy)
    profile = policy.resolve(
        context=AnalysisProfileResolutionContext(
            tenant_ref="tenant-ci",
            organization_ref="organization-ci",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
        )
    )
    assert profile.model_version_id == "banana-density-ci-v1"
    assert profile.pipeline_config_version == "pipeline-ci-v1"
    assert profile.policy_ref == "manual-approved-ci-v1"

    # El contrato HTTP no permite seleccionar perfil, modelo o pipeline.
    try:
        AnalysisJobCreateRequest(
            request_id="request-ci",
            orthophoto_asset_id=ORTHO_ID,
            boundary_asset_id=BOUNDARY_ID,
            model_version_id="attacker-model",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("El cliente no debe poder seleccionar un modelo.")

    protected = {
        DBI_ANALYSIS_MODEL_VERSION_ENV,
        DBI_ANALYSIS_PIPELINE_CONFIG_ENV,
        DBI_ANALYSIS_POLICY_REF_ENV,
    }
    assert all(name.startswith("DBI_ANALYSIS_") for name in protected)
    assert all(name not in AnalysisJobCreateRequest.model_fields for name in protected)
    print("Política de perfil DBI server-side aprobada offline.")


if __name__ == "__main__":
    main()
