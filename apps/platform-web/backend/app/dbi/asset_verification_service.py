"""Servicio autorizado de confirmación y verificación de activos DBI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.dbi.asset_registration import DBIAssetRegistrationConflict
from app.dbi.asset_verification import (
    DBIAssetVerificationDecision,
    DBIAssetVerificationResult,
    verify_asset_content,
)
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.models.assets import AnalysisInputAsset
from app.dbi.storage_contracts import DBIPrivateObjectStore, DBIStoragePurpose
from app.dbi.storage_policy import DBIStoragePolicy


class DBIAssetVerificationRepositoryPort(Protocol):
    def get_for_update(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        asset_id: UUID,
    ) -> AnalysisInputAsset | None: ...

    def apply_verification(
        self,
        *,
        row: AnalysisInputAsset,
        decision,
        verified_at: datetime,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class DBIAssetVerificationEvidence:
    """Evidencia no sensible de la confirmación."""

    result: DBIAssetVerificationResult
    changed: bool


def _organization_ref(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "*" in value:
        raise DBIAccessDenied()
    return value


class DBIAssetVerificationService:
    """Bloquea, lee completamente y transiciona un activo autorizado."""

    def __init__(
        self,
        repository: DBIAssetVerificationRepositoryPort,
        store: DBIPrivateObjectStore,
    ) -> None:
        if not hasattr(repository, "get_for_update") or not hasattr(
            repository, "apply_verification"
        ):
            raise TypeError("repository no implementa la frontera de verificación.")
        if not hasattr(store, "stat") or not hasattr(store, "open_read"):
            raise TypeError("store no implementa la frontera privada requerida.")
        self._repository = repository
        self._store = store

    def confirm(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        asset_id: UUID,
        verified_at: datetime,
    ) -> DBIAssetVerificationEvidence:
        """Confirma contenido real sin abrir ni cerrar la transacción externa."""

        if not isinstance(context, DBIAccessContext):
            raise DBIAccessDenied()
        if not isinstance(farm_id, UUID) or not isinstance(asset_id, UUID):
            raise TypeError("farm_id y asset_id deben ser UUID.")
        organization = _organization_ref(organization_ref)
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
            raise DBIAssetRegistrationConflict("activo no disponible.")
        if row.plot_id is not None:
            DBIAuthorizationPolicy.require_plot(
                context,
                tenant_ref=context.tenant_ref,
                organization_ref=organization,
                farm_id=farm_id,
                plot_id=row.plot_id,
                permission=DBIPermission.WRITE,
            )

        expected_address = DBIStoragePolicy.build_address(
            tenant_ref=row.tenant_ref,
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=row.id,
        )
        if row.object_key != expected_address.object_key:
            raise DBIAssetRegistrationConflict("dirección de objeto divergente.")

        expected = DBIStoragePolicy.build_metadata(
            address=expected_address,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            sha256_hex=row.sha256,
        )
        record = self._store.stat(expected.address)
        DBIStoragePolicy.validate_record(record)
        if record.metadata.address != expected.address:
            raise DBIAssetRegistrationConflict("dirección de objeto divergente.")

        if record.metadata != expected:
            result = DBIAssetVerificationResult(
                decision=DBIAssetVerificationDecision.QUARANTINED,
                observed_size_bytes=record.metadata.size_bytes,
                observed_sha256=record.metadata.sha256,
                content_type_matches=(
                    record.metadata.content_type == expected.content_type
                ),
            )
        else:
            with self._store.open_read(expected.address) as content:
                result = verify_asset_content(
                    expected=expected,
                    observed_content_type=record.metadata.content_type,
                    content=content,
                )
        changed = self._repository.apply_verification(
            row=row,
            decision=result.decision,
            verified_at=verified_at,
        )
        if not isinstance(changed, bool):
            raise TypeError("apply_verification debe devolver bool.")
        return DBIAssetVerificationEvidence(result=result, changed=changed)
