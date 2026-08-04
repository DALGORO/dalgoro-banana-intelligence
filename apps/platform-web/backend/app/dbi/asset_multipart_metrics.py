"""Métricas agregadas y seguras para transporte multipartes DBI."""

from __future__ import annotations

from dataclasses import dataclass, fields
from threading import RLock
from time import perf_counter_ns
from typing import Any

from app.dbi.asset_multipart_provider import (
    DBIMultipartObjectStore,
    DBIMultipartProviderAbortConfirmation,
    DBIMultipartProviderAbortRequest,
    DBIMultipartProviderCompleteRequest,
    DBIMultipartProviderCompletion,
    DBIMultipartProviderConflict,
    DBIMultipartProviderError,
    DBIMultipartProviderInitiateRequest,
    DBIMultipartProviderPartGrant,
    DBIMultipartProviderPartGrantRequest,
    DBIMultipartProviderUpload,
)


@dataclass(frozen=True, slots=True)
class DBIMultipartMetricsSnapshot:
    """Contadores sin etiquetas ni identificadores de alta cardinalidad."""

    initiation_attempts: int = 0
    uploads_initiated: int = 0
    grant_attempts: int = 0
    part_grants_issued: int = 0
    part_bytes_authorized: int = 0
    completion_attempts: int = 0
    uploads_completed: int = 0
    completed_parts: int = 0
    completed_bytes: int = 0
    retry_recovery_attempts: int = 0
    abort_attempts: int = 0
    provider_uploads_aborted: int = 0
    cleanup_confirmations: int = 0
    residual_uploads_observed: int = 0
    provider_conflicts: int = 0
    provider_errors: int = 0
    provider_duration_microseconds: int = 0


class DBIMultipartMetrics:
    """Registro en memoria, monotónico y seguro entre hilos."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._values = {
            field.name: 0 for field in fields(DBIMultipartMetricsSnapshot)
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

    def snapshot(self) -> DBIMultipartMetricsSnapshot:
        with self._lock:
            return DBIMultipartMetricsSnapshot(**self._values)


class DBIMeteredMultipartObjectStore:
    """Decora un proveedor sin registrar contenido, claves, URLs o identidades."""

    def __init__(
        self,
        delegate: DBIMultipartObjectStore,
        metrics: DBIMultipartMetrics | None = None,
    ) -> None:
        required = (
            "initiate",
            "issue_part_access",
            "complete",
            "inspect_completed",
            "abort",
        )
        if any(not hasattr(delegate, name) for name in required):
            raise TypeError("delegate no implementa el puerto multipartes.")
        if metrics is not None and not isinstance(metrics, DBIMultipartMetrics):
            raise TypeError("metrics debe ser DBIMultipartMetrics.")
        self._delegate = delegate
        self._metrics = metrics or DBIMultipartMetrics()

    @property
    def metrics(self) -> DBIMultipartMetrics:
        return self._metrics

    def __getattr__(self, name: str) -> Any:
        """Conserva capacidades efímeras del adaptador, como resolver grants."""

        return getattr(self._delegate, name)

    def _observe(self, started_at: int, error: BaseException | None) -> None:
        elapsed = max(1, (perf_counter_ns() - started_at + 999) // 1_000)
        increments = {"provider_duration_microseconds": elapsed}
        if isinstance(error, DBIMultipartProviderConflict):
            increments["provider_conflicts"] = 1
            increments["provider_errors"] = 1
        elif isinstance(error, DBIMultipartProviderError):
            increments["provider_errors"] = 1
        self._metrics.add(**increments)

    def initiate(
        self,
        request: DBIMultipartProviderInitiateRequest,
    ) -> DBIMultipartProviderUpload:
        self._metrics.add(initiation_attempts=1)
        started_at = perf_counter_ns()
        error: BaseException | None = None
        try:
            result = self._delegate.initiate(request)
        except DBIMultipartProviderError as caught:
            error = caught
            raise
        else:
            self._metrics.add(uploads_initiated=1)
            return result
        finally:
            self._observe(started_at, error)

    def issue_part_access(
        self,
        request: DBIMultipartProviderPartGrantRequest,
    ) -> DBIMultipartProviderPartGrant:
        self._metrics.add(grant_attempts=1)
        started_at = perf_counter_ns()
        error: BaseException | None = None
        try:
            result = self._delegate.issue_part_access(request)
        except DBIMultipartProviderError as caught:
            error = caught
            raise
        else:
            self._metrics.add(
                part_grants_issued=1,
                part_bytes_authorized=request.size_bytes,
            )
            return result
        finally:
            self._observe(started_at, error)

    def complete(
        self,
        request: DBIMultipartProviderCompleteRequest,
    ) -> DBIMultipartProviderCompletion:
        self._metrics.add(completion_attempts=1)
        started_at = perf_counter_ns()
        error: BaseException | None = None
        try:
            result = self._delegate.complete(request)
        except DBIMultipartProviderError as caught:
            error = caught
            raise
        else:
            if result.created:
                self._metrics.add(
                    uploads_completed=1,
                    completed_parts=len(request.parts),
                    completed_bytes=sum(part.size_bytes for part in request.parts),
                )
            else:
                self._metrics.add(retry_recovery_attempts=1)
            return result
        finally:
            self._observe(started_at, error)

    def inspect_completed(
        self,
        upload: DBIMultipartProviderUpload,
    ) -> DBIMultipartProviderCompletion:
        self._metrics.add(retry_recovery_attempts=1)
        started_at = perf_counter_ns()
        error: BaseException | None = None
        try:
            return self._delegate.inspect_completed(upload)
        except DBIMultipartProviderError as caught:
            error = caught
            raise
        finally:
            self._observe(started_at, error)

    def abort(
        self,
        request: DBIMultipartProviderAbortRequest,
    ) -> DBIMultipartProviderAbortConfirmation:
        self._metrics.add(abort_attempts=1)
        started_at = perf_counter_ns()
        error: BaseException | None = None
        try:
            result = self._delegate.abort(request)
        except DBIMultipartProviderError as caught:
            error = caught
            raise
        else:
            self._metrics.add(
                provider_uploads_aborted=result.provider_uploads_aborted,
                cleanup_confirmations=int(result.cleanup_confirmed),
                residual_uploads_observed=int(not result.cleanup_confirmed),
            )
            return result
        finally:
            self._observe(started_at, error)
