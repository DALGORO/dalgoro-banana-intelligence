"""H14/2H-2C: register a scientific input Asset linked to a locked Campaign.

The transaction owner locks the Campaign and the binding first. Does not
create a multipart session, grant, asset in legacy catalog, or raster bytes.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.dbi.models.scientific_raster_assets import DBIScientificRasterInputAsset
from app.dbi.models.scientific_raster_bindings import DBIScientificRasterBinding
from app.dbi.scientific_raster_binding_repository import (
    ScientificRasterBindingIntent, _canonical, _same,
)


class ScientificRasterAssetConflict(ValueError):
    """Asset/binding does not exactly match the immutable scientific evidence."""


def scientific_asset_id(intent: ScientificRasterBindingIntent) -> UUID:
    _canonical(intent)
    return uuid5(
        NAMESPACE_URL,
        "dalgoro-dbi:h14:scientific-registered-asset:v1:"
        + str(intent.binding_id) + "|" + str(intent.target_object_id),
    )


def _binding_matches(row: DBIScientificRasterBinding, intent: ScientificRasterBindingIntent,
                     asset_id: UUID) -> bool:
    # Reuse exhaustive immutable checks from 2B. Only state and asset_id are
    # permitted to evolve into exactly one pending-byte association.
    pending = row.status == "asset_registered_pending_bytes" and row.asset_id == asset_id
    if not (pending or (row.status == "reserved_no_asset" and row.asset_id is None)):
        return False
    expected = SimpleNamespace(**{
        column.name: getattr(row, column.name)
        for column in DBIScientificRasterBinding.__table__.columns
    })
    expected.status = "reserved_no_asset"
    expected.asset_id = None
    return _same(expected, intent)


def _asset_matches(asset: DBIScientificRasterInputAsset,
                   intent: ScientificRasterBindingIntent, asset_id: UUID) -> bool:
    return all((
        asset.id == asset_id,
        asset.binding_id == intent.binding_id,
        asset.tenant_ref == intent.tenant_ref,
        asset.organization_ref == intent.organization_ref,
        asset.farm_id == intent.farm_id,
        asset.plot_id == intent.plot_id,
        asset.campaign_id == intent.campaign_id,
        asset.role == intent.role,
        asset.index_ref == intent.index_ref,
        asset.asset_kind == ("orthophoto_rgb" if intent.role == "rgb" else "scientific_cog"),
        asset.target_object_id == intent.target_object_id,
        asset.declared_size_bytes == intent.declared_size_bytes,
        asset.declared_sha256 == intent.declared_sha256,
        asset.content_type == "image/tiff",
        asset.status == "registered_pending_bytes",
        asset.file_received is False,
        asset.content_verified is False,
        asset.session_started is False,
        asset.institutional_approved is False,
        asset.published is False,
        asset.created_by_ref == intent.created_by_ref,
    ))


class DBIScientificRasterAssetRepository:
    """No commit or rollback. Caller must hold Campaign row lock."""

    def __init__(self, session: Session):
        if not isinstance(session, Session):
            raise ScientificRasterAssetConflict("Se requiere Session transaccional.")
        self._session = session

    def register_asset(
        self, intent: ScientificRasterBindingIntent,
    ) -> tuple[DBIScientificRasterInputAsset, bool]:
        _canonical(intent)
        asset_id = scientific_asset_id(intent)
        binding = self._session.execute(
            select(DBIScientificRasterBinding)
            .where(
                DBIScientificRasterBinding.id == intent.binding_id,
                DBIScientificRasterBinding.tenant_ref == intent.tenant_ref,
                DBIScientificRasterBinding.organization_ref == intent.organization_ref,
                DBIScientificRasterBinding.farm_id == intent.farm_id,
                DBIScientificRasterBinding.plot_id == intent.plot_id,
                DBIScientificRasterBinding.campaign_id == intent.campaign_id,
                DBIScientificRasterBinding.role == intent.role,
                DBIScientificRasterBinding.index_ref == intent.index_ref,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if binding is None or not _binding_matches(binding, intent, asset_id):
            raise ScientificRasterAssetConflict("El vínculo SQL es inexistente o divergente.")

        inserted = self._session.execute(
            pg_insert(DBIScientificRasterInputAsset).values(
                id=asset_id, binding_id=intent.binding_id,
                tenant_ref=intent.tenant_ref, organization_ref=intent.organization_ref,
                farm_id=intent.farm_id, plot_id=intent.plot_id,
                campaign_id=intent.campaign_id, role=intent.role,
                index_ref=intent.index_ref,
                asset_kind="orthophoto_rgb" if intent.role == "rgb" else "scientific_cog",
                target_object_id=intent.target_object_id,
                declared_size_bytes=intent.declared_size_bytes,
                declared_sha256=intent.declared_sha256,
                content_type="image/tiff", status="registered_pending_bytes",
                file_received=False, content_verified=False, session_started=False,
                institutional_approved=False, published=False,
                created_by_ref=intent.created_by_ref,
            ).on_conflict_do_nothing().returning(DBIScientificRasterInputAsset.id)
        ).scalar_one_or_none()
        asset = self._session.execute(
            select(DBIScientificRasterInputAsset)
            .where(
                DBIScientificRasterInputAsset.id == asset_id,
                DBIScientificRasterInputAsset.binding_id == intent.binding_id,
                DBIScientificRasterInputAsset.tenant_ref == intent.tenant_ref,
                DBIScientificRasterInputAsset.campaign_id == intent.campaign_id,
                DBIScientificRasterInputAsset.role == intent.role,
                DBIScientificRasterInputAsset.index_ref == intent.index_ref,
            ).with_for_update()
        ).scalar_one_or_none()
        if asset is None or not _asset_matches(asset, intent, asset_id):
            raise ScientificRasterAssetConflict("Asset científico existente divergente.")
        if binding.asset_id is None and binding.status == "reserved_no_asset":
            binding.asset_id = asset_id
            binding.status = "asset_registered_pending_bytes"
        elif binding.asset_id != asset_id or binding.status != "asset_registered_pending_bytes":
            raise ScientificRasterAssetConflict("Vínculo ya pertenece a otro Asset.")
        self._session.flush()
        return asset, inserted is not None
