"""Máquina de estados pura para trabajos geoespaciales DBI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AnalysisJobStatus(str, Enum):
    """Estados globales aprobados para un trabajo."""

    ACCEPTED = "accepted"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"


class InvalidAnalysisJobTransition(ValueError):
    """Indica una transición inválida o no autorizada."""


@dataclass(frozen=True)
class TransitionDecision:
    """Resultado determinista de evaluar una transición."""

    current: AnalysisJobStatus
    target: AnalysisJobStatus
    changed: bool
    retry_authorized: bool


ALLOWED_ANALYSIS_JOB_TRANSITIONS = {
    AnalysisJobStatus.ACCEPTED: frozenset(
        {AnalysisJobStatus.QUEUED}
    ),
    AnalysisJobStatus.QUEUED: frozenset(
        {
            AnalysisJobStatus.RUNNING,
            AnalysisJobStatus.CANCEL_REQUESTED,
        }
    ),
    AnalysisJobStatus.RUNNING: frozenset(
        {
            AnalysisJobStatus.SUCCEEDED,
            AnalysisJobStatus.FAILED,
            AnalysisJobStatus.CANCEL_REQUESTED,
        }
    ),
    AnalysisJobStatus.FAILED: frozenset(
        {AnalysisJobStatus.QUEUED}
    ),
    AnalysisJobStatus.CANCEL_REQUESTED: frozenset(
        {AnalysisJobStatus.CANCELED}
    ),
    AnalysisJobStatus.SUCCEEDED: frozenset(),
    AnalysisJobStatus.CANCELED: frozenset(),
}


def is_terminal_analysis_job_status(status: AnalysisJobStatus) -> bool:
    """Indica si el estado no admite cambios posteriores."""

    return status in {
        AnalysisJobStatus.SUCCEEDED,
        AnalysisJobStatus.CANCELED,
    }


def evaluate_analysis_job_transition(
    current: AnalysisJobStatus,
    target: AnalysisJobStatus,
    *,
    retry_authorized: bool = False,
) -> TransitionDecision:
    """Valida una transición sin persistir ni producir efectos externos."""

    if current == target:
        return TransitionDecision(
            current=current,
            target=target,
            changed=False,
            retry_authorized=retry_authorized,
        )

    if target not in ALLOWED_ANALYSIS_JOB_TRANSITIONS[current]:
        raise InvalidAnalysisJobTransition(
            f"Transición no permitida: {current.value} → {target.value}."
        )

    is_retry = (
        current is AnalysisJobStatus.FAILED
        and target is AnalysisJobStatus.QUEUED
    )
    if is_retry and not retry_authorized:
        raise InvalidAnalysisJobTransition(
            "El reintento failed → queued exige autorización explícita."
        )

    return TransitionDecision(
        current=current,
        target=target,
        changed=True,
        retry_authorized=retry_authorized,
    )
