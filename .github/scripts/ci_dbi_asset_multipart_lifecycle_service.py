"""Valida aborto, expiración y limpieza multipartes sin red."""

from __future__ import annotations

import ast
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.asset_multipart_application import (  # noqa: E402
    DBIMultipartAssetSnapshot,
    DBIMultipartSessionSnapshot,
)
from app.dbi.asset_multipart_contracts import (  # noqa: E402
    DBIMultipartSessionState,
)
from app.dbi.asset_multipart_lifecycle_service import (  # noqa: E402
    DBIMultipartLifecycleService,
    DBIMultipartTerminationRecord,
)
from app.dbi.asset_multipart_policy import (  # noqa: E402
    MIB,
    DBIMultipartConflict,
    DBIMultipartPolicy,
)
from app.dbi.asset_multipart_provider import (  # noqa: E402
    DBIMultipartProviderAbortConfirmation,
    DBIMultipartProviderConflict,
)
from app.dbi.asset_multipart_upload_service import (  # noqa: E402
    DBIMultipartSessionContext,
)
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)


SESSION_ID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_SESSION_ID = UUID("22222222-2222-4222-8222-222222222222")
ASSET_ID = UUID("33333333-3333-4333-8333-333333333333")
FARM_ID = UUID("44444444-4444-4444-8444-444444444444")
PLOT_ID = UUID("55555555-5555-4555-8555-555555555555")
NOW = datetime(2026, 8, 4, 3, tzinfo=timezone.utc)


def _context(*, write: bool = True) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="principal-1",
        tenant_ref="tenant-1",
        organization_refs=frozenset({"org-1"}),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref="org-1", farm_id=FARM_ID)}
        ),
        plot_scopes=frozenset(
            {
                DBIPlotScope(
                    organization_ref="org-1",
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                )
            }
        ),
        permissions=frozenset(
            {DBIPermission.WRITE if write else DBIPermission.READ}
        ),
    )


def _session_context(
    *,
    session_id: UUID = SESSION_ID,
    state: DBIMultipartSessionState = DBIMultipartSessionState.UPLOADING,
    provider_ref: str | None = "provider-upload-secret-001",
    expires_at: datetime = NOW - timedelta(minutes=1),
) -> DBIMultipartSessionContext:
    plan = DBIMultipartPolicy.build_upload_plan(size_bytes=128 * MIB)
    asset = DBIMultipartAssetSnapshot(
        asset_id=ASSET_ID,
        tenant_ref="tenant-1",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        status="registered",
        content_type="image/tiff",
        size_bytes=plan.size_bytes,
        sha256="a" * 64,
    )
    snapshot = DBIMultipartSessionSnapshot(
        session_id=session_id,
        asset_id=ASSET_ID,
        tenant_ref="tenant-1",
        state=state,
        reason_code=None,
        size_bytes=plan.size_bytes,
        part_size_bytes=plan.part_size_bytes,
        part_count=plan.part_count,
        max_grants_per_window=plan.max_grants_per_window,
        max_client_concurrency=plan.max_client_concurrency,
        checksum_algorithm=plan.checksum_algorithm,
        checksum_type=plan.checksum_type,
        request_fingerprint="f" * 64,
        created_by_ref="principal-1",
        version=2,
        expires_at=expires_at,
        last_activity_at=NOW - timedelta(hours=1),
        created_at=NOW - timedelta(hours=2),
        updated_at=NOW - timedelta(hours=1),
        aborted_at=(NOW if state is DBIMultipartSessionState.ABORTED else None),
        expired_at=(NOW if state is DBIMultipartSessionState.EXPIRED else None),
    )
    return DBIMultipartSessionContext(
        snapshot=snapshot,
        asset=asset,
        provider_upload_ref=provider_ref,
    )


class FakeRepository:
    def __init__(self, contexts: tuple[DBIMultipartSessionContext, ...]) -> None:
        self.contexts = {item.snapshot.session_id: item for item in contexts}
        self.get_calls = 0
        self.claim_calls: list[tuple[datetime, int]] = []
        self.mark_calls: list[tuple[UUID, DBIMultipartSessionState]] = []

    def get_session_for_update(self, **kwargs):
        self.get_calls += 1
        return self.contexts.get(kwargs["session_id"])

    def claim_expired_for_cleanup(self, *, expired_at_or_before, batch_size):
        self.claim_calls.append((expired_at_or_before, batch_size))
        active = (
            DBIMultipartSessionState.INITIATED,
            DBIMultipartSessionState.UPLOADING,
        )
        return tuple(
            item
            for item in self.contexts.values()
            if item.snapshot.state in active
            and item.snapshot.expires_at is not None
            and item.snapshot.expires_at <= expired_at_or_before
        )[:batch_size]

    def mark_terminated(self, *, context, requested_state, changed_at):
        self.mark_calls.append((context.snapshot.session_id, requested_state))
        changed = context.snapshot.state is not requested_state
        snapshot = context.snapshot
        if changed:
            snapshot = replace(
                snapshot,
                state=requested_state,
                version=snapshot.version + 1,
                last_activity_at=changed_at,
                updated_at=changed_at,
                aborted_at=(
                    changed_at
                    if requested_state is DBIMultipartSessionState.ABORTED
                    else None
                ),
                expired_at=(
                    changed_at
                    if requested_state is DBIMultipartSessionState.EXPIRED
                    else None
                ),
            )
        updated = replace(context, snapshot=snapshot, provider_upload_ref=None)
        self.contexts[snapshot.session_id] = updated
        return DBIMultipartTerminationRecord(snapshot=snapshot, changed=changed)


