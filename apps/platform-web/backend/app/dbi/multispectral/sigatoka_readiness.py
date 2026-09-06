"""Gate científico para habilitar inferencia temprana de Sigatoka negra.

Este módulo NO diagnostica, no fija umbrales agronómicos de índices y no recomienda
tratamientos. Sólo evalúa, contra una política versionada, si una versión de modelo
aprobada tiene evidencia de validación suficiente para emitir una salida `inferred`.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DBI_SIGATOKA_READINESS_SCHEMA_VERSION = "dbi-sigatoka-readiness.v1"

DBISigatokaReadinessReason = Literal[
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
    "calibration_metric_mismatch",
    "calibration_error_above_policy",
]


class _ReadinessModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DBISigatokaValidationEvidence(_ReadinessModel):
    """Snapshot reproducible de validación de una versión de modelo."""

    model_version_id: UUID
    model_family: Literal["sigatoka_early_risk"] = "sigatoka_early_risk"
    model_version: str = Field(min_length=1, max_length=128)
    model_status: Literal["draft", "validated", "approved", "retired"]
    validation_dataset_version: str = Field(min_length=1, max_length=128)
    truth_ground_contract_version: str = Field(min_length=1, max_length=128)
    truth_ground_evidence_kind: Literal["observed", "derived", "inferred"]
    positive_foure_stages: tuple[int, ...] = Field(min_length=1, max_length=7)
    holdout_unit: Literal["farm_date", "random_record", "same_farm_random"]
    held_out_farms: int = Field(ge=0)
    held_out_dates: int = Field(ge=0)
    positive_examples: int = Field(ge=0)
    negative_examples: int = Field(ge=0)
    sensitivity_recall: float = Field(ge=0, le=1)
    calibration_metric: Literal["ece", "brier_score"]
    calibration_error: float = Field(ge=0, le=1)
    uses_single_index_rule: bool = False

    @field_validator(
        "model_version",
        "validation_dataset_version",
        "truth_ground_contract_version",
    )
    @classmethod
    def require_canonical_ref(cls, value: str) -> str:
        if (
            value != value.strip()
            or "*" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("La referencia de validación debe ser canónica.")
        return value

    @field_validator("positive_foure_stages")
    @classmethod
    def validate_foure_stages(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(stage < 0 or stage > 6 for stage in value):
            raise ValueError("Fouré debe permanecer dentro de 0..6.")
        if len(set(value)) != len(value):
            raise ValueError("positive_foure_stages no admite duplicados.")
        return tuple(sorted(value))


class DBISigatokaReadinessPolicy(_ReadinessModel):
    """Umbrales de gobernanza explícitos; no son umbrales de un índice vegetal."""

    policy_version: str = Field(min_length=1, max_length=128)
    min_held_out_farms: int = Field(ge=1)
    min_held_out_dates: int = Field(ge=1)
    min_positive_examples: int = Field(ge=1)
    min_negative_examples: int = Field(ge=1)
    min_sensitivity_recall: float = Field(gt=0, le=1)
    required_calibration_metric: Literal["ece", "brier_score"]
    max_calibration_error: float = Field(ge=0, lt=1)

    @field_validator("policy_version")
    @classmethod
    def require_canonical_version(cls, value: str) -> str:
        if (
            value != value.strip()
            or "*" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("policy_version debe ser canónica.")
        return value


class DBISigatokaReadinessDecision(_ReadinessModel):
    """Resultado de gobernanza. `ready` sólo habilita inferencia, nunca diagnóstico."""

    schema_version: Literal["dbi-sigatoka-readiness.v1"] = (
        DBI_SIGATOKA_READINESS_SCHEMA_VERSION
    )
    model_version_id: UUID
    model_version: str
    validation_dataset_version: str
    policy_version: str
    decision: Literal["ready", "blocked"]
    reasons: tuple[DBISigatokaReadinessReason, ...]
    evidence_kind: Literal["derived"] = "derived"
    inference_kind_if_emitted: Literal["inferred"] = "inferred"
    inference_allowed: bool
    diagnosis_allowed: Literal[False] = False
    agrochemical_recommendation_allowed: Literal[False] = False
    single_index_rule_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_decision_semantics(self) -> "DBISigatokaReadinessDecision":
        if self.decision == "ready":
            if self.reasons or not self.inference_allowed:
                raise ValueError("ready requiere cero bloqueos e inference_allowed=true.")
        elif not self.reasons or self.inference_allowed:
            raise ValueError("blocked requiere razones e inference_allowed=false.")
        return self


def evaluate_sigatoka_early_readiness(
    evidence: DBISigatokaValidationEvidence,
    policy: DBISigatokaReadinessPolicy,
) -> DBISigatokaReadinessDecision:
    """Evalúa readiness sin producir una predicción agronómica."""

    if not isinstance(evidence, DBISigatokaValidationEvidence):
        evidence = DBISigatokaValidationEvidence.model_validate(evidence)
    if not isinstance(policy, DBISigatokaReadinessPolicy):
        policy = DBISigatokaReadinessPolicy.model_validate(policy)

    reasons: list[DBISigatokaReadinessReason] = []

    if evidence.model_status != "approved":
        reasons.append("model_not_approved")
    if evidence.positive_foure_stages != (1, 2):
        reasons.append("target_not_foure_1_2")
    if evidence.truth_ground_evidence_kind != "observed":
        reasons.append("truth_ground_not_observed")
    if evidence.holdout_unit != "farm_date":
        reasons.append("holdout_not_farm_date")
    if evidence.uses_single_index_rule:
        reasons.append("single_index_rule")
    if evidence.held_out_farms < policy.min_held_out_farms:
        reasons.append("insufficient_held_out_farms")
    if evidence.held_out_dates < policy.min_held_out_dates:
        reasons.append("insufficient_held_out_dates")
    if evidence.positive_examples < policy.min_positive_examples:
        reasons.append("insufficient_positive_examples")
    if evidence.negative_examples < policy.min_negative_examples:
        reasons.append("insufficient_negative_examples")
    if evidence.sensitivity_recall < policy.min_sensitivity_recall:
        reasons.append("sensitivity_below_policy")
    if evidence.calibration_metric != policy.required_calibration_metric:
        reasons.append("calibration_metric_mismatch")
    elif evidence.calibration_error > policy.max_calibration_error:
        reasons.append("calibration_error_above_policy")

    blocked = tuple(reasons)
    return DBISigatokaReadinessDecision(
        model_version_id=evidence.model_version_id,
        model_version=evidence.model_version,
        validation_dataset_version=evidence.validation_dataset_version,
        policy_version=policy.policy_version,
        decision="blocked" if blocked else "ready",
        reasons=blocked,
        inference_allowed=not blocked,
    )
