"""Persistencia idempotente y bloqueada de activos de entrada DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.asset_registration import (
    DBIAssetRegistrationAction,
    DBIAssetRegistrationConflict,
    DBIAssetRegistrationIntent,
    DBIAssetRegistrationPlan,
    DBIAssetRegistrationSnapshot,
    build_asset_registration_plan,
)
from app.dbi.asset_verification import DBIAssetVerificationDecision
from app.dbi.models.assets import AnalysisInputAsset


def _required_uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise DBIAssetRegistrationConflict(f"{field_name} debe ser UUID.")
    return value


def _required_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DBIAssetRegistrationConflict(f"{field_name} no es canónico.")
    return value


def _required_plan(value: object) -> DBIAssetRegistrationPlan:
    if not isinstance(value, DBIAssetRegistrationPlan):
        raise DBIAssetRegistrationConflict("plan inválido.")
    return value


def _utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DBIAssetRegistrationConflict(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _intent(plan: DBIAssetRegistrationPlan) -> DBIAssetRegistrationIntent:
    return DBIAssetRegistrationIntent(
        asset_id=plan.asset_id,
        tenant_ref=plan.tenant_ref,
        farm_id=plan.farm_id,
        plot_id=plan.plot_id,
        asset_kind=plan.asset_kind,
        content_type=plan.metadata.content_type,
        size_bytes=plan.metadata.size_bytes,
        sha256=plan.metadata.sha256,
        crs=plan.crs,
        created_by_ref=plan.created_by_ref,
    )


def _snapshot(row: AnalysisInputAsset) -> DBIAssetRegistrationSnapshot:
    if not isinstance(row, AnalysisInputAsset):
        raise DBIAssetRegistrationConflict("registro de activo inválido.")
    return DBIAssetRegistrationSnapshot(
        asset_id=row.id,
        tenant_ref=row.tenant_ref,
        farm_id=row.farm_id,
        plot_id=row.plot_id,
        asset_kind=row.asset_kind,
        status=row.status,
        object_key=row.object_key,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        crs=row.crs,
        created_by_ref=row.created_by_ref,
    )


class DBIAssetRepository:
    """Opera sobre una sesión externa sin confirmar ni revertir transacciones."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBIAssetRegistrationConflict("session debe ser Session.")
        self._session = session

    def get_for_update(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        asset_id: UUID,
    ) -> AnalysisInputAsset | None:
        """Bloquea un activo únicamente dentro del tenant y finca solicitados."""

        tenant = _required_ref(tenant_ref, field_name="tenant_ref")
        farm = _required_uuid(farm_id, field_name="farm_id")
        asset = _required_uuid(asset_id, field_name="asset_id")
        row = self._session.execute(
            select(AnalysisInputAsset)
            .where(
                AnalysisInputAsset.tenant_ref == tenant,
                AnalysisInputAsset.farm_id == farm,
                AnalysisInputAsset.id == asset,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is not None and not isinstance(row, AnalysisInputAsset):
            raise DBIAssetRegistrationConflict("resultado de activo inválido.")
        return row

    def persist_registration(self, *, plan: DBIAssetRegistrationPlan) -> bool:
        """Inserta un plan CREATE o acepta de forma segura un reintento exacto."""

        registration = _required_plan(plan)
        canonical_intent = _intent(registration)
        if registration.action is DBIAssetRegistrationAction.REUSE:
            row = self.get_for_update(
                tenant_ref=registration.tenant_ref,
                farm_id=registration.farm_id,
                asset_id=registration.asset_id,
            )
            if row is None:
                raise DBIAssetRegistrationConflict("activo no disponible.")
            checked = build_asset_registration_plan(
                intent=canonical_intent,
                existing=_snapshot(row),
            )
            if checked.action is not DBIAssetRegistrationAction.REUSE:
                raise DBIAssetRegistrationConflict("reintento divergente.")
            return False

        if registration.action is not DBIAssetRegistrationAction.CREATE:
            raise DBIAssetRegistrationConflict("acción de registro inválida.")

        inserted_id = self._session.execute(
            postgresql_insert(AnalysisInputAsset)
            .values(
                id=registration.asset_id,
                tenant_ref=registration.tenant_ref,
                farm_id=registration.farm_id,
                plot_id=registration.plot_id,
                asset_kind=registration.asset_kind,
                status="registered",
                object_key=registration.metadata.address.object_key,
                content_type=registration.metadata.content_type,
                size_bytes=registration.metadata.size_bytes,
                sha256=registration.metadata.sha256,
                crs=registration.crs,
                created_by_ref=registration.created_by_ref,
                verified_at=None,
            )
            .on_conflict_do_nothing()
            .returning(AnalysisInputAsset.id)
        ).scalar_one_or_none()

        if inserted_id is not None:
            if inserted_id != registration.asset_id:
                raise DBIAssetRegistrationConflict("identidad insertada divergente.")
            return True

        row = self.get_for_update(
            tenant_ref=registration.tenant_ref,
            farm_id=registration.farm_id,
            asset_id=registration.asset_id,
        )
        if row is None:
            raise DBIAssetRegistrationConflict("activo no disponible.")
        checked = build_asset_registration_plan(
            intent=canonical_intent,
            existing=_snapshot(row),
        )
        if checked.action is not DBIAssetRegistrationAction.REUSE:
            raise DBIAssetRegistrationConflict("registro concurrente divergente.")
        return False

    def apply_verification(
        self,
        *,
        row: AnalysisInputAsset,
        decision: DBIAssetVerificationDecision,
        verified_at: datetime,
    ) -> bool:
        """Aplica una transición bloqueada sin confirmar la transacción externa."""

        if not isinstance(row, AnalysisInputAsset):
            raise DBIAssetRegistrationConflict("registro de activo inválido.")
        if not isinstance(decision, DBIAssetVerificationDecision):
            raise DBIAssetRegistrationConflict("decisión de verificación inválida.")
        timestamp = _utc(verified_at, field_name="verified_at")

        if row.status == "verified":
            if decision is not DBIAssetVerificationDecision.VERIFIED or row.verified_at is None:
                raise DBIAssetRegistrationConflict("activo verificado no puede cambiar de estado.")
            return False
        if row.status != "registered":
            raise DBIAssetRegistrationConflict("el activo no admite verificación.")

        row.status = decision.value
        row.verified_at = (
            timestamp if decision is DBIAssetVerificationDecision.VERIFIED else None
        )
        row.updated_at = timestamp
        self._session.flush()
        return True

    def apply_retirement(
        self,
        *,
        row: AnalysisInputAsset,
        retired_at: datetime,
    ) -> bool:
        """Persiste un retiro lógico idempotente sin controlar la transacción."""

        if not isinstance(row, AnalysisInputAsset):
            raise DBIAssetRegistrationConflict(
                "registro de activo inválido."
            )

        timestamp = _utc(
            retired_at,
            field_name="retired_at",
        )

        if row.status == "retired":
            return False

        if row.status not in {
            "registered",
            "verified",
            "quarantined",
        }:
            raise DBIAssetRegistrationConflict(
                "el activo no admite retiro."
            )

        row.status = "retired"
        row.updated_at = timestamp
        self._session.flush()
        return True
