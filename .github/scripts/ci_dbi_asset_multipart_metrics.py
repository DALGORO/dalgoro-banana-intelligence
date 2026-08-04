"""Contrato CI para métricas multipartes agregadas y sin cardinalidad sensible."""

from __future__ import annotations

import ast
import sys
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.asset_multipart_metrics import (  # noqa: E402
    DBIMeteredMultipartObjectStore,
    DBIMultipartMetrics,
    DBIMultipartMetricsSnapshot,
)
from app.dbi.asset_multipart_provider import (  # noqa: E402
    DBIMultipartProviderConflict,
)


class FakeMultipartStore:
    def __init__(self) -> None:
        self.raise_conflict = False

    def initiate(self, request):
        return SimpleNamespace(request=request)

    def issue_part_access(self, request):
        if self.raise_conflict:
            raise DBIMultipartProviderConflict("conflicto sintético")
        return SimpleNamespace(size_bytes=request.size_bytes)

    def complete(self, request):
        return SimpleNamespace(created=request.created)

    def inspect_completed(self, upload):
        return SimpleNamespace(created=False, upload=upload)

    def abort(self, request):
        return SimpleNamespace(
            provider_uploads_aborted=request.provider_uploads_aborted,
            cleanup_confirmed=request.cleanup_confirmed,
        )

    def resolve_part_access(self, grant_ref):
        return ("PUT", grant_ref)


def _must_raise(error_type, callable_) -> None:
    try:
        callable_()
    except error_type:
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}.")


def validate_aggregates() -> None:
    raw = FakeMultipartStore()
    metrics = DBIMultipartMetrics()
    store = DBIMeteredMultipartObjectStore(raw, metrics)
    part_a = SimpleNamespace(size_bytes=64)
    part_b = SimpleNamespace(size_bytes=16)

    store.initiate(SimpleNamespace())
    store.issue_part_access(SimpleNamespace(size_bytes=64))
    store.issue_part_access(SimpleNamespace(size_bytes=16))
    store.complete(SimpleNamespace(created=True, parts=(part_a, part_b)))
    store.complete(SimpleNamespace(created=False, parts=(part_a, part_b)))
    store.inspect_completed(SimpleNamespace())
    store.abort(
        SimpleNamespace(provider_uploads_aborted=1, cleanup_confirmed=True)
    )
    store.abort(
        SimpleNamespace(provider_uploads_aborted=0, cleanup_confirmed=False)
    )

    raw.raise_conflict = True
    _must_raise(
        DBIMultipartProviderConflict,
        lambda: store.issue_part_access(SimpleNamespace(size_bytes=8)),
    )

    snapshot = metrics.snapshot()
    assert snapshot == DBIMultipartMetricsSnapshot(
        initiation_attempts=1,
        uploads_initiated=1,
        grant_attempts=3,
        part_grants_issued=2,
        part_bytes_authorized=80,
        completion_attempts=2,
        uploads_completed=1,
        completed_parts=2,
        completed_bytes=80,
        retry_recovery_attempts=2,
        abort_attempts=2,
        provider_uploads_aborted=1,
        cleanup_confirmations=1,
        residual_uploads_observed=1,
        provider_conflicts=1,
        provider_errors=1,
        provider_duration_microseconds=snapshot.provider_duration_microseconds,
    )
    assert snapshot.provider_duration_microseconds >= 9
    assert store.resolve_part_access("grant-sintético") == (
        "PUT",
        "grant-sintético",
    )


def validate_thread_safe_updates_and_input_bounds() -> None:
    metrics = DBIMultipartMetrics()
    metrics.add(part_grants_issued=2, part_bytes_authorized=128)
    assert metrics.snapshot().part_grants_issued == 2
    _must_raise(ValueError, lambda: metrics.add(unknown_counter=1))
    _must_raise(ValueError, lambda: metrics.add(part_grants_issued=-1))
    _must_raise(ValueError, lambda: metrics.add(part_grants_issued=True))


def validate_safe_surface() -> None:
    forbidden_names = {
        "tenant",
        "organization",
        "farm",
        "plot",
        "asset",
        "session",
        "object_key",
        "url",
        "token",
        "checksum",
        "etag",
        "secret",
    }
    names = {field.name for field in fields(DBIMultipartMetricsSnapshot)}
    assert not names & forbidden_names

    source_path = (
        BACKEND / "app" / "dbi" / "asset_multipart_metrics.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not imports & {"boto3", "httpx", "logging", "sqlalchemy"}
    assert "print(" not in source


def main() -> None:
    validate_aggregates()
    validate_thread_safe_updates_and_input_bounds()
    validate_safe_surface()
    print("dbi asset multipart metrics checks passed")


if __name__ == "__main__":
    main()
