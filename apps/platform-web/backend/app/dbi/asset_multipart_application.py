"""Servicio de aplicación para preparar sesiones multipartes DBI sin red."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from uuid import UUID, uuid4

from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm,
    DBIMultipartChecksumType,
    DBIMultipartIdempotencyIdentity,
    DBIMultipartLimits,
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
    DBIMultipartUploadPlan,
)
from app.dbi.asset_multipart_policy import (
    DBI_MULTIPART_DEFAULT_LIMITS,
    DBIMultipartConflict,
    DBIMultipartPolicy,
)
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)


DBI_MULTIPART_SESSION_TTL = timedelta(hours=24)
_MAX_SESSION_TTL = timedelta(days=7)


class DBIMultipartUnavailable(DBIMultipartConflict):
    """El activo o una sesión compatible no están disponibles en el ámbito."""


@dataclass(frozen=True, slots=True)
class DBIMultipartAssetSnapshot:
    """Metadata durable mínima para decidir la ruta sin abrir el objeto."""

    asset_id: UUID
    tenant_ref: str
    farm_id: UUID
    plot_id: UUID | None
    status: str
    content_type: str
    size_bytes: int
    sha256: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DBIMultipartInitiationRecord:
    """Intención persistible que no contiene URL ni referencia del proveedor."""

    session_id: UUID
    asset: DBIMultipartAssetSnapshot
    plan: DBIMultipartUploadPlan
    identity: DBIMultipartIdempotencyIdentity = field(repr=False)
    created_by_ref: str
    requested_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class DBIMultipartSessionSnapshot:
    """Vista segura de sesión; excluye upload ID, URL y clave idempotente."""

    session_id: UUID
    asset_id: UUID
    tenant_ref: str
    state: DBIMultipartSessionState
    reason_code: str | None
    size_bytes: int
    part_size_bytes: int | None
    part_count: int | None
    max_grants_per_window: int | None
    max_client_concurrency: int | None
    checksum_algorithm: DBIMultipartChecksumAlgorithm
    checksum_type: DBIMultipartChecksumType
    request_fingerprint: str
    created_by_ref: str
    version: int
    expires_at: datetime | None
    last_activity_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DBIMultipartPersistedInitiation:
    """Resultado de crear o reutilizar una sesión bajo la misma transacción."""

    snapshot: DBIMultipartSessionSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class DBIMultipartPreparationEvidence:
    """Decisión autorizada para flujo síncrono, multipartes o bloqueo visible."""

    plan: DBIMultipartUploadPlan
    session: DBIMultipartSessionSnapshot | None
    created: bool


class DBIMultipartApplicationRepositoryPort(Protocol):
    """Puerto transaccional de persistencia, sin proveedor de objetos."""

    def get_asset_for_update(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
    ) -> DBIMultipartAssetSnapshot | None: ...

    def persist_initiation(
        self,
        *,
        record: DBIMultipartInitiationRecord,
    ) -> DBIMultipartPersistedInitiation: ...


def _required_uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} debe ser UUID.")
    return value


def _required_organization_ref(value: object) -> str:
    if not isinstance(value, str):
        raise DBIAccessDenied()
    normalized = value.strip()
    if not normalized or normalized != value or "*" in normalized:
        raise DBIAccessDenied()
    return normalized


def _utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _validated_ttl(value: object) -> timedelta:
    if not isinstance(value, timedelta) or not timedelta(0) < value <= _MAX_SESSION_TTL:
        raise TypeError("session_ttl debe estar entre 0 y 7 días.")
    return value


class DBIMultipartApplicationService:
    """Autoriza y prepara una sesión durable sin llamar al almacenamiento."""

    def __init__(
        self,
        repository: DBIMultipartApplicationRepositoryPort,
        *,
        limits: DBIMultipartLimits = DBI_MULTIPART_DEFAULT_LIMITS,
        session_ttl: timedelta = DBI_MULTIPART_SESSION_TTL,
        clock: Callable[[], datetime] | None = None,
        session_id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        for method in ("get_asset_for_update", "persist_initiation"):
            if not hasattr(repository, method):
                raise TypeError(f"repository no implementa {method}.")
        self._repository = repository
        self._limits = DBIMultipartPolicy.validate_limits(limits)
        self._session_ttl = _validated_ttl(session_ttl)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._session_id_factory = session_id_factory or uuid4

    def prepare(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        idempotency_key: str,
        checksum_algorithm: DBIMultipartChecksumAlgorithm = (
            DBIMultipartChecksumAlgorithm.SHA256
        ),
        checksum_type: DBIMultipartChecksumType = (
            DBIMultipartChecksumType.COMPOSITE
        ),
    ) -> DBIMultipartPreparationEvidence:
        """Decide y persiste el inicio; el binario y el proveedor quedan fuera."""

        if not isinstance(context, DBIAccessContext):
            raise DBIAccessDenied()
        organization = _required_organization_ref(organization_ref)
        farm = _required_uuid(farm_id, field_name="farm_id")
        asset_uuid = _required_uuid(asset_id, field_name="asset_id")
        if plot_id is None:
            DBIAuthorizationPolicy.require_farm(
                context,
                tenant_ref=context.tenant_ref,
                organization_ref=organization,
                farm_id=farm,
                permission=DBIPermission.WRITE,
            )
        else:
            plot = _required_uuid(plot_id, field_name="plot_id")
            DBIAuthorizationPolicy.require_plot(
                context,
                tenant_ref=context.tenant_ref,
                organization_ref=organization,
                farm_id=farm,
                plot_id=plot,
                permission=DBIPermission.WRITE,
            )

        asset = self._repository.get_asset_for_update(
            tenant_ref=context.tenant_ref,
            farm_id=farm,
            plot_id=plot_id,
            asset_id=asset_uuid,
        )
        if (
            not isinstance(asset, DBIMultipartAssetSnapshot)
            or asset.tenant_ref != context.tenant_ref
            or asset.farm_id != farm
            or asset.plot_id != plot_id
            or asset.asset_id != asset_uuid
            or asset.status != "registered"
        ):
            raise DBIMultipartUnavailable("activo multipartes no disponible.")

        plan = DBIMultipartPolicy.build_upload_plan(
            size_bytes=asset.size_bytes,
            limits=self._limits,
            checksum_algorithm=checksum_algorithm,
            checksum_type=checksum_type,
        )
        if plan.decision is DBIMultipartRoutingDecision.SYNCHRONOUS:
            return DBIMultipartPreparationEvidence(
                plan=plan,
                session=None,
                created=False,
            )

        identity = DBIMultipartPolicy.build_idempotency_identity(
            idempotency_key=idempotency_key,
            asset_id=asset.asset_id,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            sha256_hex=asset.sha256,
        )
        requested_at = _utc(self._clock(), field_name="clock")
        session_id = _required_uuid(
            self._session_id_factory(),
            field_name="session_id_factory",
        )
        expires_at = (
            requested_at + self._session_ttl
            if plan.decision is DBIMultipartRoutingDecision.MULTIPART
            else None
        )
        persisted = self._repository.persist_initiation(
            record=DBIMultipartInitiationRecord(
                session_id=session_id,
                asset=asset,
                plan=plan,
                identity=identity,
                created_by_ref=context.principal_ref,
                requested_at=requested_at,
                expires_at=expires_at,
            )
        )
        if not isinstance(persisted, DBIMultipartPersistedInitiation):
            raise TypeError(
                "persist_initiation debe devolver DBIMultipartPersistedInitiation."
            )
        if not isinstance(persisted.created, bool):
            raise TypeError("persist_initiation debe indicar created como bool.")
        snapshot = persisted.snapshot
        blocked = plan.decision is DBIMultipartRoutingDecision.BLOCKED_BY_POLICY
        expected_reason = plan.reason_code.value if plan.reason_code else None
        expected_states = (
            {DBIMultipartSessionState.BLOCKED_BY_POLICY}
            if blocked
            else {
                DBIMultipartSessionState.INITIATED,
                DBIMultipartSessionState.UPLOADING,
                DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION,
                DBIMultipartSessionState.ABORTED,
                DBIMultipartSessionState.EXPIRED,
            }
        )
        if (
            not isinstance(snapshot, DBIMultipartSessionSnapshot)
            or snapshot.asset_id != asset.asset_id
            or snapshot.tenant_ref != asset.tenant_ref
            or snapshot.request_fingerprint != identity.request_fingerprint
            or snapshot.state not in expected_states
            or snapshot.reason_code != expected_reason
            or snapshot.size_bytes != plan.size_bytes
            or snapshot.part_size_bytes != plan.part_size_bytes
            or snapshot.part_count != (plan.part_count if not blocked else None)
            or snapshot.max_grants_per_window
            != (plan.max_grants_per_window if not blocked else None)
            or snapshot.max_client_concurrency
            != (plan.max_client_concurrency if not blocked else None)
            or snapshot.checksum_algorithm is not plan.checksum_algorithm
            or snapshot.checksum_type is not plan.checksum_type
            or snapshot.created_by_ref != context.principal_ref
        ):
            raise DBIMultipartConflict("resultado durable multipartes divergente.")
        return DBIMultipartPreparationEvidence(
            plan=plan,
            session=snapshot,
            created=persisted.created,
        )
