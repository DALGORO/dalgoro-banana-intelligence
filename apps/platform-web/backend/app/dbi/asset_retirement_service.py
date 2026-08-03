"""Servicio autorizado de retiro lógico de activos DBI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from app.dbi.asset_registration import DBIAssetRegistrationConflict
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.models.assets import AnalysisInputAsset
from app.dbi.storage_contracts import (
    DBIPrivateObjectStore,
    DBIStoragePurpose,
)
from app.dbi.storage_policy import DBIStoragePolicy


class DBIAssetRetirementRepositoryPort(Protocol):
    """Persistencia mínima requerida por el servicio de retiro."""

    def get_for_update(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        asset_id: UUID,
    ) -> AnalysisInputAsset | None: ...

    def apply_retirement(
        self,
        *,
        row: AnalysisInputAsset,
        retired_at: datetime,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class DBIAssetRetirementEvidence:
    """Evidencia no sensible del retiro coordinado."""

    object_changed: bool
    state_changed: bool


def _organization_ref(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "*" in value
    ):
        raise DBIAccessDenied()
    return value


def _retirement_timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIAssetRegistrationConflict(
            "retired_at debe incluir zona horaria."
        )
    return value.astimezone(timezone.utc)


class DBIAssetRetirementService:
    """Retira primero el objeto y después persiste el estado DBI."""

    def __init__(
        self,
        repository: DBIAssetRetirementRepositoryPort,
        store: DBIPrivateObjectStore,
    ) -> None:
        if not hasattr(repository, "get_for_update") or not hasattr(
            repository,
            "apply_retirement",
        ):
            raise TypeError(
                "repository no implementa la frontera de retiro."
            )
        if not hasattr(store, "retire"):
            raise TypeError(
                "store no implementa la frontera privada de retiro."
            )

        self._repository = repository
        self._store = store

    def retire(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        asset_id: UUID,
        retired_at: datetime,
    ) -> DBIAssetRetirementEvidence:
        """Coordina un retiro autorizado sin controlar la transacción externa."""

        if not isinstance(context, DBIAccessContext):
            raise DBIAccessDenied()
        if not isinstance(farm_id, UUID) or not isinstance(asset_id, UUID):
            raise TypeError(
                "farm_id y asset_id deben ser UUID."
            )

        organization = _organization_ref(organization_ref)
        timestamp = _retirement_timestamp(retired_at)

        DBIAuthorizationPolicy.require_farm(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization,
            farm_id=farm_id,
            permission=DBIPermission.WRITE,
        )

        row = self._repository.get_for_update(
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            asset_id=asset_id,
        )
        if row is None:
            raise DBIAssetRegistrationConflict(
                "activo no disponible."
            )
        if not isinstance(row, AnalysisInputAsset):
            raise DBIAssetRegistrationConflict(
                "registro de activo inválido."
            )

        if (
            row.tenant_ref != context.tenant_ref
            or row.farm_id != farm_id
            or row.id != asset_id
        ):
            raise DBIAssetRegistrationConflict(
                "identidad de activo divergente."
            )

        if row.plot_id is not None:
            DBIAuthorizationPolicy.require_plot(
                context,
                tenant_ref=context.tenant_ref,
                organization_ref=organization,
                farm_id=farm_id,
                plot_id=row.plot_id,
                permission=DBIPermission.WRITE,
            )

        if row.status not in {
            "registered",
            "verified",
            "quarantined",
            "retired",
        }:
            raise DBIAssetRegistrationConflict(
                "el activo no admite retiro."
            )

        address = DBIStoragePolicy.build_address(
            tenant_ref=row.tenant_ref,
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=row.id,
        )
        if row.object_key != address.object_key:
            raise DBIAssetRegistrationConflict(
                "dirección de objeto divergente."
            )

        object_changed = self._store.retire(
            address,
            retired_at=timestamp,
        )
        if not isinstance(object_changed, bool):
            raise TypeError(
                "store.retire debe devolver bool."
            )

        state_changed = self._repository.apply_retirement(
            row=row,
            retired_at=timestamp,
        )
        if not isinstance(state_changed, bool):
            raise TypeError(
                "apply_retirement debe devolver bool."
            )

        return DBIAssetRetirementEvidence(
            object_changed=object_changed,
            state_changed=state_changed,
        )
