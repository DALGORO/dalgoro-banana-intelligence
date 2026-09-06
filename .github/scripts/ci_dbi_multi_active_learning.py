"""Valida prioridades advisory MULTI -> Sampling sin mutación automática."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.multispectral.active_learning import (  # noqa: E402
    DBISamplingPriorityBatch,
    DBISamplingPriorityCandidate,
    rank_sampling_priorities,
    sampling_priority_fingerprint,
)

TENANT = "tenant-multi-ci"
ORGANIZATION = "organization-multi-ci"
FARM_ID = UUID("10000000-0000-4000-8000-000000000080")
PLOT_ID = UUID("20000000-0000-4000-8000-000000000080")
UP_HIGH = UUID("40000000-0000-4000-8000-000000000081")
UP_CONTROL = UUID("40000000-0000-4000-8000-000000000082")
SAMPLING_UNDERREPRESENTED = UUID("50000000-0000-4000-8000-000000000083")


def _candidate(
    *,
    target_kind: str,
    target_id: UUID,
    priority_score: float,
    uncertainty: float,
    reason_codes: tuple[str, ...],
    source_kind: str,
    tenant_ref: str = TENANT,
) -> DBISamplingPriorityCandidate:
    return DBISamplingPriorityCandidate(
        tenant_ref=tenant_ref,
        organization_ref=ORGANIZATION,
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        target_kind=target_kind,
        target_id=target_id,
        priority_score=priority_score,
        uncertainty=uncertainty,
        reason_codes=reason_codes,
        source_kind=source_kind,
        source_ref="champion-sigatoka" if source_kind == "model" else "dataset-multi",
        source_version="v1",
    )


def _batch(candidates) -> DBISamplingPriorityBatch:
    return DBISamplingPriorityBatch(
        tenant_ref=TENANT,
        organization_ref=ORGANIZATION,
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        priority_profile_version="active-learning-v1",
        candidates=tuple(candidates),
    )


def _raises_validation(callback) -> None:
    try:
        callback()
    except ValidationError:
        return
    raise AssertionError("Se esperaba ValidationError.")


def validate_advisory_ranking() -> None:
    anomaly = _candidate(
        target_kind="up",
        target_id=UP_HIGH,
        priority_score=0.95,
        uncertainty=0.72,
        reason_codes=("anomaly", "low_confidence"),
        source_kind="model",
    )
    underrepresented = _candidate(
        target_kind="sampling_point",
        target_id=SAMPLING_UNDERREPRESENTED,
        priority_score=0.80,
        uncertainty=0.90,
        reason_codes=("underrepresented_class",),
        source_kind="dataset",
    )
    control = _candidate(
        target_kind="up",
        target_id=UP_CONTROL,
        priority_score=0.55,
        uncertainty=0.15,
        reason_codes=("healthy_control",),
        source_kind="audit",
    )
    batch = _batch((control, underrepresented, anomaly))

    ranked = rank_sampling_priorities(batch)
    assert [item.target_id for item in ranked] == [
        UP_HIGH,
        SAMPLING_UNDERREPRESENTED,
        UP_CONTROL,
    ]
    assert rank_sampling_priorities(batch, limit=2) == ranked[:2]
    assert all(item.evidence_kind == "inferred" for item in ranked)
    assert all(item.recommendation_mode == "advisory" for item in ranked)
    assert batch.evidence_kind == "inferred"
    assert batch.recommendation_mode == "advisory"

    reversed_batch = _batch(tuple(reversed(batch.candidates)))
    assert sampling_priority_fingerprint(batch) == sampling_priority_fingerprint(
        reversed_batch
    )


def validate_fail_closed_boundaries() -> None:
    anomaly = _candidate(
        target_kind="up",
        target_id=UP_HIGH,
        priority_score=0.95,
        uncertainty=0.72,
        reason_codes=("anomaly",),
        source_kind="model",
    )

    _raises_validation(
        lambda: _candidate(
            target_kind="up",
            target_id=UP_CONTROL,
            priority_score=0.70,
            uncertainty=0.40,
            reason_codes=("model_disagreement",),
            source_kind="dataset",
        )
    )
    _raises_validation(
        lambda: DBISamplingPriorityCandidate.model_validate(
            {
                **anomaly.model_dump(mode="json"),
                "evidence_kind": "observed",
            }
        )
    )
    _raises_validation(
        lambda: _batch(
            (
                anomaly,
                _candidate(
                    target_kind="sampling_point",
                    target_id=SAMPLING_UNDERREPRESENTED,
                    priority_score=0.60,
                    uncertainty=0.50,
                    reason_codes=("underrepresented_class",),
                    source_kind="dataset",
                    tenant_ref="tenant-crossed",
                ),
            )
        )
    )
    _raises_validation(lambda: _batch((anomaly, anomaly)))

    try:
        rank_sampling_priorities(_batch((anomaly,)), limit=0)
    except ValueError:
        pass
    else:
        raise AssertionError("limit=0 debía fallar.")


def main() -> None:
    validate_advisory_ranking()
    validate_fail_closed_boundaries()
    print(
        "DBI-MULTI-001 active learning aprobado: prioridades inferidas/advisory, "
        "ranking determinista, provenance y aislamiento de scope sin mutar Sampling."
    )


if __name__ == "__main__":
    main()
