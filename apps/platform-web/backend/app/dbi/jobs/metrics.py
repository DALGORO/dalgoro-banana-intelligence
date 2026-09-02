"""Métricas agregadas y seguras para la frontera de trabajos DBI."""

from __future__ import annotations

from dataclasses import dataclass, fields
from threading import RLock


@dataclass(frozen=True, slots=True)
class DBIAnalysisJobMetricsSnapshot:
    """Contadores sin etiquetas ni identificadores de alta cardinalidad."""

    create_attempts: int = 0
    jobs_created: int = 0
    exact_reuses: int = 0
    create_conflicts: int = 0
    unavailable_resources: int = 0
    unavailable_profiles: int = 0
    cancel_attempts: int = 0
    cancel_changes: int = 0
    cancel_noops: int = 0
    retry_attempts: int = 0
    retry_changes: int = 0
    retry_noops: int = 0
    rollbacks: int = 0
    service_duration_microseconds: int = 0


class DBIAnalysisJobMetrics:
    """Registro monotónico, local y seguro entre hilos."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._values = {
            field.name: 0 for field in fields(DBIAnalysisJobMetricsSnapshot)
        }

    def add(self, **increments: int) -> None:
        if not increments:
            return
        if any(
            name not in self._values
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for name, value in increments.items()
        ):
            raise ValueError("los incrementos de métricas deben ser enteros válidos.")
        with self._lock:
            for name, value in increments.items():
                self._values[name] += value

    def snapshot(self) -> DBIAnalysisJobMetricsSnapshot:
        with self._lock:
            return DBIAnalysisJobMetricsSnapshot(**self._values)
