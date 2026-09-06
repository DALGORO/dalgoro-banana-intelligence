"""Superficie pública de evidencia multiespectral DBI.

Los contratos puros se cargan sin arrastrar dependencias de persistencia. El
repositorio SQLAlchemy se resuelve de forma perezosa sólo cuando un consumidor lo
solicita explícitamente.
"""

from __future__ import annotations

from typing import Any

from app.dbi.multispectral.active_learning import (
    DBI_SAMPLING_PRIORITY_SCHEMA_VERSION,
    DBISamplingPriorityBatch,
    DBISamplingPriorityCandidate,
    DBISamplingPriorityReason,
    rank_sampling_priorities,
    sampling_priority_fingerprint,
)
from app.dbi.multispectral.contracts import (
    DBI_MULTISPECTRAL_EXTRACTION_SCHEMA_VERSION,
    DBIMultispectralExtractionCandidate,
    DBISpectralVariableSummary,
    multispectral_extraction_id,
)

_LAZY_REPOSITORY_EXPORTS = frozenset(
    {
        "DBIMultispectralExtractionRepository",
        "DBIMultispectralPersistenceConflict",
    }
)


def __getattr__(name: str) -> Any:
    """Carga persistencia sólo para consumidores que realmente la requieren."""

    if name not in _LAZY_REPOSITORY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from app.dbi.multispectral.repository import (
        DBIMultispectralExtractionRepository,
        DBIMultispectralPersistenceConflict,
    )

    exports = {
        "DBIMultispectralExtractionRepository": DBIMultispectralExtractionRepository,
        "DBIMultispectralPersistenceConflict": DBIMultispectralPersistenceConflict,
    }
    value = exports[name]
    globals()[name] = value
    return value


__all__ = [
    "DBI_MULTISPECTRAL_EXTRACTION_SCHEMA_VERSION",
    "DBI_SAMPLING_PRIORITY_SCHEMA_VERSION",
    "DBIMultispectralExtractionCandidate",
    "DBIMultispectralExtractionRepository",
    "DBIMultispectralPersistenceConflict",
    "DBISamplingPriorityBatch",
    "DBISamplingPriorityCandidate",
    "DBISamplingPriorityReason",
    "DBISpectralVariableSummary",
    "multispectral_extraction_id",
    "rank_sampling_priorities",
    "sampling_priority_fingerprint",
]
