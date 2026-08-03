"""Orquestación autorizada de registro y grant temporal de carga DBI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from app.dbi.asset_registration import DBIAssetRegistrationConflict
from app.dbi.asset_schemas import AnalysisInputAssetRegister
from app.dbi.asset_service import DBIAssetRegistrationEvidence, DBIAssetService
from app.dbi.authorization import DBIAccessContext
from app.dbi.storage_contracts import (
    DBIPrivateObjectStore,
    DBIStorageAccessMode,
    DBIStorageConflict,
    DBIStorageError,
    DBIStorageTemporaryGrant,
)
from app.dbi.storage_policy import DBIStoragePolicy


class DBIAssetUploadGrantFailure(RuntimeError):
    """El grant no fue emitido y la transacción externa debe revertirse."""


class DBIAssetRegistrationServicePort(Protocol):
    def register(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        request: AnalysisInputAssetRegister,
    ) -> DBIAssetRegistrationEvidence: ...


@dataclass(frozen=True, slots=True)
class DBIAssetUploadEvidence:
    """Resultado no persistente de registro y autorización temporal de carga."""

    registration: DBIAssetRegistrationEvidence
    grant: DBIStorageTemporaryGrant


class DBIAssetUploadService:
    """Coordina registro y grant sin confirmar ni revertir la transacción.

    La frontera que posea la unidad de trabajo debe hacer commit únicamente
    después de recibir evidencia completa. Ante DBIAssetUploadGrantFailure debe
    ejecutar rollback; este servicio no borra registros ni controla sesiones.
    """

    def __init__(
        self,
        registration_service: DBIAssetRegistrationServicePort,
        object_store: DBIPrivateObjectStore,
        *,
        grant_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        if not isinstance(registration_service, DBIAssetService) and not hasattr(
            registration_service, "register"
        ):
            raise TypeError("registration_service no cumple el puerto requerido.")
        if not hasattr(object_store, "issue_temporary_access"):
            raise TypeError("object_store no cumple el puerto requerido.")
        if not isinstance(grant_ttl, timedelta):
            raise TypeError("grant_ttl debe ser timedelta.")
        issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
        DBIStoragePolicy.validate_access_window(
            issued_at=issued,
            expires_at=issued + grant_ttl,
        )
        self._registration_service = registration_service
        self._object_store = object_store
        self._grant_ttl = grant_ttl

    def register_and_issue_upload(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        request: AnalysisInputAssetRegister,
        issued_at: datetime,
    ) -> DBIAssetUploadEvidence:
        """Registra metadata y emite un grant WRITE vinculado al mismo objeto."""

        registration = self._registration_service.register(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            request=request,
        )
        if registration.plan.status != "registered":
            raise DBIAssetRegistrationConflict(
                "Solo un activo registrado admite un nuevo grant de carga."
            )

        expires_at = issued_at + self._grant_ttl
        DBIStoragePolicy.validate_access_window(
            issued_at=issued_at,
            expires_at=expires_at,
        )
        try:
            grant = self._object_store.issue_temporary_access(
                registration.plan.metadata,
                mode=DBIStorageAccessMode.WRITE,
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except DBIStorageConflict as error:
            raise DBIAssetRegistrationConflict(
                "La clave privada del activo no está disponible para carga."
            ) from error
        except (DBIStorageError, TypeError, ValueError) as error:
            raise DBIAssetUploadGrantFailure(
                "No fue posible emitir el grant; la unidad de trabajo debe revertirse."
            ) from error

        try:
            DBIStoragePolicy.validate_grant(grant)
        except (DBIStorageError, TypeError, ValueError) as error:
            raise DBIAssetUploadGrantFailure(
                "El proveedor devolvió un grant inválido."
            ) from error

        if (
            grant.metadata != registration.plan.metadata
            or grant.mode is not DBIStorageAccessMode.WRITE
        ):
            raise DBIAssetUploadGrantFailure(
                "El proveedor devolvió un grant divergente; la unidad de trabajo debe revertirse."
            )
        return DBIAssetUploadEvidence(
            registration=registration,
            grant=grant,
        )
