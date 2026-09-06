"""Valida dataset MULTI multi-finca con revisitas opcionales y aislamiento tenant."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
SERVICE_SRC = ROOT / "services" / "banana-density" / "src"
sys.path.insert(0, str(SERVICE_SRC))

from banana_analyzer.multispectral_dataset import (  # noqa: E402
    EvidenceSeriesKind,
    MultispectralDatasetError,
    SpectralEvidenceRecord,
    assemble_multifarm_dataset,
)
from banana_analyzer.multispectral_extraction import (  # noqa: E402
    SpatialSpectralExtraction,
    SpatialSupportMode,
)

TENANT = "tenant-demo"
ORGANIZATION = "organization-demo"


def _uuid(prefix: int, suffix: int) -> UUID:
    return UUID(f"{prefix:08x}-0000-4000-8000-{suffix:012x}")


def _extraction(
    *,
    farm: int,
    observation: int,
    up: int | None = None,
    sampling: int | None = None,
    tenant: str = TENANT,
    evidence_kind: str = "derived",
) -> SpatialSpectralExtraction:
    return SpatialSpectralExtraction(
        schema_version="dbi-multispectral-extraction.v1",
        evidence_kind=evidence_kind,
        tenant_ref=tenant,
        organization_ref=ORGANIZATION,
        farm_id=_uuid(0x10, farm),
        plot_id=_uuid(0x20, farm),
        observation_version_id=_uuid(0x30, observation),
        sampling_point_id=_uuid(0x40, sampling) if sampling is not None else None,
        up_id=_uuid(0x50, up) if up is not None else None,
        support_mode=SpatialSupportMode.COPA_UP if up is not None else SpatialSupportMode.WINDOW,
        support_profile_version="copa_up_mask_v1" if up is not None else "window_5m_v1",
        support_limitation=None if up is not None else "Ventana sustituta versionada.",
        stack_fingerprint=f"{observation:064x}",
        selected_count=4,
        summaries=(),
    )


def _record(
    *,
    farm: int,
    observation: int,
    day: int,
    up: int | None = None,
    sampling: int | None = None,
    tenant: str = TENANT,
    evidence_kind: str = "derived",
) -> SpectralEvidenceRecord:
    return SpectralEvidenceRecord(
        extraction=_extraction(
            farm=farm,
            observation=observation,
            up=up,
            sampling=sampling,
            tenant=tenant,
            evidence_kind=evidence_kind,
        ),
        acquired_at=datetime(2026, 8, day, 15, 0, tzinfo=timezone.utc),
        product_version="scientific_cog_v1",
    )


def _raises(callback) -> None:
    try:
        callback()
    except MultispectralDatasetError:
        return
    raise AssertionError("Se esperaba MultispectralDatasetError.")


def validate_cross_sectional_and_longitudinal() -> None:
    records = [
        _record(farm=1, observation=1, day=1, up=101),
        _record(farm=2, observation=2, day=2, sampling=202),
        _record(farm=1, observation=3, day=10, up=101),
        _record(farm=3, observation=4, day=3),
    ]
    dataset = assemble_multifarm_dataset(
        records,
        tenant_ref=TENANT,
        organization_ref=ORGANIZATION,
    )

    assert dataset.schema_version == "dbi-multispectral-dataset.v1"
    assert dataset.evidence_kind == "derived"
    assert dataset.farm_count == 3
    assert len(dataset.entries) == 4
    assert dataset.longitudinal_count == 2
    assert dataset.cross_sectional_count == 2

    farm_two = [entry for entry in dataset.entries if entry.farm_id == _uuid(0x10, 2)]
    assert len(farm_two) == 1
    assert farm_two[0].series_kind is EvidenceSeriesKind.CROSS_SECTIONAL

    revisited = [entry for entry in dataset.entries if entry.up_id == _uuid(0x50, 101)]
    assert len(revisited) == 2
    assert all(entry.series_kind is EvidenceSeriesKind.LONGITUDINAL for entry in revisited)
    assert all(entry.evidence_kind == "derived" for entry in dataset.entries)


def validate_reproducibility_and_optional_revisit() -> None:
    records = [
        _record(farm=11, observation=11, day=5, sampling=301),
        _record(farm=12, observation=12, day=6),
        _record(farm=13, observation=13, day=7, up=401),
    ]
    first = assemble_multifarm_dataset(
        records,
        tenant_ref=TENANT,
        organization_ref=ORGANIZATION,
    )
    second = assemble_multifarm_dataset(
        list(reversed(records)),
        tenant_ref=TENANT,
        organization_ref=ORGANIZATION,
    )
    assert first == second
    assert first.fingerprint == second.fingerprint
    assert first.cross_sectional_count == 3
    assert first.longitudinal_count == 0


def validate_boundaries() -> None:
    valid = _record(farm=21, observation=21, day=8, up=501)
    other_tenant = _record(
        farm=22,
        observation=22,
        day=9,
        tenant="tenant-other",
    )
    _raises(
        lambda: assemble_multifarm_dataset(
            [valid, other_tenant],
            tenant_ref=TENANT,
            organization_ref=ORGANIZATION,
        )
    )

    _raises(
        lambda: assemble_multifarm_dataset(
            [valid, valid],
            tenant_ref=TENANT,
            organization_ref=ORGANIZATION,
        )
    )

    same_identity_same_time = SpectralEvidenceRecord(
        extraction=_extraction(farm=21, observation=23, up=501),
        acquired_at=valid.acquired_at,
        product_version="scientific_cog_v1",
    )
    _raises(
        lambda: assemble_multifarm_dataset(
            [valid, same_identity_same_time],
            tenant_ref=TENANT,
            organization_ref=ORGANIZATION,
        )
    )

    observed = replace(valid, extraction=replace(valid.extraction, evidence_kind="observed"))
    _raises(
        lambda: assemble_multifarm_dataset(
            [observed],
            tenant_ref=TENANT,
            organization_ref=ORGANIZATION,
        )
    )

    naive_time = replace(valid, acquired_at=datetime(2026, 8, 8, 15, 0))
    _raises(
        lambda: assemble_multifarm_dataset(
            [naive_time],
            tenant_ref=TENANT,
            organization_ref=ORGANIZATION,
        )
    )


def main() -> None:
    validate_cross_sectional_and_longitudinal()
    validate_reproducibility_and_optional_revisit()
    validate_boundaries()
    print(
        "DBI-MULTI-001 dataset aprobado: multi-finca, revisita opcional, "
        "cross-sectional/longitudinal, tenant isolation y frontera derived."
    )


if __name__ == "__main__":
    main()
