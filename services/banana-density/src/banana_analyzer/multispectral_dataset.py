"""Dataset puro de evidencia MULTI entre fincas y revisitas opcionales.

Este módulo organiza extracciones espectrales ya derivadas sin persistirlas ni
convertirlas en observaciones o inferencias. Conserva cada observación válida aunque
la finca no vuelva a contratar y clasifica como longitudinal únicamente la evidencia
que comparte una identidad espacial verificable en instantes distintos.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from .multispectral_extraction import SpatialSpectralExtraction

_SCHEMA_VERSION = "dbi-multispectral-dataset.v1"
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class MultispectralDatasetError(RuntimeError):
    """El dataset solicitado rompe una frontera verificable de evidencia MULTI."""


class EvidenceSeriesKind(StrEnum):
    CROSS_SECTIONAL = "cross-sectional"
    LONGITUDINAL = "longitudinal"


@dataclass(frozen=True, slots=True)
class SpectralEvidenceRecord:
    """Extracción MULTI vinculada a su instante y producto científico versionado."""

    extraction: SpatialSpectralExtraction
    acquired_at: datetime
    product_version: str


@dataclass(frozen=True, slots=True)
class DatasetEvidenceEntry:
    observation_version_id: UUID
    farm_id: UUID
    plot_id: UUID
    sampling_point_id: UUID | None
    up_id: UUID | None
    acquired_at: datetime
    product_version: str
    stack_fingerprint: str
    evidence_kind: str
    series_kind: EvidenceSeriesKind
    revisit_key: str | None


@dataclass(frozen=True, slots=True)
class MultifarmSpectralDataset:
    schema_version: str
    tenant_ref: str
    organization_ref: str
    evidence_kind: str
    entries: tuple[DatasetEvidenceEntry, ...]
    farm_count: int
    cross_sectional_count: int
    longitudinal_count: int
    fingerprint: str


def _canonical_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise MultispectralDatasetError(f"{field_name} no es una referencia canónica.")
    return value


def _validate_acquired_at(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MultispectralDatasetError("acquired_at debe incluir zona horaria.")
    return value


def _revisit_key(extraction: SpatialSpectralExtraction) -> str | None:
    if extraction.up_id is not None:
        return f"up:{extraction.farm_id}:{extraction.up_id}"
    if extraction.sampling_point_id is not None:
        return f"sampling:{extraction.farm_id}:{extraction.sampling_point_id}"
    return None


def _fingerprint(entries: tuple[DatasetEvidenceEntry, ...], *, tenant_ref: str, organization_ref: str) -> str:
    lines = [f"schema={_SCHEMA_VERSION}", f"tenant={tenant_ref}", f"organization={organization_ref}"]
    for entry in entries:
        lines.append(
            "|".join(
                (
                    str(entry.observation_version_id),
                    str(entry.farm_id),
                    str(entry.plot_id),
                    str(entry.sampling_point_id or ""),
                    str(entry.up_id or ""),
                    entry.acquired_at.isoformat(),
                    entry.product_version,
                    entry.stack_fingerprint,
                    entry.evidence_kind,
                    entry.series_kind.value,
                    entry.revisit_key or "",
                )
            )
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def assemble_multifarm_dataset(
    records: tuple[SpectralEvidenceRecord, ...] | list[SpectralEvidenceRecord],
    *,
    tenant_ref: str,
    organization_ref: str,
) -> MultifarmSpectralDataset:
    """Construye un dataset tenant-safe con evidencia transversal y longitudinal.

    La identidad longitudinal se basa primero en ``up_id`` y, cuando no existe, en
    ``sampling_point_id``. Una observación sin ninguna de esas identidades sigue
    siendo evidencia transversal válida y nunca se descarta por falta de revisita.
    """

    tenant_ref = _canonical_ref(tenant_ref, field_name="tenant_ref")
    organization_ref = _canonical_ref(organization_ref, field_name="organization_ref")
    if not isinstance(records, (tuple, list)) or not records:
        raise MultispectralDatasetError("records debe contener al menos una evidencia.")

    normalized: list[tuple[SpectralEvidenceRecord, str | None]] = []
    seen_observations: set[UUID] = set()
    identity_times: set[tuple[str, datetime]] = set()

    for record in records:
        if not isinstance(record, SpectralEvidenceRecord):
            raise MultispectralDatasetError("Cada record debe ser SpectralEvidenceRecord.")
        extraction = record.extraction
        if not isinstance(extraction, SpatialSpectralExtraction):
            raise MultispectralDatasetError("record.extraction debe ser SpatialSpectralExtraction.")
        if extraction.evidence_kind != "derived":
            raise MultispectralDatasetError("MULTI sólo admite evidencia espectral derived.")
        if extraction.tenant_ref != tenant_ref or extraction.organization_ref != organization_ref:
            raise MultispectralDatasetError("Se rechazó evidencia fuera del tenant/organization del dataset.")
        acquired_at = _validate_acquired_at(record.acquired_at)
        _canonical_ref(record.product_version, field_name="product_version")

        observation_id = extraction.observation_version_id
        if observation_id in seen_observations:
            raise MultispectralDatasetError("observation_version_id duplicado en el dataset.")
        seen_observations.add(observation_id)

        key = _revisit_key(extraction)
        if key is not None:
            identity_time = (key, acquired_at)
            if identity_time in identity_times:
                raise MultispectralDatasetError(
                    "Una misma identidad espacial no puede tener dos observaciones MULTI en el mismo instante."
                )
            identity_times.add(identity_time)
        normalized.append((record, key))

    revisit_counts: dict[str, int] = {}
    for _, key in normalized:
        if key is not None:
            revisit_counts[key] = revisit_counts.get(key, 0) + 1

    entries: list[DatasetEvidenceEntry] = []
    for record, key in normalized:
        extraction = record.extraction
        series_kind = (
            EvidenceSeriesKind.LONGITUDINAL
            if key is not None and revisit_counts[key] > 1
            else EvidenceSeriesKind.CROSS_SECTIONAL
        )
        entries.append(
            DatasetEvidenceEntry(
                observation_version_id=extraction.observation_version_id,
                farm_id=extraction.farm_id,
                plot_id=extraction.plot_id,
                sampling_point_id=extraction.sampling_point_id,
                up_id=extraction.up_id,
                acquired_at=record.acquired_at,
                product_version=record.product_version,
                stack_fingerprint=extraction.stack_fingerprint,
                evidence_kind="derived",
                series_kind=series_kind,
                revisit_key=key,
            )
        )

    ordered = tuple(
        sorted(
            entries,
            key=lambda item: (item.acquired_at, str(item.observation_version_id)),
        )
    )
    cross_sectional_count = sum(
        item.series_kind is EvidenceSeriesKind.CROSS_SECTIONAL for item in ordered
    )
    longitudinal_count = len(ordered) - cross_sectional_count
    farms = {item.farm_id for item in ordered}

    return MultifarmSpectralDataset(
        schema_version=_SCHEMA_VERSION,
        tenant_ref=tenant_ref,
        organization_ref=organization_ref,
        evidence_kind="derived",
        entries=ordered,
        farm_count=len(farms),
        cross_sectional_count=cross_sectional_count,
        longitudinal_count=longitudinal_count,
        fingerprint=_fingerprint(
            ordered,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
        ),
    )
