"""Métricas agregadas y seguras para la entrega durable DBI."""

from __future__ import annotations

from dataclasses import dataclass, fields
from threading import RLock


@dataclass(frozen=True, slots=True)
class DBIDeliveryMetricsSnapshot:
    """Contadores monotónicos sin identificadores ni etiquetas sensibles."""

    enqueue_attempts: int = 0
    messages_created: int = 0
    exact_reuses: int = 0
    enqueue_conflicts: int = 0
    claims: int = 0
    acknowledgements: int = 0
    negative_acknowledgements: int = 0
    dead_letters: int = 0
    lease_conflicts: int = 0
    result_publications: int = 0
    rollbacks: int = 0


class DBIDeliveryMetrics:
    """Registro local seguro entre hilos y sin alta cardinalidad."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._values = {field.name: 0 for field in fields(DBIDeliveryMetricsSnapshot)}

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

    def snapshot(self) -> DBIDeliveryMetricsSnapshot:
        with self._lock:
            return DBIDeliveryMetricsSnapshot(**self._values)
