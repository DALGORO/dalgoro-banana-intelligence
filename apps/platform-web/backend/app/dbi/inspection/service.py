"""Servicio de aplicación autorizado para observaciones de campo DBI."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.inspection.api_schemas import (
    DBIFieldObservationBody,
    DBIFieldObservationCorrectionRequest,
    DBIFieldObservationCreateRequest,
)
from app.dbi.inspection.contracts import (
    DBIFieldObservationCorrection,
    DBIFieldObservationCreate,
    DBIFieldObservationPayload,
    DBIFieldObservationVersion,
)
from app.dbi.inspection.repository import (
    DBIFieldObservationRepository,
    DBIInspectionConflict,
)


class DBIInspectionUnavailable(LookupError):
    """La observación no existe dentro del alcance autorizado."""


class DBIFieldObservationService:
    """Aplica autoridad DBI antes de leer o persistir verdad-terreno."""

    def __init__(self, session: Session) -> None:
        self._repository = DBIFieldObservationRepository(session)

    @staticmethod
    def _require_plot(
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        permission: DBIPermission,
    ) -> None:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=permission,
        )

    @staticmethod
    def _payload(
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        observation: DBIFieldObservationBody,
    ) -> DBIFieldObservationPayload:
        return DBIFieldObservationPayload(
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            operator_ref=context.principal_ref,
            observed_at=observation.observed_at,
            gps_fix=observation.gps_fix,
            sampling_point_id=observation.sampling_point_id,
            up_id=observation.up_id,
            core=observation.core,
            structural=observation.structural,
            diagnostic=observation.diagnostic,
            evidence_kind="observed",
        )

    def create(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        request: DBIFieldObservationCreateRequest,
    ) -> DBIFieldObservationVersion:
        self._require_plot(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.WRITE,
        )
        payload = self._payload(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            observation=request.observation,
        )
        return self._repository.create_observation(
            DBIFieldObservationCreate(payload=payload),
            recorded_by_ref=context.principal_ref,
        )

    def correct(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        observation_id: UUID,
        request: DBIFieldObservationCorrectionRequest,
    ) -> DBIFieldObservationVersion:
        self._require_plot(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.WRITE,
        )
        latest = self._repository.get_latest(
            observation_id=observation_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if latest is None:
            raise DBIInspectionUnavailable()
        if latest.version_id != request.base_version_id:
            raise DBIInspectionConflict(
                "base_version_id no es la versión vigente de la observación indicada."
            )
        payload = self._payload(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            observation=request.observation,
        )
        return self._repository.correct_observation(
            DBIFieldObservationCorrection(
                base_version_id=request.base_version_id,
                correction_reason=request.correction_reason,
                payload=payload,
            ),
            recorded_by_ref=context.principal_ref,
        )

    def get_latest(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        observation_id: UUID,
    ) -> DBIFieldObservationVersion:
        self._require_plot(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.READ,
        )
        result = self._repository.get_latest(
            observation_id=observation_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if result is None:
            raise DBIInspectionUnavailable()
        return result

    def list_versions(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        observation_id: UUID,
    ) -> tuple[DBIFieldObservationVersion, ...]:
        self._require_plot(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.READ,
        )
        values = self._repository.list_versions(
            observation_id=observation_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if not values:
            raise DBIInspectionUnavailable()
        return values
