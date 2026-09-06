"""Valida que Sigatoka temprana falle cerrado hasta existir evidencia suficiente."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.multispectral.sigatoka_readiness import (  # noqa: E402
    DBISigatokaReadinessPolicy,
    DBISigatokaValidationEvidence,
    evaluate_sigatoka_early_readiness,
)

MODEL_ID = UUID("70000000-0000-4000-8000-000000000080")


def _policy() -> DBISigatokaReadinessPolicy:
    return DBISigatokaReadinessPolicy(
        policy_version="sigatoka-readiness-ci-v1",
        min_held_out_farms=3,
        min_held_out_dates=4,
        min_positive_examples=40,
        min_negative_examples=60,
        min_sensitivity_recall=0.85,
        required_calibration_metric="ece",
        max_calibration_error=0.08,
    )


def _evidence() -> DBISigatokaValidationEvidence:
    return DBISigatokaValidationEvidence(
        model_version_id=MODEL_ID,
        model_version="sigatoka-early-ci-v1",
        model_status="approved",
        validation_dataset_version="multi-validation-ci-v1",
        truth_ground_contract_version="dbi-field-observation.v1",
        truth_ground_evidence_kind="observed",
        positive_foure_stages=(1, 2),
        holdout_unit="farm_date",
        held_out_farms=3,
        held_out_dates=4,
        positive_examples=40,
        negative_examples=60,
        sensitivity_recall=0.90,
        calibration_metric="ece",
        calibration_error=0.05,
        uses_single_index_rule=False,
    )


def validate_ready_contract() -> None:
    result = evaluate_sigatoka_early_readiness(_evidence(), _policy())
    assert result.decision == "ready"
    assert result.reasons == ()
    assert result.inference_allowed is True
    assert result.evidence_kind == "derived"
    assert result.inference_kind_if_emitted == "inferred"
    assert result.diagnosis_allowed is False
    assert result.agrochemical_recommendation_allowed is False
    assert result.single_index_rule_allowed is False


def validate_fail_closed() -> None:
    policy = _policy()
    base = _evidence()
    blocked = evaluate_sigatoka_early_readiness(
        replace(
            base,
            model_status="validated",
            positive_foure_stages=(2, 3),
            truth_ground_evidence_kind="derived",
            holdout_unit="random_record",
            held_out_farms=1,
            held_out_dates=1,
            positive_examples=5,
            negative_examples=10,
            sensitivity_recall=0.70,
            calibration_error=0.20,
            uses_single_index_rule=True,
        ),
        policy,
    )
    assert blocked.decision == "blocked"
    assert blocked.inference_allowed is False
    assert set(blocked.reasons) == {
        "model_not_approved",
        "target_not_foure_1_2",
        "truth_ground_not_observed",
        "holdout_not_farm_date",
        "single_index_rule",
        "insufficient_held_out_farms",
        "insufficient_held_out_dates",
        "insufficient_positive_examples",
        "insufficient_negative_examples",
        "sensitivity_below_policy",
        "calibration_error_above_policy",
    }

    metric_mismatch = evaluate_sigatoka_early_readiness(
        replace(base, calibration_metric="brier_score"),
        policy,
    )
    assert metric_mismatch.reasons == ("calibration_metric_mismatch",)
    assert metric_mismatch.inference_allowed is False


def validate_thresholds_are_policy_driven() -> None:
    evidence = _evidence()
    strict = replace(
        _policy(),
        policy_version="sigatoka-readiness-ci-strict-v1",
        min_sensitivity_recall=0.95,
    )
    result = evaluate_sigatoka_early_readiness(evidence, strict)
    assert result.decision == "blocked"
    assert result.reasons == ("sensitivity_below_policy",)
    assert result.policy_version == "sigatoka-readiness-ci-strict-v1"


def main() -> None:
    validate_ready_contract()
    validate_fail_closed()
    validate_thresholds_are_policy_driven()
    print(
        "DBI-MULTI-001 readiness Sigatoka aprobado: Fouré 1-2 observado, "
        "holdout finca-fecha, sensibilidad/calibración versionadas y fail-closed."
    )


if __name__ == "__main__":
    main()