class FakeProvider:
    def __init__(
        self,
        *,
        failures: frozenset[UUID] = frozenset(),
        cleanup_confirmed: bool = True,
    ) -> None:
        self.failures = failures
        self.cleanup_confirmed = cleanup_confirmed
        self.calls = []

    def abort(self, request):
        self.calls.append(request)
        if request.session_id in self.failures:
            raise DBIMultipartProviderConflict("fallo recuperable")
        return DBIMultipartProviderAbortConfirmation(
            session_id=request.session_id,
            aborted_at=request.requested_at,
            provider_uploads_aborted=(
                1 if request.provider_upload_ref is not None else 2
            ),
            cleanup_confirmed=self.cleanup_confirmed,
        )


def _must_raise(error_type, callable_) -> None:
    try:
        callable_()
    except error_type:
        return
    raise AssertionError(f"Se esperaba {error_type.__name__}.")


def validate_authorized_abort_and_retry() -> None:
    repository = FakeRepository((_session_context(),))
    provider = FakeProvider()
    service = DBIMultipartLifecycleService(
        repository,
        provider,
        clock=lambda: NOW,
    )
    result = service.abort(
        _context(),
        organization_ref="org-1",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        session_id=SESSION_ID,
    )
    assert result.session.state is DBIMultipartSessionState.ABORTED
    assert result.session.aborted_at == NOW
    assert result.changed is True
    assert result.provider_uploads_aborted == 1
    assert len(provider.calls) == 1
    assert "provider-upload-secret-001" not in repr(provider.calls[0])

    retry = service.abort(
        _context(),
        organization_ref="org-1",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        session_id=SESSION_ID,
    )
    assert retry.changed is False
    assert retry.provider_uploads_aborted == 0
    assert len(provider.calls) == 1


def validate_authorization_and_terminal_guards() -> None:
    repository = FakeRepository((_session_context(),))
    provider = FakeProvider()
    service = DBIMultipartLifecycleService(repository, provider, clock=lambda: NOW)
    _must_raise(
        DBIAccessDenied,
        lambda: service.abort(
            _context(write=False),
            organization_ref="org-1",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            asset_id=ASSET_ID,
            session_id=SESSION_ID,
        ),
    )
    assert repository.get_calls == 0
    assert provider.calls == []

    completed = _session_context(
        state=DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION,
    )
    completed_repository = FakeRepository((completed,))
    completed_provider = FakeProvider()
    _must_raise(
        DBIMultipartConflict,
        lambda: DBIMultipartLifecycleService(
            completed_repository,
            completed_provider,
            clock=lambda: NOW,
        ).abort(
            _context(),
            organization_ref="org-1",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            asset_id=ASSET_ID,
            session_id=SESSION_ID,
        ),
    )
    assert completed_provider.calls == []


def validate_unbound_and_cleanup_batch() -> None:
    unbound = _session_context(
        state=DBIMultipartSessionState.INITIATED,
        provider_ref=None,
    )
    second = _session_context(
        session_id=SECOND_SESSION_ID,
        provider_ref="provider-upload-secret-002",
    )
    repository = FakeRepository((unbound, second))
    provider = FakeProvider(failures=frozenset({SECOND_SESSION_ID}))
    result = DBIMultipartLifecycleService(
        repository,
        provider,
        clock=lambda: NOW,
    ).cleanup_expired(batch_size=10)
    assert result.scanned == 2
    assert result.expired == 1
    assert result.failed == 1
    assert result.expired_session_ids == (SESSION_ID,)
    assert result.failed_session_ids == (SECOND_SESSION_ID,)
    assert repository.contexts[SESSION_ID].snapshot.state is (
        DBIMultipartSessionState.EXPIRED
    )
    assert repository.contexts[SECOND_SESSION_ID].snapshot.state is (
        DBIMultipartSessionState.UPLOADING
    )
    assert provider.calls[0].provider_upload_ref is None

    uncertain_repository = FakeRepository((_session_context(),))
    uncertain_provider = FakeProvider(cleanup_confirmed=False)
    uncertain_service = DBIMultipartLifecycleService(
        uncertain_repository,
        uncertain_provider,
        clock=lambda: NOW,
    )
    uncertain = uncertain_service.cleanup_expired()
    assert uncertain.scanned == 1
    assert uncertain.expired == 0
    assert uncertain.failed == 1
    assert uncertain_repository.mark_calls == []


def validate_static_boundaries() -> None:
    path = (
        BACKEND / "app" / "dbi" / "asset_multipart_lifecycle_service.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    assert {"fastapi", "sqlalchemy", "boto3", "botocore"}.isdisjoint(roots)
    for forbidden in (
        ".commit(",
        ".rollback(",
        "delete_object",
        "open_read",
        "UploadFile",
    ):
        assert forbidden not in source
    assert source.index("_authorize(") < source.index(
        "self._repository.get_session_for_update("
    )
    assert "context.snapshot.state not in" in source
    assert "DBIMultipartSessionState.INITIATED" in source
    assert "DBIMultipartSessionState.UPLOADING" in source
    assert "claim_expired_for_cleanup(" in source


def main() -> None:
    validate_authorized_abort_and_retry()
    validate_authorization_and_terminal_guards()
    validate_unbound_and_cleanup_batch()
    validate_static_boundaries()
    print("Ciclo de vida multipartes DBI aprobado offline.")


if __name__ == "__main__":
    main()
