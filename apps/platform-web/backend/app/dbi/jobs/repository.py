"""Persistencia idempotente y bloqueada para trabajos geoespaciales DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.jobs.persistence_contracts import (
    AnalysisJobPersistenceConflict,
    AnalysisJobResourceUnavailable,
    AnalysisJobSnapshot,
)
from app.dbi.jobs.service_contracts import (
    AnalysisJobRequestIntent,
    analysis_job_request_fingerprint,
)
from app.dbi.jobs.state_machine import AnalysisJobStatus
from app.dbi.models.agriculture import Campaign, Farm, Plot
from app.dbi.models.analysis_jobs import AnalysisJob
from app.dbi.models.assets import AnalysisInputAsset


def _required_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AnalysisJobPersistenceConflict(f"{field_name} no es canónico.")
    return value


def _required_uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise AnalysisJobPersistenceConflict(f"{field_name} debe ser UUID.")
    return value


def _utc(value: object, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AnalysisJobPersistenceConflict(
            f"{field_name} debe incluir zona horaria."
        )
    return value.astimezone(timezone.utc)


def _canonical_uuid_ref(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, str) or not value:
        raise AnalysisJobPersistenceConflict(f"{field_name} inválido.")
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as error:
        raise AnalysisJobPersistenceConflict(f"{field_name} inválido.") from error
    if value != str(parsed):
        raise AnalysisJobPersistenceConflict(f"{field_name} no es canónico.")
    return parsed


def _status(value: object) -> AnalysisJobStatus:
    try:
        return AnalysisJobStatus(value)
    except (TypeError, ValueError) as error:
        raise AnalysisJobPersistenceConflict("estado de trabajo inválido.") from error


def _snapshot(row: AnalysisJob) -> AnalysisJobSnapshot:
    if not isinstance(row, AnalysisJob):
        raise AnalysisJobPersistenceConflict("registro de trabajo inválido.")
    return AnalysisJobSnapshot(
        job_id=row.id,
        tenant_ref=row.tenant_ref,
        request_id=row.request_id,
        correlation_id=row.correlation_id,
        farm_id=row.farm_id,
        plot_id=row.plot_id,
        campaign_id=row.campaign_id,
        orthophoto_asset_id=_canonical_uuid_ref(
            row.orthophoto_asset_ref,
            field_name="orthophoto_asset_ref",
        ),
        boundary_asset_id=_canonical_uuid_ref(
            row.boundary_asset_ref,
            field_name="boundary_asset_ref",
        ),
        exclusions_asset_id=(
            None
            if row.exclusions_asset_ref is None
            else _canonical_uuid_ref(
                row.exclusions_asset_ref,
                field_name="exclusions_asset_ref",
            )
        ),
        model_version_id=row.model_version_ref,
        pipeline_config_version=row.pipeline_config_version,
        requested_by_ref=row.requested_by_ref,
        command_sha256=row.command_sha256,
        status=_status(row.status),
        accepted_at=_utc(row.accepted_at, field_name="accepted_at"),
        updated_at=_utc(row.updated_at, field_name="updated_at"),
    )


def _intent_from_snapshot(snapshot: AnalysisJobSnapshot) -> AnalysisJobRequestIntent:
    return AnalysisJobRequestIntent(
        tenant_ref=snapshot.tenant_ref,
        request_id=snapshot.request_id,
        farm_id=snapshot.farm_id,
        plot_id=snapshot.plot_id,
        campaign_id=snapshot.campaign_id,
        orthophoto_asset_id=snapshot.orthophoto_asset_id,
        boundary_asset_id=snapshot.boundary_asset_id,
        exclusions_asset_id=snapshot.exclusions_asset_id,
        requested_by_ref=snapshot.requested_by_ref,
    )


class DBIAnalysisJobRepository:
    """Opera sobre una sesión externa sin commit, rollback ni efectos remotos."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise AnalysisJobPersistenceConflict("session debe ser Session.")
        self._session = session

    def require_plot(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> None:
        """Valida pertenencia exacta de finca y lote sin cargar su geometría."""

        organization = _required_ref(organization_ref, field_name="organization_ref")
        farm = _required_uuid(farm_id, field_name="farm_id")
        plot = _required_uuid(plot_id, field_name="plot_id")
        row_id = self._session.execute(
            select(Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(
                Farm.organization_ref == organization,
                Farm.id == farm,
                Plot.id == plot,
                Plot.farm_id == farm,
            )
        ).scalar_one_or_none()
        if row_id is None:
            raise AnalysisJobResourceUnavailable("lote no disponible.")

    def require_campaign(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
        campaign_id: UUID,
    ) -> None:
        """Valida campaña y finca con lectura; las FK conservan la integridad."""

        organization = _required_ref(organization_ref, field_name="organization_ref")
        farm = _required_uuid(farm_id, field_name="farm_id")
        campaign = _required_uuid(campaign_id, field_name="campaign_id")
        row_id = self._session.execute(
            select(Campaign.id)
            .join(Farm, Campaign.farm_id == Farm.id)
            .where(
                Farm.organization_ref == organization,
                Campaign.id == campaign,
                Campaign.farm_id == farm,
            )
        ).scalar_one_or_none()
        if row_id is None:
            raise AnalysisJobResourceUnavailable("campaña no disponible.")

    def require_verified_asset(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        asset_id: UUID,
        asset_kind: str,
    ) -> None:
        """Bloquea el activo verified para evitar retiro concurrente."""

        tenant = _required_ref(tenant_ref, field_name="tenant_ref")
        farm = _required_uuid(farm_id, field_name="farm_id")
        plot = _required_uuid(plot_id, field_name="plot_id")
        asset = _required_uuid(asset_id, field_name="asset_id")
        kind = _required_ref(asset_kind, field_name="asset_kind")
        row_id = self._session.execute(
            select(AnalysisInputAsset.id)
            .where(
                AnalysisInputAsset.id == asset,
                AnalysisInputAsset.tenant_ref == tenant,
                AnalysisInputAsset.farm_id == farm,
                AnalysisInputAsset.plot_id == plot,
                AnalysisInputAsset.asset_kind == kind,
                AnalysisInputAsset.status == "verified",
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row_id is None:
            raise AnalysisJobResourceUnavailable("activo no disponible.")

    def get_by_request_for_update(
        self,
        *,
        tenant_ref: str,
        request_id: str,
    ) -> AnalysisJobSnapshot | None:
        tenant = _required_ref(tenant_ref, field_name="tenant_ref")
        request = _required_ref(request_id, field_name="request_id")
        row = self._session.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.tenant_ref == tenant,
                AnalysisJob.request_id == request,
            )
            .with_for_update()
        ).scalar_one_or_none()
        return None if row is None else _snapshot(row)

    def get_for_update(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        job_id: UUID,
    ) -> AnalysisJobSnapshot | None:
        tenant = _required_ref(tenant_ref, field_name="tenant_ref")
        farm = _required_uuid(farm_id, field_name="farm_id")
        job = _required_uuid(job_id, field_name="job_id")
        row = self._session.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.id == job,
                AnalysisJob.tenant_ref == tenant,
                AnalysisJob.farm_id == farm,
            )
            .with_for_update()
        ).scalar_one_or_none()
        return None if row is None else _snapshot(row)

    @staticmethod
    def require_same_intent(
        *,
        existing: AnalysisJobSnapshot,
        incoming: AnalysisJobRequestIntent,
    ) -> None:
        if not isinstance(existing, AnalysisJobSnapshot):
            raise AnalysisJobPersistenceConflict("trabajo existente inválido.")
        if not isinstance(incoming, AnalysisJobRequestIntent):
            raise AnalysisJobPersistenceConflict("intención entrante inválida.")
        historical = _intent_from_snapshot(existing)
        if (
            historical != incoming
            or analysis_job_request_fingerprint(historical)
            != analysis_job_request_fingerprint(incoming)
        ):
            raise AnalysisJobPersistenceConflict("reintento divergente.")

    def persist_accepted(
        self,
        *,
        candidate: AnalysisJobSnapshot,
        intent: AnalysisJobRequestIntent,
    ) -> tuple[AnalysisJobSnapshot, bool]:
        if not isinstance(candidate, AnalysisJobSnapshot):
            raise AnalysisJobPersistenceConflict("candidato inválido.")
        if candidate.status is not AnalysisJobStatus.ACCEPTED:
            raise AnalysisJobPersistenceConflict(
                "un trabajo nuevo debe iniciar en accepted."
            )
        if not isinstance(intent, AnalysisJobRequestIntent):
            raise AnalysisJobPersistenceConflict("intención inválida.")

        inserted_id = self._session.execute(
            postgresql_insert(AnalysisJob)
            .values(
                id=candidate.job_id,
                tenant_ref=candidate.tenant_ref,
                request_id=candidate.request_id,
                correlation_id=candidate.correlation_id,
                farm_id=candidate.farm_id,
                plot_id=candidate.plot_id,
                campaign_id=candidate.campaign_id,
                orthophoto_asset_ref=str(candidate.orthophoto_asset_id),
                boundary_asset_ref=str(candidate.boundary_asset_id),
                exclusions_asset_ref=(
                    None
                    if candidate.exclusions_asset_id is None
                    else str(candidate.exclusions_asset_id)
                ),
                model_version_ref=candidate.model_version_id,
                pipeline_config_version=candidate.pipeline_config_version,
                requested_by_ref=candidate.requested_by_ref,
                command_sha256=candidate.command_sha256,
                status=AnalysisJobStatus.ACCEPTED.value,
                accepted_at=candidate.accepted_at,
                created_at=candidate.accepted_at,
                updated_at=candidate.updated_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_dbi_analysis_jobs_tenant_request"
            )
            .returning(AnalysisJob.id)
        ).scalar_one_or_none()

        if inserted_id is not None:
            if inserted_id != candidate.job_id:
                raise AnalysisJobPersistenceConflict("identidad insertada divergente.")
            persisted = self.get_for_update(
                tenant_ref=candidate.tenant_ref,
                farm_id=candidate.farm_id,
                job_id=candidate.job_id,
            )
            if persisted is None:
                raise AnalysisJobPersistenceConflict("trabajo insertado no recuperable.")
            return persisted, True

        existing = self.get_by_request_for_update(
            tenant_ref=candidate.tenant_ref,
            request_id=candidate.request_id,
        )
        if existing is None:
            raise AnalysisJobPersistenceConflict("clave idempotente no recuperable.")
        self.require_same_intent(existing=existing, incoming=intent)
        return existing, False

    def apply_status(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        job_id: UUID,
        expected_status: AnalysisJobStatus,
        target_status: AnalysisJobStatus,
        changed_at: datetime,
    ) -> AnalysisJobSnapshot:
        tenant = _required_ref(tenant_ref, field_name="tenant_ref")
        farm = _required_uuid(farm_id, field_name="farm_id")
        job = _required_uuid(job_id, field_name="job_id")
        if not isinstance(expected_status, AnalysisJobStatus):
            raise AnalysisJobPersistenceConflict("expected_status inválido.")
        if not isinstance(target_status, AnalysisJobStatus):
            raise AnalysisJobPersistenceConflict("target_status inválido.")
        timestamp = _utc(changed_at, field_name="changed_at")

        row = self._session.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.id == job,
                AnalysisJob.tenant_ref == tenant,
                AnalysisJob.farm_id == farm,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise AnalysisJobResourceUnavailable("trabajo no disponible.")
        current = _status(row.status)
        if current is not expected_status:
            raise AnalysisJobPersistenceConflict(
                "el trabajo cambió durante la operación."
            )
        row.status = target_status.value
        row.updated_at = timestamp
        self._session.flush()
        return _snapshot(row)
