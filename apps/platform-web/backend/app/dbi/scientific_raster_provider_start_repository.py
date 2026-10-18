"""H14/2H-2D/2: SQL ledger of real local multipart initiations, never grants."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.dbi.asset_multipart_provider import DBIMultipartProviderPolicy, DBIMultipartProviderUpload
from app.dbi.models.scientific_raster_provider_starts import DBIScientificRasterProviderStart
from app.dbi.scientific_raster_session_repository import SessionPreparationRequest, _id


class ScientificProviderStartConflict(ValueError):
    pass


def _verify(row: DBIScientificRasterProviderStart, value: SessionPreparationRequest,
            upload_ref: str | None = None) -> None:
    r = value.raster
    if not all((
        row.id == _id(value.asset_id),
        row.preparation_id == _id(value.asset_id),
        row.asset_id == value.asset_id,
        row.binding_id == r.binding_id,
        row.tenant_ref == r.tenant_ref,
        row.organization_ref == r.organization_ref,
        row.farm_id == r.farm_id,
        row.plot_id == r.plot_id,
        row.campaign_id == r.campaign_id,
        row.target_object_id == r.target_object_id,
        row.declared_sha256 == r.declared_sha256,
        row.size_bytes == r.declared_size_bytes,
        row.created_by_ref == value.requested_by,
        row.status in {"initiated_no_grants", "aborted_no_grants"},
        isinstance(row.provider_upload_ref, str),
    )):
        raise ScientificProviderStartConflict("Registro proveedor divergente.")
    DBIMultipartProviderPolicy.provider_ref(row.provider_upload_ref)
    if upload_ref is not None and row.provider_upload_ref != upload_ref:
        raise ScientificProviderStartConflict("La referencia remota ha cambiado.")


class DBIScientificProviderStartRepository:
    """All calls under Campaign, Asset, ticket and provider-start SQL locks."""

    def __init__(self, session: Session):
        if not isinstance(session, Session):
            raise ScientificProviderStartConflict("Se requiere Session SQL.")
        self.session = session

    def get(self, value: SessionPreparationRequest):
        row = self.session.execute(
            select(DBIScientificRasterProviderStart).where(
                DBIScientificRasterProviderStart.preparation_id == _id(value.asset_id),
                DBIScientificRasterProviderStart.tenant_ref == value.raster.tenant_ref,
                DBIScientificRasterProviderStart.campaign_id == value.raster.campaign_id,
                DBIScientificRasterProviderStart.asset_id == value.asset_id,
                DBIScientificRasterProviderStart.binding_id == value.raster.binding_id,
            ).with_for_update()
        ).scalar_one_or_none()
        if row is not None:
            _verify(row, value)
        return row

    def record_start(self, value: SessionPreparationRequest,
                     upload: DBIMultipartProviderUpload, *, now: datetime):
        DBIMultipartProviderPolicy.validate_upload(upload)
        if upload.session_id != _id(value.asset_id):
            raise ScientificProviderStartConflict("El proveedor devolvió otra sesión.")
        if upload.metadata.address.object_id != value.raster.target_object_id:
            raise ScientificProviderStartConflict("El proveedor devolvió otro TIFF.")
        if upload.metadata.size_bytes != value.raster.declared_size_bytes or (
            upload.metadata.sha256 != value.raster.declared_sha256
        ):
            raise ScientificProviderStartConflict("El proveedor devolvió otros bytes declarados.")
        if self.get(value) is not None:
            raise ScientificProviderStartConflict("La sesión ya fue iniciada.")
        self.session.execute(
            pg_insert(DBIScientificRasterProviderStart).values(
                id=_id(value.asset_id), preparation_id=_id(value.asset_id),
                asset_id=value.asset_id, binding_id=value.raster.binding_id,
                tenant_ref=value.raster.tenant_ref,
                organization_ref=value.raster.organization_ref,
                farm_id=value.raster.farm_id, plot_id=value.raster.plot_id,
                campaign_id=value.raster.campaign_id,
                target_object_id=value.raster.target_object_id,
                declared_sha256=value.raster.declared_sha256,
                size_bytes=value.raster.declared_size_bytes,
                provider_upload_ref=upload.provider_upload_ref,
                status="initiated_no_grants", created_by_ref=value.requested_by,
                created_at=now, updated_at=now, aborted_at=None,
            ).on_conflict_do_nothing()
        )
        row = self.get(value)
        if row is None:
            raise ScientificProviderStartConflict("No se guardó el inicio S3.")
        _verify(row, value, upload.provider_upload_ref)
        if row.status != "initiated_no_grants":
            raise ScientificProviderStartConflict("Inicio remoto ya fue abortado.")
        return row

    def mark_aborted(self, value: SessionPreparationRequest, *, now: datetime):
        row = self.get(value)
        if row is None:
            raise ScientificProviderStartConflict("No existe sesión iniciada.")
        changed = row.status == "initiated_no_grants"
        if changed:
            row.status = "aborted_no_grants"
            row.aborted_at = now
            row.updated_at = now
            self.session.flush()
        return row, changed
