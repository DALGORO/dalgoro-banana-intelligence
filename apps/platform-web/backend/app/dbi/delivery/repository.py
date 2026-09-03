"""Repositorio transaccional para mensajes durables DBI."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.delivery.contracts import (
    DeliveryEnvelope,
    DeliveryLease,
    DeliveryLeaseRenewalEvidence,
    DeliveryMessageStatus,
    DeliveryMessageUnavailable,
    DeliveryPersistenceConflict,
    DeliveryStream,
    DeliveryTransitionEvidence,
    PreparedDeliveryPayload,
)
from app.dbi.models.delivery import DBIDeliveryMessage

_ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _utc(value: datetime, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DeliveryPersistenceConflict(
            f"{field_name} debe incluir zona horaria."
        )
    return value.astimezone(timezone.utc)


def _uuid(value: UUID, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise DeliveryPersistenceConflict(f"{field_name} debe ser UUID.")
    return value


def _ref(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DeliveryPersistenceConflict(f"{field_name} no es canónico.")
    return value


def _error_code(value: str) -> str:
    normalized = _ref(value, field_name="error_code")
    if _ERROR_CODE_PATTERN.fullmatch(normalized) is None:
        raise DeliveryPersistenceConflict("error_code no es canónico.")
    return normalized


def _stream(value: object) -> DeliveryStream:
    try:
        return DeliveryStream(value)
    except (TypeError, ValueError) as error:
        raise DeliveryPersistenceConflict("stream persistido inválido.") from error


def _status(value: object) -> DeliveryMessageStatus:
    try:
        return DeliveryMessageStatus(value)
    except (TypeError, ValueError) as error:
        raise DeliveryPersistenceConflict("estado persistido inválido.") from error


def _lease_seconds(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 3600:
        raise DeliveryPersistenceConflict("lease_seconds fuera de rango.")
    return value


def _envelope(row: DBIDeliveryMessage) -> DeliveryEnvelope:
    stream = _stream(row.stream)
    payload = PreparedDeliveryPayload(
        stream=stream,
        schema_version=row.schema_version,
        payload_json=row.payload_json,
        payload_sha256=row.payload_sha256,
    )
    return DeliveryEnvelope(
        message_id=row.id,
        stream=stream,
        job_id=row.job_id,
        attempt_id=row.attempt_id,
        correlation_id=row.correlation_id,
        payload=payload,
        status=_status(row.status),
        available_at=_utc(row.available_at, field_name="available_at"),
        delivery_count=row.delivery_count,
        max_deliveries=row.max_deliveries,
    )


class DBIDeliveryRepository:
    """Persistencia sin commit, rollback, red ni efectos de worker."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DeliveryPersistenceConflict("session debe ser Session.")
        self._session = session

    def publish(
        self,
        *,
        job_id: UUID,
        attempt_id: UUID,
        correlation_id: str,
        payload: PreparedDeliveryPayload,
        available_at: datetime,
        max_deliveries: int = 5,
    ) -> tuple[DeliveryEnvelope, bool]:
        """Publica por stream+attempt de forma idempotente."""

        job = _uuid(job_id, field_name="job_id")
        attempt = _uuid(attempt_id, field_name="attempt_id")
        correlation = _ref(correlation_id, field_name="correlation_id")
        available = _utc(available_at, field_name="available_at")
        if not isinstance(payload, PreparedDeliveryPayload):
            raise DeliveryPersistenceConflict("payload debe estar preparado.")
        if not isinstance(max_deliveries, int) or not 1 <= max_deliveries <= 100:
            raise DeliveryPersistenceConflict("max_deliveries fuera de rango.")

        message_id = uuid4()
        inserted = self._session.execute(
            postgresql_insert(DBIDeliveryMessage)
            .values(
                id=message_id,
                stream=payload.stream.value,
                job_id=job,
                attempt_id=attempt,
                correlation_id=correlation,
                schema_version=payload.schema_version,
                payload_json=payload.payload_json,
                payload_sha256=payload.payload_sha256,
                status=DeliveryMessageStatus.PENDING.value,
                delivery_count=0,
                max_deliveries=max_deliveries,
                available_at=available,
                created_at=available,
                updated_at=available,
            )
            .on_conflict_do_nothing(
                constraint="uq_dbi_delivery_messages_stream_attempt"
            )
            .returning(DBIDeliveryMessage.id)
        ).scalar_one_or_none()

        existing = self._session.execute(
            select(DBIDeliveryMessage)
            .where(
                DBIDeliveryMessage.stream == payload.stream.value,
                DBIDeliveryMessage.attempt_id == attempt,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if existing is None:
            raise DeliveryPersistenceConflict("mensaje publicado no recuperable.")

        exact = (
            existing.job_id == job
            and existing.correlation_id == correlation
            and existing.schema_version == payload.schema_version
            and existing.payload_json == payload.payload_json
            and existing.payload_sha256 == payload.payload_sha256
            and existing.max_deliveries == max_deliveries
        )
        if not exact:
            raise DeliveryPersistenceConflict(
                "stream+attempt ya representa otro mensaje."
            )
        if inserted is not None and inserted != existing.id:
            raise DeliveryPersistenceConflict("identidad insertada divergente.")
        return _envelope(existing), inserted is not None

    def get_for_update(self, message_id: UUID) -> DBIDeliveryMessage:
        message = _uuid(message_id, field_name="message_id")
        row = self._session.execute(
            select(DBIDeliveryMessage)
            .where(DBIDeliveryMessage.id == message)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise DeliveryMessageUnavailable("mensaje no disponible.")
        return row

    def claim_one(
        self,
        *,
        stream: DeliveryStream,
        claimed_at: datetime,
        lease_seconds: int,
    ) -> DeliveryLease | None:
        """Reclama un mensaje sin bloquear a otros consumidores."""

        if not isinstance(stream, DeliveryStream):
            raise DeliveryPersistenceConflict("stream debe ser DeliveryStream.")
        claimed = _utc(claimed_at, field_name="claimed_at")
        duration = _lease_seconds(lease_seconds)

        row = self._session.execute(
            select(DBIDeliveryMessage)
            .where(
                DBIDeliveryMessage.stream == stream.value,
                DBIDeliveryMessage.delivery_count < DBIDeliveryMessage.max_deliveries,
                or_(
                    and_(
                        DBIDeliveryMessage.status == DeliveryMessageStatus.PENDING.value,
                        DBIDeliveryMessage.available_at <= claimed,
                    ),
                    and_(
                        DBIDeliveryMessage.status == DeliveryMessageStatus.LEASED.value,
                        DBIDeliveryMessage.lease_expires_at <= claimed,
                    ),
                ),
            )
            .order_by(DBIDeliveryMessage.available_at, DBIDeliveryMessage.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None

        if _status(row.status) is DeliveryMessageStatus.LEASED:
            row.last_lease_ref = row.lease_ref
            row.last_error_code = "LEASE_EXPIRED"

        lease_ref = uuid4()
        expires = claimed + timedelta(seconds=duration)
        row.status = DeliveryMessageStatus.LEASED.value
        row.delivery_count += 1
        row.lease_ref = lease_ref
        row.lease_expires_at = expires
        row.updated_at = claimed
        self._session.flush()

        return DeliveryLease(
            lease_ref=lease_ref,
            claimed_at=claimed,
            lease_expires_at=expires,
            envelope=_envelope(row),
        )

    def renew_lease(
        self,
        *,
        message_id: UUID,
        lease_ref: UUID,
        renewed_at: datetime,
        lease_seconds: int,
    ) -> DeliveryLeaseRenewalEvidence:
        """Extiende el lease activo sin reentrega ni cambio de identidad."""

        lease = _uuid(lease_ref, field_name="lease_ref")
        renewed = _utc(renewed_at, field_name="renewed_at")
        duration = _lease_seconds(lease_seconds)
        row = self.get_for_update(message_id)

        if (
            _status(row.status) is not DeliveryMessageStatus.LEASED
            or row.lease_ref != lease
            or row.lease_expires_at is None
        ):
            raise DeliveryPersistenceConflict("lease de renovación no corresponde.")

        previous = _utc(row.lease_expires_at, field_name="lease_expires_at")
        if renewed >= previous:
            raise DeliveryPersistenceConflict("lease de renovación ya expiró.")

        candidate = renewed + timedelta(seconds=duration)
        changed = candidate > previous
        if changed:
            row.lease_expires_at = candidate
            row.updated_at = renewed
            self._session.flush()
            expires = candidate
        else:
            expires = previous

        return DeliveryLeaseRenewalEvidence(
            message_id=row.id,
            lease_ref=lease,
            renewed_at=renewed,
            previous_expires_at=previous,
            lease_expires_at=expires,
            changed=changed,
        )

    def ack(
        self,
        *,
        message_id: UUID,
        lease_ref: UUID,
        delivered_at: datetime,
    ) -> DeliveryTransitionEvidence:
        """Confirma exactamente el lease activo; un replay exacto es no-op."""

        lease = _uuid(lease_ref, field_name="lease_ref")
        delivered = _utc(delivered_at, field_name="delivered_at")
        row = self.get_for_update(message_id)
        status = _status(row.status)

        if status is DeliveryMessageStatus.DELIVERED:
            if row.last_lease_ref != lease:
                raise DeliveryPersistenceConflict("lease de ack no corresponde.")
            return DeliveryTransitionEvidence(
                message_id=row.id,
                status=status,
                changed=False,
                delivery_count=row.delivery_count,
            )

        if (
            status is not DeliveryMessageStatus.LEASED
            or row.lease_ref != lease
            or row.lease_expires_at is None
            or delivered > _utc(row.lease_expires_at, field_name="lease_expires_at")
        ):
            raise DeliveryPersistenceConflict("lease de ack no está vigente.")

        row.status = DeliveryMessageStatus.DELIVERED.value
        row.last_lease_ref = lease
        row.lease_ref = None
        row.lease_expires_at = None
        row.delivered_at = delivered
        row.last_error_code = None
        row.updated_at = delivered
        self._session.flush()
        return DeliveryTransitionEvidence(
            message_id=row.id,
            status=DeliveryMessageStatus.DELIVERED,
            changed=True,
            delivery_count=row.delivery_count,
        )

    def nack(
        self,
        *,
        message_id: UUID,
        lease_ref: UUID,
        changed_at: datetime,
        available_at: datetime,
        error_code: str,
    ) -> DeliveryTransitionEvidence:
        """Reprograma o envía a dead-letter sin perder evidencia."""

        lease = _uuid(lease_ref, field_name="lease_ref")
        changed = _utc(changed_at, field_name="changed_at")
        available = _utc(available_at, field_name="available_at")
        error = _error_code(error_code)
        if available < changed:
            raise DeliveryPersistenceConflict("available_at no puede ser anterior.")

        row = self.get_for_update(message_id)
        status = _status(row.status)
        if status in {
            DeliveryMessageStatus.PENDING,
            DeliveryMessageStatus.DEAD_LETTER,
        } and row.last_lease_ref == lease:
            return DeliveryTransitionEvidence(
                message_id=row.id,
                status=status,
                changed=False,
                delivery_count=row.delivery_count,
            )

        if (
            status is not DeliveryMessageStatus.LEASED
            or row.lease_ref != lease
            or row.lease_expires_at is None
            or changed > _utc(row.lease_expires_at, field_name="lease_expires_at")
        ):
            raise DeliveryPersistenceConflict("lease de nack no está vigente.")

        target = (
            DeliveryMessageStatus.DEAD_LETTER
            if row.delivery_count >= row.max_deliveries
            else DeliveryMessageStatus.PENDING
        )
        row.status = target.value
        row.last_lease_ref = lease
        row.lease_ref = None
        row.lease_expires_at = None
        row.last_error_code = error
        row.available_at = available
        row.updated_at = changed
        self._session.flush()
        return DeliveryTransitionEvidence(
            message_id=row.id,
            status=target,
            changed=True,
            delivery_count=row.delivery_count,
        )

    def reap_expired_exhausted(
        self,
        *,
        changed_at: datetime,
        limit: int = 100,
    ) -> int:
        """Cierra leases agotados de forma no bloqueante."""

        changed = _utc(changed_at, field_name="changed_at")
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise DeliveryPersistenceConflict("limit fuera de rango.")
        rows = self._session.execute(
            select(DBIDeliveryMessage)
            .where(
                DBIDeliveryMessage.status == DeliveryMessageStatus.LEASED.value,
                DBIDeliveryMessage.lease_expires_at <= changed,
                DBIDeliveryMessage.delivery_count >= DBIDeliveryMessage.max_deliveries,
            )
            .order_by(DBIDeliveryMessage.lease_expires_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).scalars().all()
        for row in rows:
            row.status = DeliveryMessageStatus.DEAD_LETTER.value
            row.last_lease_ref = row.lease_ref
            row.lease_ref = None
            row.lease_expires_at = None
            row.last_error_code = "LEASE_EXPIRED_MAX"
            row.updated_at = changed
        if rows:
            self._session.flush()
        return len(rows)
