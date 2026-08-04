"""Valida el repositorio multipartes DBI sin conexiones externas."""

from __future__ import annotations

import ast
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MethodType
from uuid import UUID

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.dbi.asset_multipart_application import (  # noqa: E402
    DBIMultipartAssetSnapshot,
    DBIMultipartInitiationRecord,
)
from app.dbi.asset_multipart_contracts import (  # noqa: E402
    DBIMultipartPartEvidence,
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
)
from app.dbi.asset_multipart_policy import (  # noqa: E402
    GIB,
    DBIMultipartConflict,
    DBIMultipartPolicy,
)
from app.dbi.asset_multipart_repository import (  # noqa: E402
    DBIMultipartRepository,
    _session_snapshot,
)
from app.dbi.asset_multipart_upload_service import (  # noqa: E402
    DBIMultipartSessionContext,
)
from app.dbi.models.asset_multipart import (  # noqa: E402
    AssetMultipartPart,
    AssetMultipartSession,
)
from app.dbi.models.assets import AnalysisInputAsset  # noqa: E402

ASSET_ID = UUID("11111111-1111-4111-8111-111111111111")
SESSION_ID = UUID("22222222-2222-4222-8222-222222222222")
EXISTING_SESSION_ID = UUID("33333333-3333-4333-8333-333333333333")
FARM_ID = UUID("44444444-4444-4444-8444-444444444444")
PLOT_ID = UUID("55555555-5555-4555-8555-555555555555")
NOW = datetime(2026, 8, 3, 20, tzinfo=timezone.utc)


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


def _session(results: list[object], statements: list[object]) -> Session:
    session = Session()

    def execute(self, statement):
        statements.append(statement)
        if not results:
            raise AssertionError("No había resultado preparado para execute().")
        return ScalarResult(results.pop(0))

    session.execute = MethodType(execute, session)  # type: ignore[method-assign]
    return session


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    )


def _asset_row(*, size_bytes: int = 10 * GIB) -> AnalysisInputAsset:
    return AnalysisInputAsset(
        id=ASSET_ID,
        tenant_ref="tenant-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_kind="orthophoto",
        status="registered",
        object_key=f"tenants/tenant-a/analysis-input/{ASSET_ID}",
        content_type="image/tiff",
        size_bytes=size_bytes,
        sha256="a" * 64,
        crs="EPSG:32717",
        created_by_ref="principal-a",
        verified_at=None,
    )


def _asset_snapshot(*, size_bytes: int = 10 * GIB) -> DBIMultipartAssetSnapshot:
    return DBIMultipartAssetSnapshot(
        asset_id=ASSET_ID,
        tenant_ref="tenant-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        status="registered",
        content_type="image/tiff",
        size_bytes=size_bytes,
        sha256="a" * 64,
    )


def _record(
    *,
    size_bytes: int = 10 * GIB,
    idempotency_key: str = "upload-request-0001",
) -> DBIMultipartInitiationRecord:
    asset = _asset_snapshot(size_bytes=size_bytes)
    plan = DBIMultipartPolicy.build_upload_plan(size_bytes=size_bytes)
    identity = DBIMultipartPolicy.build_idempotency_identity(
        idempotency_key=idempotency_key,
        asset_id=asset.asset_id,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        sha256_hex=asset.sha256,
    )
    return DBIMultipartInitiationRecord(
        session_id=SESSION_ID,
        asset=asset,
        plan=plan,
        identity=identity,
        created_by_ref="principal-a",
        requested_at=NOW,
        expires_at=(
            NOW + timedelta(hours=24)
            if plan.decision is DBIMultipartRoutingDecision.MULTIPART
            else None
        ),
    )


