"""Repositorio transaccional de preparación multipartes DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.asset_multipart_application import (
    DBIMultipartAssetSnapshot,
    DBIMultipartInitiationRecord,
    DBIMultipartPersistedInitiation,
    DBIMultipartSessionSnapshot,
)
from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm,
    DBIMultipartChecksumType,
    DBIMultipartIdempotencyIdentity,
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
    DBIMultipartUploadPlan,
)
from app.dbi.asset_multipart_policy import (
    DBIMultipartConflict,
    DBIMultipartPolicy,
)
from app.dbi.models.asset_multipart import AssetMultipartSession
from app.dbi.models.assets import AnalysisInputAsset


def _required_uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise DBIMultipartConflict(f"{field_name} debe ser UUID.")
    return value


def _required_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DBIMultipartConflict(f"{field_name} no es canónico.")
    return value


def _utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DBIMultipartConflict(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _asset_snapshot(row: AnalysisInputAsset) -> DBIMultipartAssetSnapshot:
    if not isinstance(row, AnalysisInputAsset):
        raise DBIMultipartConflict("registro de activo inválido.")
    return DBIMultipartAssetSnapshot(
        asset_id=row.id,
        tenant_ref=row.tenant_ref,
        farm_id=row.farm_id,
        plot_id=row.plot_id,
        status=row.status,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
    )


def _session_snapshot(row: AssetMultipartSession) -> DBIMultipartSessionSnapshot:
    if not isinstance(row, AssetMultipartSession):
        raise DBIMultipartConflict("registro de sesión inválido.")
    try:
        state = DBIMultipartSessionState(row.status)
        algorithm = DBIMultipartChecksumAlgorithm(row.checksum_algorithm)
        checksum_type = DBIMultipartChecksumType(row.checksum_type)
    except ValueError as error:
        raise DBIMultipartConflict("sesión durable no canónica.") from error
    return DBIMultipartSessionSnapshot(
        session_id=row.id,
        asset_id=row.asset_id,
        tenant_ref=row.tenant_ref,
        state=state,
        reason_code=row.reason_code,
        size_bytes=row.size_bytes,
        part_size_bytes=row.part_size_bytes,
        part_count=row.part_count,
        max_grants_per_window=row.max_grants_per_window,
        max_client_concurrency=row.max_client_concurrency,
        checksum_algorithm=algorithm,
        checksum_type=checksum_type,
        request_fingerprint=row.request_fingerprint,
        created_by_ref=row.created_by_ref,
        version=row.version,
        expires_at=row.expires_at,
        last_activity_at=row.last_activity_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _snapshot_from_record(
    record: DBIMultipartInitiationRecord,
) -> DBIMultipartSessionSnapshot:
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


def _validate_record(value: object) -> DBIMultipartInitiationRecord:
    if not isinstance(value, DBIMultipartInitiationRecord):
        raise DBIMultipartConflict("record debe ser DBIMultipartInitiationRecord.")
    if not isinstance(value.asset, DBIMultipartAssetSnapshot):
        raise DBIMultipartConflict("asset debe ser DBIMultipartAssetSnapshot.")
    if not isinstance(value.identity, DBIMultipartIdempotencyIdentity):
        raise DBIMultipartConflict(
            "identity debe ser DBIMultipartIdempotencyIdentity."
        )
    if not isinstance(value.plan, DBIMultipartUploadPlan):
        raise DBIMultipartConflict("plan debe ser DBIMultipartUploadPlan.")
    if value.plan.decision is DBIMultipartRoutingDecision.SYNCHRONOUS:
        raise DBIMultipartConflict("el flujo síncrono no crea sesión multipartes.")
    _required_uuid(value.session_id, field_name="session_id")
    _required_ref(value.asset.tenant_ref, field_name="tenant_ref")
    _required_ref(value.created_by_ref, field_name="created_by_ref")
    _utc(value.requested_at, field_name="requested_at")
    if value.plan.decision is DBIMultipartRoutingDecision.MULTIPART:
        if value.expires_at is None or _utc(
            value.expires_at,
            field_name="expires_at",
        ) <= _utc(value.requested_at, field_name="requested_at"):
            raise DBIMultipartConflict("la sesión activa requiere expiración futura.")
    elif value.expires_at is not None:
        raise DBIMultipartConflict("una sesión bloqueada no admite expiración.")
    return value


def _matches_record(
    row: AssetMultipartSession,
    record: DBIMultipartInitiationRecord,
) -> bool:
    DBIMultipartPolicy.validate_idempotent_reuse(
        DBIMultipartIdempotencyIdentity(
            key_hash=row.idempotency_key_hash,
            request_fingerprint=row.request_fingerprint,
        ),
        record.identity,
    )
    blocked = record.plan.decision is DBIMultipartRoutingDecision.BLOCKED_BY_POLICY
    expected_reason = record.plan.reason_code.value if record.plan.reason_code else None
    expected_states = (
        {DBIMultipartSessionState.BLOCKED_BY_POLICY.value}
        if blocked
        else {
            DBIMultipartSessionState.INITIATED.value,
            DBIMultipartSessionState.UPLOADING.value,
            DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION.value,
            DBIMultipartSessionState.ABORTED.value,
            DBIMultipartSessionState.EXPIRED.value,
        }
    )
    return (
        row.asset_id == record.asset.asset_id
        and row.tenant_ref == record.asset.tenant_ref
        and row.status in expected_states
        and row.reason_code == expected_reason
        and row.size_bytes == record.plan.size_bytes
        and row.part_size_bytes == record.plan.part_size_bytes
        and row.part_count == (record.plan.part_count if not blocked else None)
        and row.max_grants_per_window
        == (record.plan.max_grants_per_window if not blocked else None)
        and row.max_client_concurrency
        == (record.plan.max_client_concurrency if not blocked else None)
        and row.checksum_algorithm == record.plan.checksum_algorithm.value
        and row.checksum_type == record.plan.checksum_type.value
        and row.created_by_ref == record.created_by_ref
    )


class DBIMultipartRepository:
    """Persiste preparación multipartes sin commit, rollback o llamadas remotas."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBIMultipartConflict("session debe ser Session.")
        self._session = session

    def get_asset_for_update(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
    ) -> DBIMultipartAssetSnapshot | None:
        """Busca y bloquea el activo dentro del ámbito exacto solicitado."""

        tenant = _required_ref(tenant_ref, field_name="tenant_ref")
        farm = _required_uuid(farm_id, field_name="farm_id")
        asset = _required_uuid(asset_id, field_name="asset_id")
        plot_filter = (
            AnalysisInputAsset.plot_id.is_(None)
            if plot_id is None
            else AnalysisInputAsset.plot_id
            == _required_uuid(plot_id, field_name="plot_id")
        )
        row = self._session.execute(
            select(AnalysisInputAsset)
            .where(
                AnalysisInputAsset.tenant_ref == tenant,
                AnalysisInputAsset.farm_id == farm,
                plot_filter,
                AnalysisInputAsset.id == asset,
            )
            .with_for_update()
        ).scalar_one_or_none()
        return None if row is None else _asset_snapshot(row)

    def _get_by_idempotency_for_update(
        self,
        *,
        tenant_ref: str,
        key_hash: str,
    ) -> AssetMultipartSession | None:
        row = self._session.execute(
            select(AssetMultipartSession)
            .where(
                AssetMultipartSession.tenant_ref == tenant_ref,
                AssetMultipartSession.idempotency_key_hash == key_hash,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is not None and not isinstance(row, AssetMultipartSession):
            raise DBIMultipartConflict("resultado de sesión inválido.")
        return row

    def persist_initiation(
        self,
        *,
        record: DBIMultipartInitiationRecord,
    ) -> DBIMultipartPersistedInitiation:
        """Inserta una vez o devuelve el estado actual de un reintento exacto."""

        initiation = _validate_record(record)
        expected = _snapshot_from_record(initiation)
        inserted_id = self._session.execute(
            postgresql_insert(AssetMultipartSession)
            .values(
                id=expected.session_id,
                asset_id=expected.asset_id,
                tenant_ref=expected.tenant_ref,
                status=expected.state.value,
                reason_code=expected.reason_code,
                provider_upload_ref=None,
                size_bytes=expected.size_bytes,
                part_size_bytes=expected.part_size_bytes,
                part_count=expected.part_count,
                max_grants_per_window=expected.max_grants_per_window,
                max_client_concurrency=expected.max_client_concurrency,
                checksum_algorithm=expected.checksum_algorithm.value,
                checksum_type=expected.checksum_type.value,
                idempotency_key_hash=initiation.identity.key_hash,
                request_fingerprint=expected.request_fingerprint,
                created_by_ref=expected.created_by_ref,
                version=1,
                expires_at=expected.expires_at,
                last_activity_at=expected.last_activity_at,
                completed_at=None,
                aborted_at=None,
                expired_at=None,
                created_at=expected.created_at,
                updated_at=expected.updated_at,
            )
            .on_conflict_do_nothing()
            .returning(AssetMultipartSession.id)
        ).scalar_one_or_none()
        if inserted_id is not None:
            if inserted_id != expected.session_id:
                raise DBIMultipartConflict("identidad insertada divergente.")
            return DBIMultipartPersistedInitiation(
                snapshot=expected,
                created=True,
            )

        existing = self._get_by_idempotency_for_update(
            tenant_ref=expected.tenant_ref,
            key_hash=initiation.identity.key_hash,
        )
        if existing is None or not _matches_record(existing, initiation):
            raise DBIMultipartConflict("sesión multipartes incompatible.")
        return DBIMultipartPersistedInitiation(
            snapshot=_session_snapshot(existing),
            created=False,
        )
