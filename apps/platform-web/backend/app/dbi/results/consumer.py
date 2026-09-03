"""Consumidor durable: claim result → ingesta commit → ACK."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.dbi.delivery.contracts import DeliveryPersistenceConflict, DeliveryStream
from app.dbi.delivery.repository import DBIDeliveryRepository
from app.dbi.results.contracts import (
    DBIResultAckPending,
    DBIResultFailureCode,
    DBIResultIngestionConflict,
    DBIResultIngestionUnavailable,
    ResultIngestionEvidence,
)
from app.dbi.results.service import DBIAnalysisResultIngestionService
from app.dbi.storage_contracts import DBIPrivateObjectStore, DBIStorageError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBIAnalysisResultConsumer:
    """Procesa como máximo un resultado con transacciones cortas y recuperables."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        object_store: DBIPrivateObjectStore,
        *,
        clock: Callable[[], datetime] = _utc_now,
        lease_seconds: int = 120,
        retry_delay_seconds: int = 30,
    ) -> None:
        if not callable(session_factory) or not callable(clock):
            raise TypeError("session_factory y clock deben ser invocables.")
        if not isinstance(lease_seconds, int) or not 10 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds debe estar entre 10 y 3600.")
        if (
            not isinstance(retry_delay_seconds, int)
            or not 0 <= retry_delay_seconds <= 3600
        ):
            raise ValueError("retry_delay_seconds fuera de rango.")
        self._session_factory = session_factory
        self._store = object_store
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise DBIResultIngestionConflict("clock debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _claim(self):
        session = self._session_factory()
        try:
            lease = DBIDeliveryRepository(session).claim_one(
                stream=DeliveryStream.ANALYSIS_RESULT,
                claimed_at=self._now(),
                lease_seconds=self._lease_seconds,
            )
            session.commit()
            return lease
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _ingest(self, lease) -> ResultIngestionEvidence:
        session = self._session_factory()
        try:
            evidence = DBIAnalysisResultIngestionService(
                session,
                self._store,
            ).ingest(
                lease,
                ingested_at=self._now(),
            )
            session.commit()
            return evidence
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _ack(self, lease) -> None:
        session = self._session_factory()
        try:
            DBIDeliveryRepository(session).ack(
                message_id=lease.envelope.message_id,
                lease_ref=lease.lease_ref,
                delivered_at=self._now(),
            )
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _nack(self, lease, *, code: DBIResultFailureCode) -> None:
        now = self._now()
        session = self._session_factory()
        try:
            DBIDeliveryRepository(session).nack(
                message_id=lease.envelope.message_id,
                lease_ref=lease.lease_ref,
                changed_at=now,
                available_at=now + timedelta(seconds=self._retry_delay_seconds),
                error_code=code.value,
            )
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _failure_code(self, error: BaseException) -> DBIResultFailureCode:
        if isinstance(error, DBIResultIngestionConflict):
            return DBIResultFailureCode.CONFLICT
        if isinstance(error, (DBIResultIngestionUnavailable, DBIStorageError)):
            return DBIResultFailureCode.RESOURCE_UNAVAILABLE
        return DBIResultFailureCode.INTERNAL_FAILURE

    def process_one(self) -> ResultIngestionEvidence | None:
        lease = self._claim()
        if lease is None:
            return None
        try:
            evidence = self._ingest(lease)
        except BaseException as error:
            code = self._failure_code(error)
            try:
                self._nack(lease, code=code)
            except DeliveryPersistenceConflict:
                pass
            raise

        try:
            self._ack(lease)
        except BaseException as error:
            raise DBIResultAckPending(
                "resultado ingerido; ACK pendiente de recuperación."
            ) from error
        return evidence.model_copy(update={"acknowledged": True})