def _session_row(
    record: DBIMultipartInitiationRecord,
    *,
    state: DBIMultipartSessionState = DBIMultipartSessionState.INITIATED,
    request_fingerprint: str | None = None,
) -> AssetMultipartSession:
    blocked = record.plan.decision is DBIMultipartRoutingDecision.BLOCKED_BY_POLICY
    return AssetMultipartSession(
        id=EXISTING_SESSION_ID,
        asset_id=record.asset.asset_id,
        tenant_ref=record.asset.tenant_ref,
        status=state.value,
        reason_code=(record.plan.reason_code.value if record.plan.reason_code else None),
        provider_upload_ref="provider-secret-reference",
        size_bytes=record.plan.size_bytes,
        part_size_bytes=record.plan.part_size_bytes,
        part_count=(record.plan.part_count if not blocked else None),
        max_grants_per_window=(
            record.plan.max_grants_per_window if not blocked else None
        ),
        max_client_concurrency=(
            record.plan.max_client_concurrency if not blocked else None
        ),
        checksum_algorithm=record.plan.checksum_algorithm.value,
        checksum_type=record.plan.checksum_type.value,
        idempotency_key_hash=record.identity.key_hash,
        request_fingerprint=(
            request_fingerprint or record.identity.request_fingerprint
        ),
        created_by_ref=record.created_by_ref,
        version=2,
        expires_at=record.expires_at,
        last_activity_at=NOW,
        completed_at=None,
        aborted_at=None,
        expired_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _context(
    row: AssetMultipartSession,
) -> DBIMultipartSessionContext:
    return DBIMultipartSessionContext(
        snapshot=_session_snapshot(row),
        asset=_asset_snapshot(size_bytes=row.size_bytes),
        provider_upload_ref=row.provider_upload_ref,
    )


def _part(number: int) -> AssetMultipartPart:
    return AssetMultipartPart(
        session_id=EXISTING_SESSION_ID,
        part_number=number,
        tenant_ref="tenant-a",
        size_bytes=64 * 1024 * 1024,
        checksum="cGFydC1jaGVja3N1bS1zeW50aGV0aWM=",
        etag=f"etag-{number}",
        observed_at=NOW,
    )


def _must_conflict(callable_) -> None:
    try:
        callable_()
    except DBIMultipartConflict:
        return
    raise AssertionError("La operación debía fallar cerrada.")


def validate_asset_scope_lock() -> None:
    statements: list[object] = []
    session = _session([_asset_row()], statements)
    repository = DBIMultipartRepository(session)
    snapshot = repository.get_asset_for_update(
        tenant_ref="tenant-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
    )
    assert snapshot == _asset_snapshot()
    assert len(statements) == 1
    sql = _sql(statements[0])
    for required in ("tenant_ref", "farm_id", "plot_id", "FOR UPDATE"):
        assert required in sql
    assert "dbi_analysis_input_assets.id" in sql
    session.close()


def validate_multipart_insert() -> None:
    record = _record()
    statements: list[object] = []
    session = _session([SESSION_ID], statements)
    result = DBIMultipartRepository(session).persist_initiation(record=record)
    assert result.created is True
    assert result.snapshot.session_id == SESSION_ID
    assert result.snapshot.state is DBIMultipartSessionState.INITIATED
    assert result.snapshot.part_count == 160
    assert result.snapshot.expires_at == NOW + timedelta(hours=24)
    assert "upload-request-0001" not in repr(result)
    assert len(statements) == 1
    sql = _sql(statements[0])
    assert "INSERT INTO dbi_asset_multipart_sessions" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    assert "RETURNING dbi_asset_multipart_sessions.id" in sql
    assert "provider_upload_ref" in sql
    assert "commit" not in sql.lower()
    session.close()


def validate_exact_retry_returns_current_state() -> None:
    record = _record()
    existing = _session_row(
        record,
        state=DBIMultipartSessionState.UPLOADING,
    )
    statements: list[object] = []
    session = _session([None, existing], statements)
    result = DBIMultipartRepository(session).persist_initiation(record=record)
    assert result.created is False
    assert result.snapshot.session_id == EXISTING_SESSION_ID
    assert result.snapshot.state is DBIMultipartSessionState.UPLOADING
    assert "provider-secret-reference" not in repr(result)
    assert record.identity.key_hash not in repr(result)
    assert len(statements) == 2
    retry_sql = _sql(statements[1])
    assert "idempotency_key_hash" in retry_sql
    assert "tenant_ref" in retry_sql
    assert "FOR UPDATE" in retry_sql
    session.close()


def validate_conflicts() -> None:
    record = _record()
    divergent = _session_row(record, request_fingerprint="b" * 64)
    for existing in (divergent, None):
        statements: list[object] = []
        session = _session([None, existing], statements)
        _must_conflict(
            lambda: DBIMultipartRepository(session).persist_initiation(
                record=record
            )
        )
        assert len(statements) == 2
        session.close()


def validate_blocked_is_visible_and_provider_free() -> None:
    record = _record(size_bytes=21 * GIB)
    assert record.plan.decision is DBIMultipartRoutingDecision.BLOCKED_BY_POLICY
    statements: list[object] = []
    session = _session([SESSION_ID], statements)
    result = DBIMultipartRepository(session).persist_initiation(record=record)
    assert result.snapshot.state is DBIMultipartSessionState.BLOCKED_BY_POLICY
    assert result.snapshot.reason_code == "asset_multipart_size_exceeds_policy"
    assert result.snapshot.part_size_bytes is None
    assert result.snapshot.part_count is None
    assert result.snapshot.expires_at is None
    session.close()


def validate_session_scope_and_provider_binding() -> None:
    record = _record()
    row = _session_row(record)
    statements: list[object] = []
    session = _session([(row, _asset_row())], statements)
    repository = DBIMultipartRepository(session)
    context = repository.get_session_for_update(
        tenant_ref="tenant-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_id=ASSET_ID,
        session_id=EXISTING_SESSION_ID,
    )
    assert context.snapshot.session_id == EXISTING_SESSION_ID
    assert "provider-secret-reference" not in repr(context)
    sql = _sql(statements[0])
    for required in (
        "dbi_asset_multipart_sessions.id",
        "dbi_analysis_input_assets.farm_id",
        "dbi_analysis_input_assets.plot_id",
        "FOR UPDATE",
    ):
        assert required in sql
    session.close()

    initiated = _session_row(
        record,
        state=DBIMultipartSessionState.INITIATED,
    )
    initiated.provider_upload_ref = None
    statements = []
    session = _session([initiated], statements)
    bound = DBIMultipartRepository(session).bind_provider_upload(
        context=DBIMultipartSessionContext(
            snapshot=_context(initiated).snapshot,
            asset=_asset_snapshot(),
        ),
        provider_upload_ref="provider-upload-secret-002",
        changed_at=NOW + timedelta(minutes=1),
    )
    assert bound.snapshot.state is DBIMultipartSessionState.UPLOADING
    assert bound.snapshot.version == 3
    assert "provider-upload-secret-002" not in repr(bound)
    assert "FOR UPDATE" in _sql(statements[0])
    session.close()


def validate_part_and_completion_persistence() -> None:
    record = _record(size_bytes=128 * 1024 * 1024)
    row = _session_row(
        record,
        state=DBIMultipartSessionState.UPLOADING,
    )
    context = _context(row)
    evidence = DBIMultipartPartEvidence(
        session_id=EXISTING_SESSION_ID,
        part_number=1,
        size_bytes=64 * 1024 * 1024,
        checksum="cHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHA=",
        etag="etag-1",
    )
    statements: list[object] = []
    session = _session([row, None, 1], statements)
    result = DBIMultipartRepository(session).record_part(
        context=context,
        evidence=evidence,
        observed_at=NOW + timedelta(minutes=1),
    )
    assert result.created is True
    assert result.recorded_part_count == 1
    assert result.evidence == evidence
    assert row.version == 3
    assert evidence.checksum not in repr(result)
    assert evidence.etag not in repr(result)
    assert any("count" in _sql(statement).lower() for statement in statements)
    session.close()

    first = _part(1)
    second = _part(2)
    statements = []
    session = _session([[first, second]], statements)
    listed = DBIMultipartRepository(session).list_parts(context=context)
    assert [part.part_number for part in listed] == [1, 2]
    assert "ORDER BY" in _sql(statements[0])
    session.close()

    statements = []
    session = _session([row], statements)
    completed = DBIMultipartRepository(session).mark_completed(
        context=context,
        completed_at=NOW + timedelta(minutes=5),
    )
    assert completed.changed is True
    assert completed.snapshot.state is (
        DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION
    )
    assert completed.snapshot.completed_at == NOW + timedelta(minutes=5)
    session.close()


def validate_static_boundaries() -> None:
    path = BACKEND_ROOT / "app" / "dbi" / "asset_multipart_repository.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    assert {
        "fastapi",
        "boto3",
        "botocore",
        "requests",
        "httpx",
    }.isdisjoint(roots)
    for forbidden in (
        ".commit(",
        ".rollback(",
        "SessionLocal",
        "DATABASE_URL",
        "presigned",
        "signed_url",
    ):
        assert forbidden not in source
    assert ".with_for_update()" in source
    assert ".on_conflict_do_nothing()" in source


def main() -> None:
    validate_asset_scope_lock()
    validate_multipart_insert()
    validate_exact_retry_returns_current_state()
    validate_conflicts()
    validate_blocked_is_visible_and_provider_free()
    validate_session_scope_and_provider_binding()
    validate_part_and_completion_persistence()
    validate_static_boundaries()
    print("Repositorio multipartes DBI-ASSET-003 aprobado offline.")


if __name__ == "__main__":
    main()
