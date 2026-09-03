"""Adaptador de linaje y runtime Alembic para DBI-RASTER-001."""

from __future__ import annotations

import ci_dbi_migration_control_base as base

base.HEAD = "dbi_0015_raster_products"
base.KNOWN = set(base.KNOWN) | {"dbi_0014_analysis_results", base.HEAD}

RASTER_AUTHORIZED_RUNTIME = {
    **base.AUTHORIZED_RUNTIME,
    "GITHUB_WORKFLOW": "DBI raster integration",
    "GITHUB_WORKFLOW_REF": (
        "DALGORO/dalgoro-banana-intelligence/"
        ".github/workflows/dbi-raster-integration.yml@refs/pull/77/merge"
    ),
    "GITHUB_JOB": "raster-postgis",
}


def validate_authorized_runtime_with_raster() -> None:
    authorized_runtimes = (
        base.AUTHORIZED_RUNTIME,
        base.ASSET_AUTHORIZED_RUNTIME,
        base.ANALYSIS_JOB_AUTHORIZED_RUNTIME,
        base.DELIVERY_AUTHORIZED_RUNTIME,
        base.MODEL_REGISTRY_AUTHORIZED_RUNTIME,
        base.WORKER_AUTHORIZED_RUNTIME,
        base.RESULT_AUTHORIZED_RUNTIME,
        RASTER_AUTHORIZED_RUNTIME,
    )
    assert len(base.DBI_AUTHORIZED_GITHUB_WORKFLOWS) == len(authorized_runtimes)

    for authorized in authorized_runtimes:
        for event_name in ("pull_request", "push", "workflow_dispatch"):
            runtime = dict(authorized)
            runtime["GITHUB_EVENT_NAME"] = event_name
            assert base.is_authorized_github_actions_runtime(runtime) is True

        for field in authorized:
            runtime = dict(authorized)
            runtime[field] = "valor-no-autorizado"
            assert base.is_authorized_github_actions_runtime(runtime) is False

        missing_workflow_ref = dict(authorized)
        missing_workflow_ref.pop("GITHUB_WORKFLOW_REF")
        assert base.is_authorized_github_actions_runtime(missing_workflow_ref) is False

    for original in authorized_runtimes:
        for other in authorized_runtimes:
            if original is other:
                continue
            for field in ("GITHUB_WORKFLOW", "GITHUB_WORKFLOW_REF", "GITHUB_JOB"):
                mixed = dict(original)
                mixed[field] = other[field]
                assert base.is_authorized_github_actions_runtime(mixed) is False


base.validate_authorized_runtime = validate_authorized_runtime_with_raster


if __name__ == "__main__":
    base.main()
