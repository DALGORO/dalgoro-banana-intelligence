"""Servicio autorizado y transaccional para registrar activos DBI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.dbi.asset_registration import (
    DBIAssetRegistrationIntent,
    DBIAssetRegistrationPlan,
    build_asset_registration_plan,
)
from app.dbi.asset_schemas import AnalysisInputAssetRegister
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)


class DBIAssetRegistrationRepositoryPort(Protocol):
    """Persistencia sobre una transacción externa, sin commit interno."""

    def persist_registration(
        self,
        *,
        plan: DBIAssetRegistrationPlan,
    ) -> DBIAssetRegistrationPlan: ...


@dataclass(frozen=True, slots=True)
class DBIAssetRegistrationEvidence:
    """Resultado no sensible del registro autorizado."""

    plan: DBIAssetRegistrationPlan
    created: bool


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


class DBIAssetService:
    """Autoriza, planifica y persiste registros sin abrir transacciones."""

    def __init__(self, repository: DBIAssetRegistrationRepositoryPort) -> None:
        if not hasattr(repository, "persist_registration"):
            raise TypeError("repository no implementa persist_registration.")
        self._repository = repository

    def register(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        request: AnalysisInputAssetRegister,
    ) -> DBIAssetRegistrationEvidence:
        """Registra un activo dentro del tenant y ámbito persistidos del actor."""

        if not isinstance(context, DBIAccessContext):
            raise DBIAccessDenied()
        if not isinstance(request, AnalysisInputAssetRegister):
            raise TypeError("request debe ser AnalysisInputAssetRegister.")

        organization = _required_organization_ref(organization_ref)
        farm = _required_uuid(farm_id, field_name="farm_id")
        if request.plot_id is None:
            DBIAuthorizationPolicy.require_farm(
                context,
                tenant_ref=context.tenant_ref,
                organization_ref=organization,
                farm_id=farm,
                permission=DBIPermission.WRITE,
            )
        else:
            DBIAuthorizationPolicy.require_plot(
                context,
                tenant_ref=context.tenant_ref,
                organization_ref=organization,
                farm_id=farm,
                plot_id=request.plot_id,
                permission=DBIPermission.WRITE,
            )

        plan = build_asset_registration_plan(
            intent=DBIAssetRegistrationIntent(
                asset_id=request.asset_id,
                tenant_ref=context.tenant_ref,
                farm_id=farm,
                plot_id=request.plot_id,
                asset_kind=request.asset_kind,
                content_type=request.content_type,
                size_bytes=request.size_bytes,
                sha256=request.sha256,
                crs=request.crs,
                created_by_ref=context.principal_ref,
            ),
            existing=None,
        )
        persisted_plan = self._repository.persist_registration(plan=plan)
        if not isinstance(persisted_plan, DBIAssetRegistrationPlan):
            raise TypeError(
                "persist_registration debe devolver DBIAssetRegistrationPlan."
            )
        return DBIAssetRegistrationEvidence(
            plan=persisted_plan,
            created=persisted_plan.created,
        )
