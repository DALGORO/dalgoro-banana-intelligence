"""Heartbeat transaccional para conservar la propiedad de un comando DBI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.dbi.delivery.contracts import DeliveryPersistenceConflict
from app.dbi.delivery.repository import DBIDeliveryRepository
from app.dbi.worker.contracts import DBIWorkerLeaseLost


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBIWorkerLeaseHeartbeat:
    """Renueva únicamente el lease exacto usando transacciones cortas."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        message_id: UUID,
        lease_ref: UUID,
        lease_seconds: int = 300,
        interval_seconds: int = 60,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not callable(session_factory) or not callable(clock):
            raise TypeError("session_factory y clock deben ser invocables.")
        if not isinstance(lease_seconds, int) or not 30 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds debe estar entre 30 y 3600.")
        if (
            not isinstance(interval_seconds, int)
            or interval_seconds <= 0
            or interval_seconds >= lease_seconds
        ):
            raise ValueError("interval_seconds debe ser positivo y menor al lease.")
        self._session_factory = session_factory
        self._message_id = message_id
        self._lease_ref = lease_ref
        self._lease_seconds = lease_seconds
        self._interval = timedelta(seconds=interval_seconds)
        self._clock = clock
        self._last_beat: datetime | None = None
        self._last_expires_at: datetime | None = None

    @property
    def last_expires_at(self) -> datetime | None:
        return self._last_expires_at

    def beat(self, *, force: bool = False) -> bool:
        now = self._clock().astimezone(timezone.utc)
        if (
            not force
            and self._last_beat is not None
            and now - self._last_beat < self._interval
        ):
            return False

        session = self._session_factory()
        try:
            evidence = DBIDeliveryRepository(session).renew_lease(
                message_id=self._message_id,
                lease_ref=self._lease_ref,
                renewed_at=now,
                lease_seconds=self._lease_seconds,
            )
            session.commit()
        except DeliveryPersistenceConflict as error:
            session.rollback()
            raise DBIWorkerLeaseLost("se perdió el lease activo del comando.") from error
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

        self._last_beat = now
        self._last_expires_at = evidence.lease_expires_at
        return evidence.changed

    def progress(self, _bytes_processed: int) -> None:
        """Callback para materialización streaming sin etiquetas sensibles."""

        self.beat(force=False)
