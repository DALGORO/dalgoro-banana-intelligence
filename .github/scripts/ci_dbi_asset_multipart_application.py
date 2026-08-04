"""Pruebas offline del servicio de aplicación multipartes DBI."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from app.dbi.asset_multipart_application import (
    DBIMultipartApplicationService,
    DBIMultipartAssetSnapshot,
    DBIMultipartInitiationRecord,
    DBIMultipartPersistedInitiation,
    DBIMultipartSessionSnapshot,
    DBIMultipartUnavailable,
)
from app.dbi.asset_multipart_contracts import (
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
)
from app.dbi.asset_multipart_policy import GIB, MIB
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
ASSET_ID = UUID("11111111-1111-4111-8111-111111111111")
SESSION_ID = UUID("22222222-2222-4222-8222-222222222222")
FARM_ID = UUID("33333333-3333-4333-8333-333333333333")
PLOT_ID = UUID("44444444-4444-4444-8444-444444444444")
NOW = datetime(2026, 8, 3, 20, tzinfo=timezone.utc)


def _snapshot(record: DBIMultipartInitiationRecord) -> DBIMultipartSessionSnapshot:
    blocked = record.plan.decision is DBIMultipartRoutingDecision.BLOCKED_BY_POLICY
    return DBIMultipartSessionSnapshot(
        session_id=record.session_id,
        asset_id=record.asset.asset_id,
        tenant_ref=record.asset.tenant_ref,
        state=(
            DBIMultipartSessionState.BLOCKED_BY_POLICY
            if blocked
            else DBIMultipartSessionState.INITIATED
        ),
        reason_code=(record.plan.reason_code.value if record.plan.reason_code else None),
        size_bytes=record.plan.size_bytes,
        part_size_bytes=record.plan.part_size_bytes,
        part_count=(record.plan.part_count if not blocked else None),
        max_grants_per_window=(
            record.plan.max_grants_per_window if not blocked else None
        ),
        max_client_concurrency=(
            record.plan.max_client_concurrency if not blocked else None
        ),
        checksum_algorithm=record.plan.checksum_algorithm,
        checksum_type=record.plan.checksum_type,
        request_fingerprint=record.identity.request_fingerprint,
        created_by_ref=record.created_by_ref,
        version=1,
        expires_at=record.expires_at,
        last_activity_at=record.requested_at,
        created_at=record.requested_at,
        updated_at=record.requested_at,
    )


class FakeRepository:
    def __init__(
        self,
        asset: DBIMultipartAssetSnapshot | None,
        *,
        created: bool = True,
    ) -> None:
        self.asset = asset
        self.created = created
        self.asset_calls: list[dict[str, object]] = []
        self.records: list[DBIMultipartInitiationRecord] = []

    def get_asset_for_update(self, **kwargs):
        self.asset_calls.append(kwargs)
        return self.asset

    def persist_initiation(
        self,
        *,
        record: DBIMultipartInitiationRecord,
    ) -> DBIMultipartPersistedInitiation:
        self.records.append(record)
        return DBIMultipartPersistedInitiation(
            snapshot=_snapshot(record),
            created=self.created,
        )


def _asset(
    *,
    size_bytes: int,
    plot_id: UUID | None = PLOT_ID,
    status: str = "registered",
) -> DBIMultipartAssetSnapshot:
    return DBIMultipartAssetSnapshot(
        asset_id=ASSET_ID,
        tenant_ref="tenant-a",
        farm_id=FARM_ID,
        plot_id=plot_id,
        status=status,
        content_type="image/tiff",
        size_bytes=size_bytes,
        sha256="a" * 64,
    )


def _context(*, plot_id: UUID | None = PLOT_ID, write: bool = True):
    farms = frozenset(
        {DBIFarmScope(organization_ref="org-a", farm_id=FARM_ID)}
    )
    plots = (
        frozenset(
            {
                DBIPlotScope(
                    organization_ref="org-a",
                    farm_id=FARM_ID,
                    plot_id=plot_id,
                )
            }
        )
        if plot_id is not None
        else frozenset()
    )
    return DBIAccessContext(
        principal_ref="principal-a",
        tenant_ref="tenant-a",
        organization_refs=frozenset({"org-a"}),
        farm_scopes=farms,
        plot_scopes=plots,
        permissions=frozenset(
            {DBIPermission.WRITE if write else DBIPermission.READ}
        ),
    )


def _service(repository: FakeRepository) -> DBIMultipartApplicationService:
    return DBIMultipartApplicationService(
        repository,
        clock=lambda: NOW,
        session_id_factory=lambda: SESSION_ID,
    )


def _prepare(service, *, plot_id=PLOT_ID, key="upload-request-0001"):
    return service.prepare(
        _context(plot_id=plot_id),
        organization_ref="org-a",
        farm_id=FARM_ID,
        plot_id=plot_id,
        asset_id=ASSET_ID,
        idempotency_key=key,
    )


def _must_deny(callable_) -> None:
    try:
        callable_()
    except DBIAccessDenied:
        return
    raise AssertionError("La operación debía ser denegada.")


def _must_be_unavailable(callable_) -> None:
    try:
        callable_()
    except DBIMultipartUnavailable:
        return
    raise AssertionError("El activo no debía quedar disponible.")


def validate_synchronous_routing() -> None:
    repository = FakeRepository(_asset(size_bytes=32 * MIB))
    evidence = _prepare(_service(repository))
    assert evidence.plan.decision is DBIMultipartRoutingDecision.SYNCHRONOUS
    assert evidence.session is None
    assert evidence.created is False
    assert repository.records == []
    assert repository.asset_calls == [
        {
            "tenant_ref": "tenant-a",
            "farm_id": FARM_ID,
            "plot_id": PLOT_ID,
            "asset_id": ASSET_ID,
        }
    ]


def validate_multipart_preparation() -> None:
    repository = FakeRepository(_asset(size_bytes=10 * GIB))
    evidence = _prepare(_service(repository))
    assert evidence.plan.decision is DBIMultipartRoutingDecision.MULTIPART
    assert evidence.plan.part_count == 160
    assert evidence.plan.part_size_bytes == 64 * MIB
    assert evidence.created is True
    assert evidence.session is not None
    assert evidence.session.state is DBIMultipartSessionState.INITIATED
    assert evidence.session.expires_at == NOW + timedelta(hours=24)
    assert evidence.session.version == 1
    assert len(repository.records) == 1
    record = repository.records[0]
    assert record.created_by_ref == "principal-a"
    assert record.asset.sha256 == "a" * 64
    assert "upload-request-0001" not in repr(record)
    assert "upload-request-0001" not in repr(evidence)


def validate_exact_reuse() -> None:
    repository = FakeRepository(_asset(size_bytes=10 * GIB), created=False)
    evidence = _prepare(_service(repository))
    assert evidence.created is False
    assert evidence.session is not None
    assert evidence.session.session_id == SESSION_ID
    assert len(repository.records) == 1


def validate_blocked_policy_is_persisted() -> None:
    repository = FakeRepository(_asset(size_bytes=21 * GIB))
    evidence = _prepare(_service(repository))
    assert evidence.plan.decision is DBIMultipartRoutingDecision.BLOCKED_BY_POLICY
    assert evidence.session is not None
    assert evidence.session.state is DBIMultipartSessionState.BLOCKED_BY_POLICY
    assert evidence.session.reason_code == "asset_multipart_size_exceeds_policy"
    assert evidence.session.expires_at is None
    assert len(repository.records) == 1


def validate_farm_level_asset() -> None:
    repository = FakeRepository(_asset(size_bytes=10 * GIB, plot_id=None))
    evidence = _prepare(_service(repository), plot_id=None)
    assert evidence.session is not None
    assert repository.asset_calls[0]["plot_id"] is None


def validate_authorization_and_non_enumeration() -> None:
    denied_repository = FakeRepository(_asset(size_bytes=10 * GIB))
    service = _service(denied_repository)
    _must_deny(
        lambda: service.prepare(
            _context(write=False),
            organization_ref="org-a",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            asset_id=ASSET_ID,
            idempotency_key="upload-request-0001",
        )
    )
    _must_deny(
        lambda: service.prepare(
            _context(),
            organization_ref="org-b",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            asset_id=ASSET_ID,
            idempotency_key="upload-request-0001",
        )
    )
    assert denied_repository.asset_calls == []
    assert denied_repository.records == []

    for unavailable in (
        None,
        _asset(size_bytes=10 * GIB, status="verified"),
    ):
        repository = FakeRepository(unavailable)
        _must_be_unavailable(lambda: _prepare(_service(repository)))
        assert repository.records == []


def validate_static_boundaries() -> None:
    path = BACKEND_ROOT / "app" / "dbi" / "asset_multipart_application.py"
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
        "sqlalchemy",
    }.isdisjoint(roots)
    for forbidden in (
        "provider_upload_ref",
        "presigned",
        "signed_url",
        "bucket",
        ".commit(",
        ".rollback(",
    ):
        assert forbidden not in source


def main() -> None:
    validate_synchronous_routing()
    validate_multipart_preparation()
    validate_exact_reuse()
    validate_blocked_policy_is_persisted()
    validate_farm_level_asset()
    validate_authorization_and_non_enumeration()
    validate_static_boundaries()
    print("Servicio de aplicación multipartes DBI-ASSET-003 aprobado offline.")


if __name__ == "__main__":
    main()
