"""Valida contratos API-worker y estados sin servicios externos."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = (
    REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
)
DENSITY_SOURCE = (
    REPOSITORY_ROOT
    / "services"
    / "banana-density"
    / "src"
)
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(DENSITY_SOURCE))

from app.dbi.jobs import (  # noqa: E402
    AnalysisJobStatus,
    InvalidAnalysisJobTransition,
    evaluate_analysis_job_transition,
    is_terminal_analysis_job_status,
)
from app.schemas.dbi_analysis_jobs import (  # noqa: E402
    AgronomicFinding,
    AnalysisJobCommand,
    AnalysisJobInputs,
    AnalysisJobResult,
    ArtifactManifest,
    ArtifactRole,
    FindingClassification,
    FindingConfidence,
    PipelineStage,
    ProfessionalReview,
    ProfessionalReviewStatus,
)
from banana_analyzer.worker_contract import (  # noqa: E402
    WorkerCommandValidationError,
    parse_analysis_job_command,
)
from banana_analyzer.pipeline_orchestrator import (  # noqa: E402
    ALL_STAGE_KEYS,
)


def build_command_payload() -> dict[str, object]:
    """Construye un comando válido sin rutas ni activos reales."""

    command = AnalysisJobCommand(
        request_id="request-contract-check",
        correlation_id="correlation-contract-check",
        job_id="job-contract-check",
        tenant_id="tenant-contract-check",
        farm_id="farm-contract-check",
        lot_id="lot-contract-check",
        inputs=AnalysisJobInputs(
            orthophoto_asset_id="asset-orthophoto-check",
            boundary_asset_id="asset-boundary-check",
            exclusions_asset_id=None,
        ),
        model_version_id="model-approved-check",
        pipeline_config_version="pipeline-config-check",
        requested_by="user-contract-check",
    )
    return command.model_dump(mode="json")


def expect_validation_error(callback: object) -> None:
    """Exige que un callable rechace la entrada."""

    try:
        callback()  # type: ignore[operator]
    except (ValidationError, WorkerCommandValidationError, ValueError):
        return
    raise AssertionError("La entrada inválida fue aceptada.")


def validate_command_parity() -> None:
    """Comprueba paridad estricta entre API y worker."""

    payload = build_command_payload()
    parsed = parse_analysis_job_command(payload)

    assert payload["schema_version"] == "analysis-job-command.v1"
    assert parsed.job_id == payload["job_id"]
    assert parsed.inputs.orthophoto_asset_id == (
        payload["inputs"]["orthophoto_asset_id"]  # type: ignore[index]
    )

    serialized = AnalysisJobCommand.model_validate(payload).model_dump_json()
    for forbidden in (
        "http://",
        "https://",
        "file://",
        "/tmp/",
        "\\",
        "password",
        "secret",
    ):
        assert forbidden not in serialized.lower()

    with_extra = {**payload, "unexpected_field": True}
    expect_validation_error(
        lambda: AnalysisJobCommand.model_validate(with_extra)
    )
    expect_validation_error(
        lambda: parse_analysis_job_command(with_extra)
    )

    local_path = dict(payload)
    local_path["inputs"] = {
        **payload["inputs"],  # type: ignore[arg-type]
        "orthophoto_asset_id": "/tmp/private-orthophoto.tif",
    }
    expect_validation_error(
        lambda: AnalysisJobCommand.model_validate(local_path)
    )
    expect_validation_error(
        lambda: parse_analysis_job_command(local_path)
    )


def validate_result_and_manifest() -> None:
    """Comprueba procedencia, huellas y revisión profesional."""

    assert {stage.value for stage in PipelineStage} == set(ALL_STAGE_KEYS)

    now = datetime.now(timezone.utc)
    artifact = ArtifactManifest(
        artifact_id="artifact-inventory-check",
        job_id="job-contract-check",
        role=ArtifactRole.VALIDATED_INVENTORY,
        object_key="jobs/job-contract-check/inventory.gpkg",
        content_type="application/geopackage+sqlite3",
        size_bytes=1024,
        sha256="a" * 64,
        produced_by_stage=PipelineStage.DEDUPLICATE_DETECTIONS,
        crs="EPSG-32717",
        created_at=now,
    )
    finding = AgronomicFinding(
        finding_id="finding-density-check",
        job_id="job-contract-check",
        classification=FindingClassification.INFERENCE,
        statement="Resultado estructural de validación sin dato real.",
        source_artifact_ids=[artifact.artifact_id],
        technical_source_refs=["method-density-check"],
        model_version_id="model-approved-check",
        confidence=FindingConfidence(
            level="medium",
            score=None,
            method="confidence-method-check",
        ),
        professional_review=ProfessionalReview(
            status=ProfessionalReviewStatus.PENDING,
        ),
    )
    result = AnalysisJobResult(
        correlation_id="correlation-contract-check",
        job_id="job-contract-check",
        attempt_id="attempt-contract-check",
        status="succeeded",
        pipeline_build="pipeline-build-check",
        started_at=now,
        finished_at=now,
        artifacts=[artifact],
        metrics={"contract_check": 1},
        findings=[finding],
    )
    payload = result.model_dump(mode="json")
    assert payload["schema_version"] == "analysis-job-result.v1"
    assert payload["artifacts"][0]["schema_version"] == (
        "artifact-manifest.v1"
    )
    assert payload["findings"][0]["classification"] == "inference"
    assert payload["findings"][0]["professional_review"]["status"] == (
        "pending"
    )

    invalid_manifest = artifact.model_dump(mode="json")
    invalid_manifest["object_key"] = "file:///tmp/inventory.gpkg"
    expect_validation_error(
        lambda: ArtifactManifest.model_validate(invalid_manifest)
    )
    invalid_manifest = artifact.model_dump(mode="json")
    invalid_manifest["sha256"] = "not-a-sha256"
    expect_validation_error(
        lambda: ArtifactManifest.model_validate(invalid_manifest)
    )
    invalid_manifest = artifact.model_dump(mode="json")
    invalid_manifest["size_bytes"] = 0
    expect_validation_error(
        lambda: ArtifactManifest.model_validate(invalid_manifest)
    )


def validate_state_machine() -> None:
    """Comprueba transiciones, idempotencia y reintento autorizado."""

    valid = (
        (AnalysisJobStatus.ACCEPTED, AnalysisJobStatus.QUEUED),
        (AnalysisJobStatus.QUEUED, AnalysisJobStatus.RUNNING),
        (AnalysisJobStatus.RUNNING, AnalysisJobStatus.SUCCEEDED),
        (
            AnalysisJobStatus.QUEUED,
            AnalysisJobStatus.CANCEL_REQUESTED,
        ),
        (
            AnalysisJobStatus.CANCEL_REQUESTED,
            AnalysisJobStatus.CANCELED,
        ),
    )
    for current, target in valid:
        decision = evaluate_analysis_job_transition(current, target)
        assert decision.changed is True

    duplicate = evaluate_analysis_job_transition(
        AnalysisJobStatus.RUNNING,
        AnalysisJobStatus.RUNNING,
    )
    assert duplicate.changed is False

    try:
        evaluate_analysis_job_transition(
            AnalysisJobStatus.FAILED,
            AnalysisJobStatus.QUEUED,
        )
    except InvalidAnalysisJobTransition:
        pass
    else:
        raise AssertionError("El reintento no autorizado fue aceptado.")

    retry = evaluate_analysis_job_transition(
        AnalysisJobStatus.FAILED,
        AnalysisJobStatus.QUEUED,
        retry_authorized=True,
    )
    assert retry.changed is True
    assert retry.retry_authorized is True

    for terminal in (
        AnalysisJobStatus.SUCCEEDED,
        AnalysisJobStatus.CANCELED,
    ):
        assert is_terminal_analysis_job_status(terminal)
        try:
            evaluate_analysis_job_transition(
                terminal,
                AnalysisJobStatus.QUEUED,
            )
        except InvalidAnalysisJobTransition:
            pass
        else:
            raise AssertionError("Un estado terminal permitió reabrirse.")


def validate_component_isolation() -> None:
    """Impide que el contrato ejecute o importe el pipeline."""

    worker_source = (
        DENSITY_SOURCE
        / "banana_analyzer"
        / "worker_contract.py"
    ).read_text(encoding="utf-8").lower()
    backend_source = (
        BACKEND_ROOT
        / "app"
        / "schemas"
        / "dbi_analysis_jobs.py"
    ).read_text(encoding="utf-8").lower()

    for forbidden in (
        "pipeline_orchestrator",
        "run_full_pipeline",
        "subprocess",
        "pathlib",
        "open(",
        "write_text",
        "mkdir",
        "app.",
    ):
        assert forbidden not in worker_source

    for forbidden in (
        "banana_analyzer",
        "services.",
        "database_url",
        "create_engine",
        "sessionmaker",
    ):
        assert forbidden not in backend_source


def main() -> None:
    """Ejecuta todas las barreras del contrato geoespacial."""

    validate_command_parity()
    validate_result_and_manifest()
    validate_state_machine()
    validate_component_isolation()
    print("Contrato de trabajo geoespacial: validación offline aprobada.")


if __name__ == "__main__":
    main()
