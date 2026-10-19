"""H14/2H-2D: prepare/cancel only SQL session tickets; no provider, no grants."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm, DBIMultipartChecksumType,
    DBIMultipartRoutingDecision,
)
from app.dbi.asset_multipart_policy import (
    DBI_MULTIPART_DEFAULT_LIMITS, DBIMultipartPolicy, DBIMultipartPolicyError,
)
from app.dbi.models.scientific_raster_assets import DBIScientificRasterInputAsset
from app.dbi.models.scientific_raster_bindings import DBIScientificRasterBinding
from app.dbi.models.scientific_raster_session_preparations import (
    DBIScientificRasterSessionPreparation,
)
from app.dbi.scientific_raster_asset_repository import (
    _asset_matches, _binding_matches, scientific_asset_id,
)
from app.dbi.scientific_raster_binding_repository import (
    ScientificRasterBindingIntent, _canonical,
)

SESSION_PREPARATION_TTL = timedelta(hours=1)


class ScientificSessionPreparationConflict(ValueError):
    """Ticket contradicts the approved scope, contract or earlier receipt."""


@dataclass(frozen=True, slots=True)
class SessionPreparationRequest:
    raster: ScientificRasterBindingIntent
    idempotency_key: str
    requested_by: str

    @property
    def asset_id(self) -> UUID:
        return scientific_asset_id(self.raster)


def _validate(value: SessionPreparationRequest):
    if not isinstance(value, SessionPreparationRequest):
        raise ScientificSessionPreparationConflict("Solicitud preparatoria inválida.")
    _canonical(value.raster)
    if value.requested_by != value.raster.created_by_ref:
        raise ScientificSessionPreparationConflict("Operador distinto del registrador.")
    try:
        idempotency = DBIMultipartPolicy.build_idempotency_identity(
            idempotency_key=value.idempotency_key,
            asset_id=value.asset_id,
            content_type="image/tiff",
            size_bytes=value.raster.declared_size_bytes,
            sha256_hex=value.raster.declared_sha256,
        )
        plan = DBIMultipartPolicy.build_upload_plan(
            size_bytes=value.raster.declared_size_bytes,
            limits=DBI_MULTIPART_DEFAULT_LIMITS,
            checksum_algorithm=DBIMultipartChecksumAlgorithm.SHA256,
            checksum_type=DBIMultipartChecksumType.COMPOSITE,
        )
    except DBIMultipartPolicyError as error:
        raise ScientificSessionPreparationConflict("Declaración multipart inválida.") from error
    if plan.decision != DBIMultipartRoutingDecision.MULTIPART:
        raise ScientificSessionPreparationConflict(
            "Solo TIFF con plan MULTIPART >64MiB admiten preparación.",
        )
    return idempotency, plan


def _id(asset_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, "dalgoro-dbi:h14:scientific-multipart-preparation:v1:" + str(asset_id))


def _same(row: DBIScientificRasterSessionPreparation, value: SessionPreparationRequest,
          key_hash: str, plan) -> bool:
    raster = value.raster
    return all((
        row.id == _id(value.asset_id),
        row.asset_id == value.asset_id,
        row.binding_id == raster.binding_id,
        row.tenant_ref == raster.tenant_ref,
        row.organization_ref == raster.organization_ref,
        row.farm_id == raster.farm_id,
        row.plot_id == raster.plot_id,
        row.campaign_id == raster.campaign_id,
        row.manifest_sha256 == raster.manifest_sha256,
        row.reservation_sha256 == raster.slot_sha256,
        row.declared_sha256 == raster.declared_sha256,
        row.size_bytes == raster.declared_size_bytes,
        row.part_size_bytes == plan.part_size_bytes,
        row.part_count == plan.part_count,
        row.max_grants_per_window == plan.max_grants_per_window,
        row.max_client_concurrency == plan.max_client_concurrency,
        row.checksum_algorithm == "SHA256",
        row.checksum_type == "COMPOSITE",
        row.idempotency_key_hash == key_hash,
        row.created_by_ref == value.requested_by,
        row.status in ("prepared_no_provider", "cancelled_no_provider"),
        row.expires_at > row.created_at,
    ))


class DBIScientificSessionPreparationRepository:
    """Caller holds Campaign SELECT FOR UPDATE and owns the transaction."""

    def __init__(self, session: Session):
        if not isinstance(session, Session):
            raise ScientificSessionPreparationConflict("Session SQL requerida.")
        self._session = session

    def _lock_evidence(self, value: SessionPreparationRequest) -> None:
        raster = value.raster
        binding = self._session.execute(
            select(DBIScientificRasterBinding).where(
                DBIScientificRasterBinding.id == raster.binding_id,
                DBIScientificRasterBinding.tenant_ref == raster.tenant_ref,
                DBIScientificRasterBinding.organization_ref == raster.organization_ref,
                DBIScientificRasterBinding.farm_id == raster.farm_id,
                DBIScientificRasterBinding.plot_id == raster.plot_id,
                DBIScientificRasterBinding.campaign_id == raster.campaign_id,
                DBIScientificRasterBinding.role == raster.role,
                DBIScientificRasterBinding.index_ref == raster.index_ref,
            ).with_for_update()
        ).scalar_one_or_none()
        if binding is None or not _binding_matches(binding, raster, value.asset_id):
            raise ScientificSessionPreparationConflict("Binding científico ausente/divergente.")
        asset = self._session.execute(
            select(DBIScientificRasterInputAsset).where(
                DBIScientificRasterInputAsset.id == value.asset_id,
                DBIScientificRasterInputAsset.binding_id == raster.binding_id,
                DBIScientificRasterInputAsset.tenant_ref == raster.tenant_ref,
                DBIScientificRasterInputAsset.campaign_id == raster.campaign_id,
                DBIScientificRasterInputAsset.role == raster.role,
                DBIScientificRasterInputAsset.index_ref == raster.index_ref,
            ).with_for_update()
        ).scalar_one_or_none()
        if asset is None or not _asset_matches(asset, raster, value.asset_id):
            raise ScientificSessionPreparationConflict("Asset científico ausente/divergente.")

    def _get(self, value: SessionPreparationRequest):
        raster = value.raster
        return self._session.execute(
            select(DBIScientificRasterSessionPreparation).where(
                DBIScientificRasterSessionPreparation.asset_id == value.asset_id,
                DBIScientificRasterSessionPreparation.binding_id == raster.binding_id,
                DBIScientificRasterSessionPreparation.tenant_ref == raster.tenant_ref,
                DBIScientificRasterSessionPreparation.campaign_id == raster.campaign_id,
            ).with_for_update()
        ).scalar_one_or_none()

    def prepare(self, value: SessionPreparationRequest, *, now: datetime):
        idempotency, plan = _validate(value)
        now = _now(now)
        self._lock_evidence(value)
        row = self._get(value)
        if row is None:
            inserted = self._session.execute(
                pg_insert(DBIScientificRasterSessionPreparation).values(
                    id=_id(value.asset_id), asset_id=value.asset_id,
                    binding_id=value.raster.binding_id,
                    tenant_ref=value.raster.tenant_ref,
                    organization_ref=value.raster.organization_ref,
                    farm_id=value.raster.farm_id, plot_id=value.raster.plot_id,
                    campaign_id=value.raster.campaign_id,
                    manifest_sha256=value.raster.manifest_sha256,
                    reservation_sha256=value.raster.slot_sha256,
                    declared_sha256=value.raster.declared_sha256,
                    size_bytes=value.raster.declared_size_bytes,
                    part_size_bytes=plan.part_size_bytes, part_count=plan.part_count,
                    max_grants_per_window=plan.max_grants_per_window,
                    max_client_concurrency=plan.max_client_concurrency,
                    checksum_algorithm="SHA256", checksum_type="COMPOSITE",
                    idempotency_key_hash=idempotency.key_hash,
                    status="prepared_no_provider", created_by_ref=value.requested_by,
                    created_at=now, updated_at=now,
                    expires_at=now + SESSION_PREPARATION_TTL, cancelled_at=None,
                ).on_conflict_do_nothing().returning(DBIScientificRasterSessionPreparation.id)
            ).scalar_one_or_none()
            row = self._get(value)
            created = inserted is not None
        else:
            created = False
        if row is None or not _same(row, value, idempotency.key_hash, plan):
            raise ScientificSessionPreparationConflict("Ticket existente divergente.")
        if row.status != "prepared_no_provider" or now >= row.expires_at:
            raise ScientificSessionPreparationConflict("Ticket cancelado o caducado.")
        return row, created

    def inspect(self, value: SessionPreparationRequest, *, now: datetime):
        idempotency, plan = _validate(value)
        now = _now(now)
        self._lock_evidence(value)
        row = self._get(value)
        if row is None or not _same(row, value, idempotency.key_hash, plan):
            raise ScientificSessionPreparationConflict("Ticket inexistente/divergente.")
        return row

    def cancel(self, value: SessionPreparationRequest, *, now: datetime):
        row = self.inspect(value, now=now)
        now = _now(now)
        changed = row.status == "prepared_no_provider"
        if changed:
            row.status = "cancelled_no_provider"
            row.cancelled_at = now
            row.updated_at = now
            self._session.flush()
        return row, changed


def _now(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ScientificSessionPreparationConflict("Hora debe incluir zona horaria.")
    return now.astimezone(timezone.utc)
