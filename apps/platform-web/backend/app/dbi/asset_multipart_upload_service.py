"""Orquestación autorizada de cargas multipartes DBI sin transportar binarios."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from uuid import UUID

from app.dbi.asset_multipart_application import (
    DBIMultipartApplicationRepositoryPort,
    DBIMultipartApplicationService,
    DBIMultipartAssetSnapshot,
    DBIMultipartPreparationEvidence,
    DBIMultipartSessionSnapshot,
)
from app.dbi.asset_multipart_contracts import (
    DBIMultipartPartEvidence,
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
    DBIMultipartUploadPlan,
)
from app.dbi.asset_multipart_policy import (
    DBIMultipartConflict,
    DBIMultipartPolicy,
)
from app.dbi.asset_multipart_provider import (
    DBIMultipartObjectStore,
    DBIMultipartProviderCompleteRequest,
    DBIMultipartProviderCompletion,
    DBIMultipartProviderInitiateRequest,
    DBIMultipartProviderPartGrant,
    DBIMultipartProviderPartGrantRequest,
    DBIMultipartProviderUpload,
)
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.storage_contracts import DBIStoragePurpose
from app.dbi.storage_policy import DBIStoragePolicy


DBI_MULTIPART_PART_GRANT_TTL = timedelta(minutes=15)


class DBIMultipartOperationUnavailable(DBIMultipartConflict):
    """La sesión no existe o no está disponible dentro del ámbito autorizado."""


@dataclass(frozen=True, slots=True)
class DBIMultipartSessionContext:
    """Contexto durable privado; la referencia remota nunca sale del servicio."""

    snapshot: DBIMultipartSessionSnapshot
    asset: DBIMultipartAssetSnapshot
    provider_upload_ref: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class DBIMultipartPartAuthorization:
    """Parte exacta para la cual se solicita autoridad temporal."""

    part_number: int
    checksum: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DBIMultipartPartRecord:
    """Resultado durable de registrar una parte de manera idempotente."""

    snapshot: DBIMultipartSessionSnapshot
    evidence: DBIMultipartPartEvidence = field(repr=False)
    created: bool
    recorded_part_count: int


@dataclass(frozen=True, slots=True)
class DBIMultipartCompletionRecord:
    """Resultado durable de marcar el transporte como completado."""

    snapshot: DBIMultipartSessionSnapshot
    changed: bool


@dataclass(frozen=True, slots=True)
class DBIMultipartInitiationEvidence:
    """Resultado seguro de preparar e iniciar la carga cuando corresponde."""

    preparation: DBIMultipartPreparationEvidence
    session: DBIMultipartSessionSnapshot | None
    provider_started: bool


@dataclass(frozen=True, slots=True)
class DBIMultipartGrantEvidence:
    """Grants efímeros emitidos para una sesión autorizada."""

    session: DBIMultipartSessionSnapshot
    grants: tuple[DBIMultipartProviderPartGrant, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class DBIMultipartCompletionEvidence:
    """Integridad de transporte confirmada sin verificar el SHA canónico."""

    session: DBIMultipartSessionSnapshot
    completion: DBIMultipartProviderCompletion = field(repr=False)
    changed: bool


@dataclass(frozen=True, slots=True)
class DBIMultipartInspectionEvidence:
    """Progreso durable sin URLs o referencias internas del proveedor."""

    session: DBIMultipartSessionSnapshot
    recorded_part_count: int


class DBIMultipartUploadRepositoryPort(
    DBIMultipartApplicationRepositoryPort,
    Protocol,
):
    """Persistencia requerida por las operaciones API multipartes."""

    def get_session_for_update(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        session_id: UUID,
    ) -> DBIMultipartSessionContext | None: ...

    def bind_provider_upload(
        self,
        *,
        context: DBIMultipartSessionContext,
        provider_upload_ref: str,
        changed_at: datetime,
    ) -> DBIMultipartSessionContext: ...

    def record_part(
        self,
        *,
        context: DBIMultipartSessionContext,
        evidence: DBIMultipartPartEvidence,
        observed_at: datetime,
    ) -> DBIMultipartPartRecord: ...

    def list_parts(
        self,
        *,
        context: DBIMultipartSessionContext,
    ) -> tuple[DBIMultipartPartEvidence, ...]: ...

    def mark_completed(
        self,
        *,
        context: DBIMultipartSessionContext,
        completed_at: datetime,
    ) -> DBIMultipartCompletionRecord: ...


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


def _plan(snapshot: DBIMultipartSessionSnapshot) -> DBIMultipartUploadPlan:
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


def _metadata(context: DBIMultipartSessionContext):
    return DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref=context.asset.tenant_ref,
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=context.asset.asset_id,
        ),
        content_type=context.asset.content_type,
        size_bytes=context.asset.size_bytes,
        sha256_hex=context.asset.sha256,
    )


def _provider_upload(
    context: DBIMultipartSessionContext,
) -> DBIMultipartProviderUpload:
    if context.provider_upload_ref is None:
        raise DBIMultipartConflict("la sesión aún no tiene una carga remota.")
    return DBIMultipartProviderUpload(
        provider_upload_ref=context.provider_upload_ref,
        session_id=context.snapshot.session_id,
        metadata=_metadata(context),
        plan=_plan(context.snapshot),
        initiated_at=context.snapshot.created_at,
    )


class DBIMultipartUploadService:
    """Coordina persistencia y proveedor sin recibir el contenido del activo."""

    def __init__(
        self,
        repository: DBIMultipartUploadRepositoryPort,
        provider: DBIMultipartObjectStore,
        *,
        clock: Callable[[], datetime] | None = None,
        grant_ttl: timedelta = DBI_MULTIPART_PART_GRANT_TTL,
    ) -> None:
        required_repository = (
            "get_asset_for_update",
            "persist_initiation",
            "get_session_for_update",
            "bind_provider_upload",
            "record_part",
            "list_parts",
            "mark_completed",
        )
        if any(not hasattr(repository, name) for name in required_repository):
            raise TypeError("repository no implementa el puerto multipartes.")
        required_provider = (
            "initiate",
            "issue_part_access",
            "complete",
            "inspect_completed",
        )
        if any(not hasattr(provider, name) for name in required_provider):
            raise TypeError("provider no implementa el puerto multipartes.")
        if (
            not isinstance(grant_ttl, timedelta)
            or not timedelta(0) < grant_ttl <= timedelta(hours=1)
        ):
            raise TypeError("grant_ttl debe estar entre 0 y 1 hora.")
        self._repository = repository
        self._provider = provider
        self._application = DBIMultipartApplicationService(
            repository,
            clock=clock,
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._grant_ttl = grant_ttl

    def _now(self) -> datetime:
        return _utc(self._clock(), field_name="clock")

    def _session(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        session_id: UUID,
    ) -> DBIMultipartSessionContext:
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
        result = self._repository.get_session_for_update(
            tenant_ref=context.tenant_ref,
            farm_id=farm,
            plot_id=plot_id,
            asset_id=asset,
            session_id=session,
        )
        if (
            not isinstance(result, DBIMultipartSessionContext)
            or result.snapshot.session_id != session
            or result.snapshot.asset_id != asset
            or result.snapshot.tenant_ref != context.tenant_ref
            or result.asset.asset_id != asset
            or result.asset.tenant_ref != context.tenant_ref
            or result.asset.farm_id != farm
            or result.asset.plot_id != plot_id
        ):
            raise DBIMultipartOperationUnavailable(
                "sesión multipartes no disponible."
            )
        return result

    def _require_uploading(
        self,
        context: DBIMultipartSessionContext,
        *,
        now: datetime,
    ) -> None:
        if context.snapshot.state is not DBIMultipartSessionState.UPLOADING:
            raise DBIMultipartConflict("la sesión no admite partes en este estado.")
        expires_at = context.snapshot.expires_at
        if expires_at is None or now >= expires_at:
            raise DBIMultipartConflict("la sesión multipartes está vencida.")
        _provider_upload(context)

    def initiate(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        idempotency_key: str,
        checksum_algorithm,
        checksum_type,
    ) -> DBIMultipartInitiationEvidence:
        """Prepara la sesión e inicia el proveedor solo para ruta multipartes."""

        preparation = self._application.prepare(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            asset_id=asset_id,
            idempotency_key=idempotency_key,
            checksum_algorithm=checksum_algorithm,
            checksum_type=checksum_type,
        )
        if (
            preparation.plan.decision is not DBIMultipartRoutingDecision.MULTIPART
            or preparation.session is None
        ):
            return DBIMultipartInitiationEvidence(
                preparation=preparation,
                session=preparation.session,
                provider_started=False,
            )
        durable = self._session(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            asset_id=asset_id,
            session_id=preparation.session.session_id,
        )
        if durable.snapshot.state is DBIMultipartSessionState.INITIATED:
            if durable.provider_upload_ref is not None:
                raise DBIMultipartConflict(
                    "la sesión iniciada tiene contexto remoto divergente."
                )
            initiated_at = self._now()
            upload = self._provider.initiate(
                DBIMultipartProviderInitiateRequest(
                    session_id=durable.snapshot.session_id,
                    metadata=_metadata(durable),
                    plan=_plan(durable.snapshot),
                    initiated_at=initiated_at,
                )
            )
            if (
                not isinstance(upload, DBIMultipartProviderUpload)
                or upload.session_id != durable.snapshot.session_id
                or upload.metadata != _metadata(durable)
                or upload.plan != _plan(durable.snapshot)
            ):
                raise DBIMultipartConflict(
                    "el inicio devuelto por el proveedor es divergente."
                )
            durable = self._repository.bind_provider_upload(
                context=durable,
                provider_upload_ref=upload.provider_upload_ref,
                changed_at=initiated_at,
            )
            return DBIMultipartInitiationEvidence(
                preparation=preparation,
                session=durable.snapshot,
                provider_started=True,
            )
        if durable.snapshot.state not in {
            DBIMultipartSessionState.UPLOADING,
            DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION,
            DBIMultipartSessionState.ABORTED,
            DBIMultipartSessionState.EXPIRED,
        }:
            raise DBIMultipartConflict("estado multipartes no reutilizable.")
        return DBIMultipartInitiationEvidence(
            preparation=preparation,
            session=durable.snapshot,
            provider_started=False,
        )

    def grant_parts(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        session_id: UUID,
        parts: tuple[DBIMultipartPartAuthorization, ...],
    ) -> DBIMultipartGrantEvidence:
        """Emite una ventana exacta de grants sin persistir URLs."""

        durable = self._session(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            asset_id=asset_id,
            session_id=session_id,
        )
        now = self._now()
        self._require_uploading(durable, now=now)
        plan = _plan(durable.snapshot)
        if (
            not isinstance(parts, tuple)
            or not 1 <= len(parts) <= plan.max_grants_per_window
            or any(not isinstance(part, DBIMultipartPartAuthorization) for part in parts)
        ):
            raise DBIMultipartConflict("la ventana de partes no es canónica.")
        numbers = [part.part_number for part in parts]
        if len(numbers) != len(set(numbers)):
            raise DBIMultipartConflict("la ventana contiene partes duplicadas.")
        expires_at = min(now + self._grant_ttl, durable.snapshot.expires_at)
        upload = _provider_upload(durable)
        grants = tuple(
            self._provider.issue_part_access(
                DBIMultipartProviderPartGrantRequest(
                    upload=upload,
                    part_number=part.part_number,
                    size_bytes=DBIMultipartPolicy.expected_part_size(
                        plan,
                        part_number=part.part_number,
                    ),
                    checksum=part.checksum,
                    issued_at=now,
                    expires_at=expires_at,
                )
            )
            for part in parts
        )
        for requested, grant in zip(parts, grants, strict=True):
            expected_size = DBIMultipartPolicy.expected_part_size(
                plan,
                part_number=requested.part_number,
            )
            if (
                not isinstance(grant, DBIMultipartProviderPartGrant)
                or grant.session_id != durable.snapshot.session_id
                or grant.part_number != requested.part_number
                or grant.size_bytes != expected_size
                or grant.checksum_algorithm is not plan.checksum_algorithm
                or grant.issued_at != now
                or grant.expires_at != expires_at
            ):
                raise DBIMultipartConflict(
                    "el grant devuelto por el proveedor es divergente."
                )
        return DBIMultipartGrantEvidence(
            session=durable.snapshot,
            grants=grants,
        )

    def record_part(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        session_id: UUID,
        evidence: DBIMultipartPartEvidence,
    ) -> DBIMultipartPartRecord:
        """Registra una evidencia exacta o reconoce su reintento."""

        durable = self._session(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            asset_id=asset_id,
            session_id=session_id,
        )
        now = self._now()
        self._require_uploading(durable, now=now)
        if evidence.session_id != durable.snapshot.session_id:
            raise DBIMultipartConflict("la parte pertenece a otra sesión.")
        DBIMultipartPolicy.validate_part_evidence(
            evidence,
            plan=_plan(durable.snapshot),
        )
        result = self._repository.record_part(
            context=durable,
            evidence=evidence,
            observed_at=now,
        )
        if (
            not isinstance(result, DBIMultipartPartRecord)
            or result.snapshot.session_id != durable.snapshot.session_id
            or result.evidence != evidence
            or not isinstance(result.created, bool)
            or result.recorded_part_count < 1
        ):
            raise DBIMultipartConflict("evidencia durable de parte divergente.")
        return result

    def complete(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        session_id: UUID,
        full_object_checksum: str | None,
    ) -> DBIMultipartCompletionEvidence:
        """Completa una vez y conserva pendiente la verificación canónica."""

        durable = self._session(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            asset_id=asset_id,
            session_id=session_id,
        )
        if durable.snapshot.state not in {
            DBIMultipartSessionState.UPLOADING,
            DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION,
        }:
            raise DBIMultipartConflict("la sesión no admite finalización.")
        if durable.snapshot.state is DBIMultipartSessionState.UPLOADING:
            self._require_uploading(durable, now=self._now())
        parts = self._repository.list_parts(context=durable)
        upload = _provider_upload(durable)
        request = DBIMultipartProviderCompleteRequest(
            upload=upload,
            parts=parts,
            full_object_checksum=full_object_checksum,
        )
        completion = (
            self._provider.complete(request)
            if durable.snapshot.state is DBIMultipartSessionState.UPLOADING
            else self._provider.inspect_completed(upload)
        )
        if (
            not isinstance(completion, DBIMultipartProviderCompletion)
            or completion.session_id != durable.snapshot.session_id
            or completion.metadata != upload.metadata
            or completion.checksum_algorithm
            is not durable.snapshot.checksum_algorithm
            or completion.checksum_type is not durable.snapshot.checksum_type
        ):
            raise DBIMultipartConflict(
                "la finalización devuelta por el proveedor es divergente."
            )
        completed = self._repository.mark_completed(
            context=durable,
            completed_at=completion.completed_at,
        )
        if (
            not isinstance(completed, DBIMultipartCompletionRecord)
            or completed.snapshot.state
            is not DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION
        ):
            raise DBIMultipartConflict("finalización durable divergente.")
        return DBIMultipartCompletionEvidence(
            session=completed.snapshot,
            completion=completion,
            changed=completed.changed,
        )

    def inspect(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_id: UUID,
        session_id: UUID,
    ) -> DBIMultipartInspectionEvidence:
        """Devuelve estado y progreso durable sin consultar el binario."""

        durable = self._session(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            asset_id=asset_id,
            session_id=session_id,
        )
        parts = self._repository.list_parts(context=durable)
        return DBIMultipartInspectionEvidence(
            session=durable.snapshot,
            recorded_part_count=len(parts),
        )
