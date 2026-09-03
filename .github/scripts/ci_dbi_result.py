"""Pruebas offline de contratos y fronteras de DBI-RESULT-001."""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.delivery.contracts import prepare_delivery_payload  # noqa: E402
from app.dbi.results.contracts import (  # noqa: E402
    DBIResultIngestionConflict,
    canonical_json,
    prepare_analysis_result,
)
from app.schemas.dbi_analysis_jobs import (  # noqa: E402
    AgronomicFinding,
    AnalysisJobResult,
    ArtifactManifest,
    ArtifactRole,
    FindingClassification,
    FindingConfidence,
    PipelineStage,
    ProfessionalReview,
    ProfessionalReviewStatus,
)

NOW = datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc)
JOB_ID = UUID("91000000-0000-4000-8000-000000000001")
ATTEMPT_ID = UUID("92000000-0000-4000-8000-000000000001")
ARTIFACT_ID = UUID("93000000-0000-4000-8000-000000000001")
OTHER_ARTIFACT_ID = UUID("93000000-0000-4000-8000-000000000002")


def _artifact(*, artifact_id: UUID = ARTIFACT_ID, role=ArtifactRole.HEX_DENSITY):
    return ArtifactManifest(
        artifact_id=str(artifact_id),
        job_id=str(JOB_ID),
        role=role,
        object_key=f"tenants/abc/analysis-artifacts/{artifact_id}",
        content_type="application/geopackage+sqlite3",
        size_bytes=123,
        sha256="a" * 64,
        produced_by_stage=PipelineStage.GENERATE_HEX_DENSITY,
        crs="EPSG:32717",
        created_at=NOW,
    )


def _finding(source_id: UUID = ARTIFACT_ID):
    return AgronomicFinding(
        finding_id="finding_result_ci",
        job_id=str(JOB_ID),
        classification=FindingClassification.OBSERVED,
        statement="Hallazgo observado por prueba DBI.",
        source_artifact_ids=[str(source_id)],
        technical_source_refs=[],
        model_version_id="banana_result_ci_v1",
        confidence=FindingConfidence(
            level="high",
            score=0.95,
            method="validated_inventory",
        ),
        professional_review=ProfessionalReview(
            status=ProfessionalReviewStatus.NOT_REQUIRED,
        ),
    )


def _result(**overrides):
    values = {
        "correlation_id": "correlation-result-ci",
        "job_id": str(JOB_ID),
        "attempt_id": str(ATTEMPT_ID),
        "status": "succeeded",
        "pipeline_build": "banana-density-pipeline-v1",
        "started_at": NOW,
        "finished_at": NOW,
        "artifacts": [_artifact()],
        "metrics": {"artifact_count": 1},
        "findings": [_finding()],
        "warnings": [],
        "errors": [],
    }
    values.update(overrides)
    return AnalysisJobResult(**values)


def _expect_conflict(callback) -> None:
    try:
        callback()
    except DBIResultIngestionConflict:
        return
    raise AssertionError("se esperaba DBIResultIngestionConflict.")


def validate_canonical_contract() -> None:
    result = _result()
    prepared = prepare_analysis_result(result)
    delivery = prepare_delivery_payload(result)
    assert prepared.result_sha256 == delivery.payload_sha256
    assert prepared.metrics.json_text == '{"artifact_count":1}'
    assert prepared.warnings.json_text == "[]"
    assert prepared.errors.json_text == "[]"
    assert prepared.artifact_ids == frozenset({ARTIFACT_ID})


def validate_terminal_semantics() -> None:
    _expect_conflict(
        lambda: prepare_analysis_result(
            _result(status="failed", findings=[], errors=["PIPELINE_FAILED"])
        )
    )
    _expect_conflict(
        lambda: prepare_analysis_result(
            _result(status="canceled", findings=[], errors=["CANCELED"])
        )
    )
    _expect_conflict(
        lambda: prepare_analysis_result(_result(errors=["UNEXPECTED"]))
    )

    failed = _result(
        status="failed",
        artifacts=[],
        findings=[],
        errors=["PIPELINE_FAILED"],
    )
    assert prepare_analysis_result(failed).artifact_ids == frozenset()
    canceled = _result(
        status="canceled",
        artifacts=[],
        findings=[],
        errors=["CANCELED"],
    )
    assert prepare_analysis_result(canceled).artifact_ids == frozenset()


def validate_artifact_and_finding_identity() -> None:
    _expect_conflict(
        lambda: prepare_analysis_result(
            _result(findings=[_finding(OTHER_ARTIFACT_ID)])
        )
    )
    _expect_conflict(
        lambda: prepare_analysis_result(
            _result(
                artifacts=[
                    _artifact(),
                    _artifact(
                        artifact_id=OTHER_ARTIFACT_ID,
                        role=ArtifactRole.HEX_DENSITY,
                    ),
                ],
                findings=[],
            )
        )
    )


def validate_json_safety() -> None:
    _expect_conflict(
        lambda: canonical_json(
            {"value": math.nan},
            field_name="metrics",
            max_bytes=128,
        )
    )
    _expect_conflict(
        lambda: canonical_json(
            {"payload": "x" * 200},
            field_name="metrics",
            max_bytes=32,
        )
    )


def validate_transaction_boundary() -> None:
    for relative in (
        "apps/platform-web/backend/app/dbi/results/repository.py",
        "apps/platform-web/backend/app/dbi/results/service.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert ".commit(" not in source
        assert ".rollback(" not in source
    service_source = (
        ROOT / "apps/platform-web/backend/app/dbi/results/service.py"
    ).read_text(encoding="utf-8")
    assert ".open_read(" not in service_source
    assert ".copy_to(" not in service_source
    assert ".stat(" in service_source


def main() -> None:
    validate_canonical_contract()
    validate_terminal_semantics()
    validate_artifact_and_finding_identity()
    validate_json_safety()
    validate_transaction_boundary()
    print(
        "DBI-RESULT-001 offline aprobado: canonicalización, semántica y fronteras seguras."
    )


if __name__ == "__main__":
    main()
