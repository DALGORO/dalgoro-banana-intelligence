"""Servicio autorizado e idempotente de trabajos geoespaciales DBI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.jobs.persistence_contracts import (
    AnalysisJobResourceUnavailable,
    AnalysisJobSnapshot,
)
from app.dbi.jobs.service_contracts import (
    AnalysisJobCreateRequest,
    AnalysisJobRequestIntent,
    AnalysisProfilePolicy,
    AnalysisProfileResolutionContext,
    AnalysisProfileUnavailable,
    ApprovedAnalysisProfile,
    contract_sha256,
)
from app.dbi.jobs.state_machine import (
    AnalysisJobStatus,
    evaluate_analysis_job_transition,
)
from app.schemas.dbi_analysis_jobs import AnalysisJobCommand, AnalysisJobInputs


class AnalysisJobRepositoryPort(Protocol):
    """Persistencia usada por el servicio sin controlar la transacción."""

    def require_plot(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> None: ...

    def require_campaign(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
        campaign_id: UUID,
    ) -> None: ...

    def require_verified_asset(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        asset_id: UUID,
        asset_kind: str,
    ) -> None: ...

    def get_by_request_for_update(
        self,
        *,
        tenant_ref: str,
        request_id: str,
    ) -> AnalysisJobSnapshot | None: ...

    def get_for_update(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        job_id: UUID,
    ) -> AnalysisJobSnapshot | None: ...

    def require_same_intent(
        self,
        *,
        existing: AnalysisJobSnapshot,
        incoming: AnalysisJobRequestIntent,
    ) -> None: ...

    def persist_accepted(
        self,
        *,
        candidate: AnalysisJobSnapshot,
        intent: AnalysisJobRequestIntent,
    ) -> tuple[AnalysisJobSnapshot, bool]: ...

    def apply_status(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        job_id: UUID,
        expected_status: AnalysisJobStatus,
        target_status: AnalysisJobStatus,
        changed_at: datetime,
    ) -> AnalysisJobSnapshot: ...


@dataclass(frozen=True, slots=True)
class AnalysisJobCreationEvidence:
    """Evidencia segura de alta o reutilización exacta."""

    snapshot: AnalysisJobSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class AnalysisJobTransitionEvidence:
    """Evidencia segura de una transición o no-op idempotente."""

    snapshot: AnalysisJobSnapshot
    changed: bool


def _required_organization_ref(value: object) -> str:
    if not isinstance(value, str):
        raise DBIAccessDenied()
    normalized = value.strip()
    if (
        not normalized
        or normalized != value
        or "*" in normalized
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise DBIAccessDenied()
    return normalized


def _required_uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} debe ser UUID.")
    return value


class DBIAnalysisJobService:
    """Coordina autorización, recursos, perfil y estado sin commit/rollback."""

    def __init__(self, repository: AnalysisJobRepositoryPort) -> None:
        required_repository_methods = (
            "require_plot",
            "require_campaign",
            "require_verified_asset",
            "get_by_request_for_update",
            "get_for_update",
            "require_same_intent",
            "persist_accepted",
            "apply_status",
        )
        if any(
            not hasattr(repository, method)
            for method in required_repository_methods
        ):
            raise TypeError("repository no implementa el puerto de trabajos DBI.")
        self._repository = repository

    def create(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        request: AnalysisJobCreateRequest,
        profile_policy: AnalysisProfilePolicy,
        accepted_at: datetime,
    ) -> AnalysisJobCreationEvidence:
        """Crea un trabajo accepted o recupera una repetición exacta."""

        if not isinstance(context, DBIAccessContext):
            raise DBIAccessDenied()
        if not isinstance(request, AnalysisJobCreateRequest):
            raise TypeError("request debe ser AnalysisJobCreateRequest.")

        organization = _required_organization_ref(organization_ref)
        farm = _required_uuid(farm_id, field_name="farm_id")
        plot = _required_uuid(plot_id, field_name="plot_id")

        # Regla crítica: autorizar el ámbito antes de cualquier lectura DBI.
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization,
            farm_id=farm,
            plot_id=plot,
            permission=DBIPermission.SUBMIT_ANALYSIS,
        )

        intent = AnalysisJobRequestIntent(
            tenant_ref=context.tenant_ref,
            request_id=request.request_id,
            farm_id=farm,
            plot_id=plot,
            campaign_id=request.campaign_id,
            orthophoto_asset_id=request.orthophoto_asset_id,
            boundary_asset_id=request.boundary_asset_id,
            exclusions_asset_id=request.exclusions_asset_id,
            requested_by_ref=context.principal_ref,
        )

        # Un replay exacto devuelve la evidencia ya persistida y no vuelve a
        # interpretar un perfil ni depende del estado actual de sus activos.
        existing = self._repository.get_by_request_for_update(
            tenant_ref=context.tenant_ref,
            request_id=request.request_id,
        )
        if existing is not None:
            self._repository.require_same_intent(
                existing=existing,
                incoming=intent,
            )
            return AnalysisJobCreationEvidence(
                snapshot=existing,
                created=False,
            )

        if not isinstance(profile_policy, AnalysisProfilePolicy):
            raise AnalysisProfileUnavailable(
                "No existe una política de perfil aprobada."
            )

        # Sólo una intención nueva debe demostrar que sus recursos siguen
        # disponibles y que los activos están verified en el ámbito exacto.
        self._repository.require_plot(
            organization_ref=organization,
            farm_id=farm,
            plot_id=plot,
        )
        if request.campaign_id is not None:
            self._repository.require_campaign(
                organization_ref=organization,
                farm_id=farm,
                campaign_id=request.campaign_id,
            )

        self._repository.require_verified_asset(
            tenant_ref=context.tenant_ref,
            farm_id=farm,
            plot_id=plot,
            asset_id=request.orthophoto_asset_id,
            asset_kind="orthophoto",
        )
        self._repository.require_verified_asset(
            tenant_ref=context.tenant_ref,
            farm_id=farm,
            plot_id=plot,
            asset_id=request.boundary_asset_id,
            asset_kind="boundary",
        )
        if request.exclusions_asset_id is not None:
            self._repository.require_verified_asset(
                tenant_ref=context.tenant_ref,
                farm_id=farm,
                plot_id=plot,
                asset_id=request.exclusions_asset_id,
                asset_kind="exclusions",
            )

        profile = profile_policy.resolve(
            context=AnalysisProfileResolutionContext(
                tenant_ref=context.tenant_ref,
                organization_ref=organization,
                farm_id=farm,
                plot_id=plot,
                campaign_id=request.campaign_id,
            )
        )
        if not isinstance(profile, ApprovedAnalysisProfile):
            raise AnalysisProfileUnavailable(
                "La política no devolvió un perfil aprobado."
            )

        job_id = uuid4()
        correlation_id = str(uuid4())
        command = AnalysisJobCommand(
            request_id=request.request_id,
            correlation_id=correlation_id,
            job_id=str(job_id),
            tenant_id=context.tenant_ref,
            farm_id=str(farm),
            lot_id=str(plot),
            inputs=AnalysisJobInputs(
                orthophoto_asset_id=str(request.orthophoto_asset_id),
                boundary_asset_id=str(request.boundary_asset_id),
                exclusions_asset_id=(
                    None
                    if request.exclusions_asset_id is None
                    else str(request.exclusions_asset_id)
                ),
            ),
            model_version_id=profile.model_version_id,
            pipeline_config_version=profile.pipeline_config_version,
            requested_by=context.principal_ref,
        )

        candidate = AnalysisJobSnapshot(
            job_id=job_id,
            tenant_ref=context.tenant_ref,
            request_id=request.request_id,
            correlation_id=correlation_id,
            farm_id=farm,
            plot_id=plot,
            campaign_id=request.campaign_id,
            orthophoto_asset_id=request.orthophoto_asset_id,
            boundary_asset_id=request.boundary_asset_id,
            exclusions_asset_id=request.exclusions_asset_id,
            model_version_id=profile.model_version_id,
            pipeline_config_version=profile.pipeline_config_version,
            requested_by_ref=context.principal_ref,
            command_sha256=contract_sha256(command),
            status=AnalysisJobStatus.ACCEPTED,
            accepted_at=accepted_at,
            updated_at=accepted_at,
        )
        persisted, created = self._repository.persist_accepted(
            candidate=candidate,
            intent=intent,
        )
        return AnalysisJobCreationEvidence(
            snapshot=persisted,
            created=created,
        )

    def cancel(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        job_id: UUID,
        changed_at: datetime,
    ) -> AnalysisJobTransitionEvidence:
        """Solicita cancelación únicamente desde queued o running."""

        snapshot = self._load_mutable_job(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            job_id=job_id,
        )
        if snapshot.status is AnalysisJobStatus.CANCEL_REQUESTED:
            return AnalysisJobTransitionEvidence(snapshot=snapshot, changed=False)

        decision = evaluate_analysis_job_transition(
            snapshot.status,
            AnalysisJobStatus.CANCEL_REQUESTED,
        )
        persisted = self._repository.apply_status(
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            job_id=job_id,
            expected_status=snapshot.status,
            target_status=decision.target,
            changed_at=changed_at,
        )
        return AnalysisJobTransitionEvidence(
            snapshot=persisted,
            changed=decision.changed,
        )

    def retry(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        job_id: UUID,
        changed_at: datetime,
    ) -> AnalysisJobTransitionEvidence:
        """Reencola lógicamente un failed sin crear intento ni publicar mensaje."""

        snapshot = self._load_mutable_job(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            job_id=job_id,
        )
        if snapshot.status is AnalysisJobStatus.QUEUED:
            return AnalysisJobTransitionEvidence(snapshot=snapshot, changed=False)

        decision = evaluate_analysis_job_transition(
            snapshot.status,
            AnalysisJobStatus.QUEUED,
            retry_authorized=True,
        )
        persisted = self._repository.apply_status(
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            job_id=job_id,
            expected_status=snapshot.status,
            target_status=decision.target,
            changed_at=changed_at,
        )
        return AnalysisJobTransitionEvidence(
            snapshot=persisted,
            changed=decision.changed,
        )

    def _load_mutable_job(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        job_id: UUID,
    ) -> AnalysisJobSnapshot:
        if not isinstance(context, DBIAccessContext):
            raise DBIAccessDenied()

        organization = _required_organization_ref(organization_ref)
        farm = _required_uuid(farm_id, field_name="farm_id")
        job = _required_uuid(job_id, field_name="job_id")

        # Autoriza la finca antes de buscar el trabajo.
        DBIAuthorizationPolicy.require_farm(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization,
            farm_id=farm,
            permission=DBIPermission.SUBMIT_ANALYSIS,
        )
        snapshot = self._repository.get_for_update(
            tenant_ref=context.tenant_ref,
            farm_id=farm,
            job_id=job,
        )
        if snapshot is None:
            raise AnalysisJobResourceUnavailable("trabajo no disponible.")

        # El lote persistido debe permanecer dentro del ámbito del actor.
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization,
            farm_id=farm,
            plot_id=snapshot.plot_id,
            permission=DBIPermission.SUBMIT_ANALYSIS,
        )
        return snapshot
