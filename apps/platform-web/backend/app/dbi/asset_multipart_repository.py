"""Repositorio transaccional de preparación multipartes DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, func, select
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
    DBIMultipartPartEvidence,
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
    DBIMultipartUploadPlan,
)
from app.dbi.asset_multipart_policy import (
    DBIMultipartConflict,
    DBIMultipartPolicy,
)
from app.dbi.asset_multipart_upload_service import (
    DBIMultipartCompletionRecord,
    DBIMultipartPartRecord,
    DBIMultipartSessionContext,
)
from app.dbi.models.asset_multipart import (
    AssetMultipartPart,
    AssetMultipartSession,
)
from app.dbi.models.assets import AnalysisInputAsset


def _required_uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise DBIMultipartConflict(f"{field_name} debe ser UUID.")
    return value


def _required_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DBIMultipartConflict(f"{field_name} no es canónico.")
    return value


def _provider_ref(value: object) -> str:
    reference = _required_ref(value, field_name="provider_upload_ref")
    if (
        len(reference) > 1024
        or any(ord(character) < 32 or ord(character) == 127 for character in reference)
    ):
        raise DBIMultipartConflict("provider_upload_ref no es canónica.")
    return reference


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
        completed_at=row.completed_at,
        aborted_at=row.aborted_at,
        expired_at=row.expired_at,
    )


def _part_evidence(row: AssetMultipartPart) -> DBIMultipartPartEvidence:
    if not isinstance(row, AssetMultipartPart):
        raise DBIMultipartConflict("registro de parte inválido.")
    return DBIMultipartPartEvidence(
        session_id=row.session_id,
        part_number=row.part_number,
        size_bytes=row.size_bytes,
        checksum=row.checksum,
        etag=row.etag,
    )


def _validate_session_context(value: object) -> DBIMultipartSessionContext:
    if not isinstance(value, DBIMultipartSessionContext):
        raise DBIMultipartConflict(
            "context debe ser DBIMultipartSessionContext."
        )
    if (
        value.snapshot.asset_id != value.asset.asset_id
        or value.snapshot.tenant_ref != value.asset.tenant_ref
    ):
        raise DBIMultipartConflict("contexto multipartes divergente.")
    return value


def _upload_plan(snapshot: DBIMultipartSessionSnapshot) -> DBIMultipartUploadPlan:
    if (
        snapshot.part_size_bytes is None
        or snapshot.part_count is None
        or snapshot.max_grants_per_window is None
        or snapshot.max_client_concurrency is None
    ):
        raise DBIMultipartConflict("la sesión no contiene un plan multipartes.")
    return DBIMultipartUploadPlan(
        decision=DBIMultipartRoutingDecision.MULTIPART,
        size_bytes=snapshot.size_bytes,
        part_size_bytes=snapshot.part_size_bytes,
        part_count=snapshot.part_count,
        max_grants_per_window=snapshot.max_grants_per_window,
        max_client_concurrency=snapshot.max_client_concurrency,
        checksum_algorithm=snapshot.checksum_algorithm,
        checksum_type=snapshot.checksum_type,
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

    def get_session_for_update(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        session_id: UUID,
    ) -> DBIMultipartSessionContext | None:
        """Bloquea sesión y activo bajo el ámbito exacto del solicitante."""

        tenant = _required_ref(tenant_ref, field_name="tenant_ref")
        farm = _required_uuid(farm_id, field_name="farm_id")
        asset = _required_uuid(asset_id, field_name="asset_id")
        multipart_session = _required_uuid(
            session_id,
            field_name="session_id",
        )
        plot_filter = (
            AnalysisInputAsset.plot_id.is_(None)
            if plot_id is None
            else AnalysisInputAsset.plot_id
            == _required_uuid(plot_id, field_name="plot_id")
        )
        result = self._session.execute(
            select(AssetMultipartSession, AnalysisInputAsset)
            .join(
                AnalysisInputAsset,
                and_(
                    AnalysisInputAsset.id == AssetMultipartSession.asset_id,
                    AnalysisInputAsset.tenant_ref
                    == AssetMultipartSession.tenant_ref,
                ),
            )
            .where(
                AssetMultipartSession.id == multipart_session,
                AssetMultipartSession.asset_id == asset,
                AssetMultipartSession.tenant_ref == tenant,
                AnalysisInputAsset.farm_id == farm,
                plot_filter,
            )
            .with_for_update()
        ).one_or_none()
        if result is None:
            return None
        session_row, asset_row = result
        if (
            not isinstance(session_row, AssetMultipartSession)
            or not isinstance(asset_row, AnalysisInputAsset)
        ):
            raise DBIMultipartConflict("resultado multipartes inválido.")
        return DBIMultipartSessionContext(
            snapshot=_session_snapshot(session_row),
            asset=_asset_snapshot(asset_row),
            provider_upload_ref=session_row.provider_upload_ref,
        )

    def _session_row_for_update(
        self,
        context: DBIMultipartSessionContext,
    ) -> AssetMultipartSession:
        canonical = _validate_session_context(context)
        row = self._session.execute(
            select(AssetMultipartSession)
            .where(
                AssetMultipartSession.id == canonical.snapshot.session_id,
                AssetMultipartSession.asset_id == canonical.snapshot.asset_id,
                AssetMultipartSession.tenant_ref
                == canonical.snapshot.tenant_ref,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if not isinstance(row, AssetMultipartSession):
            raise DBIMultipartConflict("sesión multipartes no disponible.")
        return row

    def bind_provider_upload(
        self,
        *,
        context: DBIMultipartSessionContext,
        provider_upload_ref: str,
        changed_at: datetime,
    ) -> DBIMultipartSessionContext:
        """Vincula una referencia remota exacta y transita a uploading."""

        canonical = _validate_session_context(context)
        reference = _provider_ref(provider_upload_ref)
        timestamp = _utc(changed_at, field_name="changed_at")
        row = self._session_row_for_update(canonical)
        transition = DBIMultipartPolicy.plan_transition(
            DBIMultipartSessionState(row.status),
            DBIMultipartSessionState.UPLOADING,
        )
        if row.provider_upload_ref not in {None, reference}:
            raise DBIMultipartConflict("la sesión ya usa otra carga remota.")
        if transition.changed:
            row.status = transition.next_state.value
            row.provider_upload_ref = reference
            row.version += 1
            row.last_activity_at = timestamp
            row.updated_at = timestamp
        elif row.provider_upload_ref != reference:
            raise DBIMultipartConflict("la carga remota no coincide.")
        return DBIMultipartSessionContext(
            snapshot=_session_snapshot(row),
            asset=canonical.asset,
            provider_upload_ref=row.provider_upload_ref,
        )

    def record_part(
        self,
        *,
        context: DBIMultipartSessionContext,
        evidence: DBIMultipartPartEvidence,
        observed_at: datetime,
    ) -> DBIMultipartPartRecord:
        """Inserta evidencia exacta o reconoce un reintento equivalente."""

        canonical = _validate_session_context(context)
        timestamp = _utc(observed_at, field_name="observed_at")
        row = self._session_row_for_update(canonical)
        if DBIMultipartSessionState(row.status) is not DBIMultipartSessionState.UPLOADING:
            raise DBIMultipartConflict("la sesión no admite nuevas partes.")
        part = DBIMultipartPolicy.validate_part_evidence(
            evidence,
            plan=_upload_plan(_session_snapshot(row)),
        )
        if part.session_id != row.id:
            raise DBIMultipartConflict("la parte pertenece a otra sesión.")
        existing = self._session.execute(
            select(AssetMultipartPart).where(
                AssetMultipartPart.session_id == row.id,
                AssetMultipartPart.part_number == part.part_number,
                AssetMultipartPart.tenant_ref == row.tenant_ref,
            )
        ).scalar_one_or_none()
        created = existing is None
        if created:
            stored = AssetMultipartPart(
                session_id=row.id,
                part_number=part.part_number,
                tenant_ref=row.tenant_ref,
                size_bytes=part.size_bytes,
                checksum=part.checksum,
                etag=part.etag,
                observed_at=timestamp,
            )
            self._session.add(stored)
            row.version += 1
            row.last_activity_at = timestamp
            row.updated_at = timestamp
        else:
            stored = existing
            if (
                not isinstance(stored, AssetMultipartPart)
                or _part_evidence(stored) != part
            ):
                raise DBIMultipartConflict(
                    "la parte registrada contradice el reintento."
                )
        recorded_count = self._session.execute(
            select(func.count())
            .select_from(AssetMultipartPart)
            .where(
                AssetMultipartPart.session_id == row.id,
                AssetMultipartPart.tenant_ref == row.tenant_ref,
            )
        ).scalar_one()
        if not isinstance(recorded_count, int) or recorded_count < 1:
            raise DBIMultipartConflict("conteo durable de partes inválido.")
        return DBIMultipartPartRecord(
            snapshot=_session_snapshot(row),
            evidence=_part_evidence(stored),
            created=created,
            recorded_part_count=recorded_count,
        )

    def list_parts(
        self,
        *,
        context: DBIMultipartSessionContext,
    ) -> tuple[DBIMultipartPartEvidence, ...]:
        """Lista evidencia ordenada sin exponer el modelo persistente."""

        canonical = _validate_session_context(context)
        rows = self._session.execute(
            select(AssetMultipartPart)
            .where(
                AssetMultipartPart.session_id
                == canonical.snapshot.session_id,
                AssetMultipartPart.tenant_ref
                == canonical.snapshot.tenant_ref,
            )
            .order_by(AssetMultipartPart.part_number)
        ).scalars().all()
        return tuple(_part_evidence(row) for row in rows)

    def mark_completed(
        self,
        *,
        context: DBIMultipartSessionContext,
        completed_at: datetime,
    ) -> DBIMultipartCompletionRecord:
        """Confirma la transición durable después del efecto del proveedor."""

        canonical = _validate_session_context(context)
        timestamp = _utc(completed_at, field_name="completed_at")
        row = self._session_row_for_update(canonical)
        transition = DBIMultipartPolicy.plan_transition(
            DBIMultipartSessionState(row.status),
            DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION,
        )
        if transition.changed:
            row.status = transition.next_state.value
            row.completed_at = timestamp
            row.version += 1
            row.last_activity_at = timestamp
            row.updated_at = timestamp
        elif row.completed_at is None:
            raise DBIMultipartConflict(
                "la sesión completada no tiene fecha durable."
            )
        return DBIMultipartCompletionRecord(
            snapshot=_session_snapshot(row),
            changed=transition.changed,
        )

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
