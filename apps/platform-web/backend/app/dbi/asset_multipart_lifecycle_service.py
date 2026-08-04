"""Aborto y limpieza recuperable de sesiones multipartes DBI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

from app.dbi.asset_multipart_application import DBIMultipartSessionSnapshot
from app.dbi.asset_multipart_contracts import (
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
    DBIMultipartUploadPlan,
)
from app.dbi.asset_multipart_policy import DBIMultipartConflict
from app.dbi.asset_multipart_provider import (
    DBIMultipartObjectStore,
    DBIMultipartProviderAbortConfirmation,
    DBIMultipartProviderAbortRequest,
    DBIMultipartProviderConflict,
    DBIMultipartProviderError,
    DBIMultipartProviderPolicy,
)
from app.dbi.asset_multipart_upload_service import (
    DBIMultipartOperationUnavailable,
    DBIMultipartSessionContext,
)
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.storage_contracts import DBIStoragePurpose
from app.dbi.storage_policy import DBIStoragePolicy


DBI_MULTIPART_CLEANUP_BATCH_SIZE = 25
_MAX_CLEANUP_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class DBIMultipartTerminationRecord:
    """Transición durable posterior a la confirmación del proveedor."""

    snapshot: DBIMultipartSessionSnapshot
    changed: bool


@dataclass(frozen=True, slots=True)
class DBIMultipartAbortEvidence:
    """Resultado seguro de un aborto autorizado e idempotente."""

    session: DBIMultipartSessionSnapshot
    changed: bool
    provider_uploads_aborted: int


@dataclass(frozen=True, slots=True)
class DBIMultipartCleanupEvidence:
    """Resumen acotado de un lote de limpieza recuperable."""

    scanned: int
    expired: int
    failed: int
    expired_session_ids: tuple[UUID, ...]
    failed_session_ids: tuple[UUID, ...]


class DBIMultipartLifecycleRepositoryPort(Protocol):
    """Persistencia mínima para aborto y limpieza por lotes."""

    def get_session_for_update(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        session_id: UUID,
    ) -> DBIMultipartSessionContext | None: ...

    def claim_expired_for_cleanup(
        self,
        *,
        expired_at_or_before: datetime,
        batch_size: int,
    ) -> tuple[DBIMultipartSessionContext, ...]: ...

    def mark_terminated(
        self,
        *,
        context: DBIMultipartSessionContext,
        requested_state: DBIMultipartSessionState,
        changed_at: datetime,
    ) -> DBIMultipartTerminationRecord: ...


def _utc(value: object, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} debe ser UUID.")
    return value


def _batch_size(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= _MAX_CLEANUP_BATCH_SIZE
    ):
        raise TypeError("batch_size debe estar entre 1 y 100.")
    return value


def _authorize(
    context: DBIAccessContext,
    *,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID | None,
) -> None:
    if not isinstance(context, DBIAccessContext):
        raise DBIAccessDenied()
    if plot_id is None:
        DBIAuthorizationPolicy.require_farm(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            permission=DBIPermission.WRITE,
        )
        return
    DBIAuthorizationPolicy.require_plot(
        context,
        tenant_ref=context.tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )


def _plan(context: DBIMultipartSessionContext) -> DBIMultipartUploadPlan:
    snapshot = context.snapshot
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


def _abort_request(
    context: DBIMultipartSessionContext,
    *,
    requested_at: datetime,
) -> DBIMultipartProviderAbortRequest:
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref=context.asset.tenant_ref,
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=context.asset.asset_id,
        ),
        content_type=context.asset.content_type,
        size_bytes=context.asset.size_bytes,
        sha256_hex=context.asset.sha256,
    )
    return DBIMultipartProviderAbortRequest(
        session_id=context.snapshot.session_id,
        metadata=metadata,
        plan=_plan(context),
        initiated_at=context.snapshot.created_at,
        requested_at=requested_at,
        provider_upload_ref=context.provider_upload_ref,
    )


class DBIMultipartLifecycleService:
    """Coordina limpieza remota antes de cerrar una sesión durable."""

    def __init__(
        self,
        repository: DBIMultipartLifecycleRepositoryPort,
        provider: DBIMultipartObjectStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        for method in (
            "get_session_for_update",
            "claim_expired_for_cleanup",
            "mark_terminated",
        ):
            if not hasattr(repository, method):
                raise TypeError(f"repository no implementa {method}.")
        if not hasattr(provider, "abort"):
            raise TypeError("provider no implementa aborto multipartes.")
        self._repository = repository
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return _utc(self._clock(), field_name="clock")

    def _terminate(
        self,
        context: DBIMultipartSessionContext,
        *,
        requested_state: DBIMultipartSessionState,
        changed_at: datetime,
    ) -> tuple[DBIMultipartTerminationRecord, int]:
        if context.snapshot.state is requested_state:
            record = self._repository.mark_terminated(
                context=context,
                requested_state=requested_state,
                changed_at=changed_at,
            )
            return record, 0
        if context.snapshot.state not in {
            DBIMultipartSessionState.INITIATED,
            DBIMultipartSessionState.UPLOADING,
        }:
            raise DBIMultipartConflict("la sesión no admite limpieza.")
        if requested_state is DBIMultipartSessionState.EXPIRED:
            expires_at = context.snapshot.expires_at
            if expires_at is None or changed_at < expires_at:
                raise DBIMultipartConflict("la sesión aún no está vencida.")

        confirmation = self._provider.abort(
            _abort_request(context, requested_at=changed_at)
        )
        canonical = DBIMultipartProviderPolicy.validate_abort_confirmation(
            confirmation
        )
        if (
            canonical.session_id != context.snapshot.session_id
            or canonical.aborted_at != changed_at
        ):
            raise DBIMultipartConflict(
                "la confirmación de limpieza es divergente."
            )
        if not canonical.cleanup_confirmed:
            raise DBIMultipartProviderConflict(
                "el proveedor aún observa partes multipartes."
            )
        record = self._repository.mark_terminated(
            context=context,
            requested_state=requested_state,
            changed_at=canonical.aborted_at,
        )
        if record.snapshot.state is not requested_state:
            raise DBIMultipartConflict("la terminación durable es divergente.")
        return record, canonical.provider_uploads_aborted

    def abort(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        session_id: UUID,
    ) -> DBIMultipartAbortEvidence:
        """Aborta una sesión autorizada sin tocar un objeto completado."""

        farm = _uuid(farm_id, field_name="farm_id")
        asset = _uuid(asset_id, field_name="asset_id")
        session = _uuid(session_id, field_name="session_id")
        if plot_id is not None:
            _uuid(plot_id, field_name="plot_id")
        _authorize(
            context,
            organization_ref=organization_ref,
            farm_id=farm,
            plot_id=plot_id,
        )
        durable = self._repository.get_session_for_update(
            tenant_ref=context.tenant_ref,
            farm_id=farm,
            plot_id=plot_id,
            asset_id=asset,
            session_id=session,
        )
        if (
            not isinstance(durable, DBIMultipartSessionContext)
            or durable.snapshot.session_id != session
            or durable.snapshot.asset_id != asset
            or durable.snapshot.tenant_ref != context.tenant_ref
            or durable.asset.farm_id != farm
            or durable.asset.plot_id != plot_id
        ):
            raise DBIMultipartOperationUnavailable()
        record, remote_count = self._terminate(
            durable,
            requested_state=DBIMultipartSessionState.ABORTED,
            changed_at=self._now(),
        )
        return DBIMultipartAbortEvidence(
            session=record.snapshot,
            changed=record.changed,
            provider_uploads_aborted=remote_count,
        )

    def cleanup_expired(
        self,
        *,
        batch_size: int = DBI_MULTIPART_CLEANUP_BATCH_SIZE,
    ) -> DBIMultipartCleanupEvidence:
        """Reclama un lote vencido y deja fallos remotos para reintento."""

        limit = _batch_size(batch_size)
        now = self._now()
        claimed = self._repository.claim_expired_for_cleanup(
            expired_at_or_before=now,
            batch_size=limit,
        )
        expired_ids: list[UUID] = []
        failed_ids: list[UUID] = []
        for durable in claimed:
            try:
                record, _remote_count = self._terminate(
                    durable,
                    requested_state=DBIMultipartSessionState.EXPIRED,
                    changed_at=now,
                )
            except DBIMultipartProviderError:
                failed_ids.append(durable.snapshot.session_id)
                continue
            expired_ids.append(record.snapshot.session_id)
        return DBIMultipartCleanupEvidence(
            scanned=len(claimed),
            expired=len(expired_ids),
            failed=len(failed_ids),
            expired_session_ids=tuple(expired_ids),
            failed_session_ids=tuple(failed_ids),
        )
