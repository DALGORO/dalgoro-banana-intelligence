"""H14/2H-2B: persistencia idempotente de vínculos privados bajo UoW externa.

Este repositorio NO registra activos ni inicia multipart. El caller debe
bloquear Campaign con SELECT FOR UPDATE antes de llamar a persist_binding.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.dbi.models.scientific_raster_bindings import DBIScientificRasterBinding


class ScientificRasterBindingConflict(ValueError):
    """Se detectó una identidad o vínculo científico divergente."""


@dataclass(frozen=True, slots=True)
class ScientificRasterBindingIntent:
    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    campaign_id: UUID
    manifest_object_id: UUID
    manifest_sha256: str
    slot_object_id: UUID
    slot_sha256: str
    role: str
    index_ref: str
    target_object_id: UUID
    declared_size_bytes: int
    declared_sha256: str
    reserved_by: str
    created_by_ref: str

    @property
    def binding_id(self) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            "dalgoro-dbi:h14:sql-scientific-raster-binding:v1:"
            + "|".join((
                self.tenant_ref, self.organization_ref,
                str(self.farm_id), str(self.plot_id), str(self.campaign_id),
                self.role, self.index_ref,
            )),
        )


def _canonical(intent: object) -> ScientificRasterBindingIntent:
    if not isinstance(intent, ScientificRasterBindingIntent):
        raise ScientificRasterBindingConflict("Intención científica inválida.")
    refs = (
        intent.tenant_ref, intent.organization_ref,
        intent.reserved_by, intent.created_by_ref,
    )
    if any(
        not isinstance(ref, str) or not (1 <= len(ref) <= 128)
        or ref.strip() != ref or "*" in ref
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in ref)
        for ref in refs
    ):
        raise ScientificRasterBindingConflict("Referencias SQL no canónicas.")
    if any(
        not isinstance(uuid, UUID)
        for uuid in (
            intent.farm_id, intent.plot_id, intent.campaign_id,
            intent.manifest_object_id, intent.slot_object_id,
            intent.target_object_id,
        )
    ) or len({intent.manifest_object_id, intent.slot_object_id, intent.target_object_id}) != 3:
        raise ScientificRasterBindingConflict("Identidades de objetos contradictorias.")
    if not (
        (intent.role == "rgb" and intent.index_ref == "_")
        or (
            intent.role == "scientific_cog"
            and intent.index_ref in {
                "ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green",
            }
        )
    ):
        raise ScientificRasterBindingConflict("Rol raster no pertenece a los siete.")
    if (
        not isinstance(intent.declared_size_bytes, int)
        or isinstance(intent.declared_size_bytes, bool)
        or not (0 < intent.declared_size_bytes <= 10 * 1024**3)
    ):
        raise ScientificRasterBindingConflict("Cuota raster no válida.")
    hashes = (intent.manifest_sha256, intent.slot_sha256, intent.declared_sha256)
    if any(
        not isinstance(digest, str) or len(digest) != 64
        or any(x not in "0123456789abcdef" for x in digest)
        for digest in hashes
    ):
        raise ScientificRasterBindingConflict("SHA-256 declarado no canónico.")
    return intent


def _same(row: DBIScientificRasterBinding, intent: ScientificRasterBindingIntent) -> bool:
    return all((
        row.id == intent.binding_id,
        row.tenant_ref == intent.tenant_ref,
        row.organization_ref == intent.organization_ref,
        row.farm_id == intent.farm_id,
        row.plot_id == intent.plot_id,
        row.campaign_id == intent.campaign_id,
        row.analysis_type == "multispectral",
        row.manifest_object_id == intent.manifest_object_id,
        row.manifest_sha256 == intent.manifest_sha256,
        row.slot_object_id == intent.slot_object_id,
        row.slot_sha256 == intent.slot_sha256,
        row.role == intent.role,
        row.index_ref == intent.index_ref,
        row.target_object_id == intent.target_object_id,
        row.declared_size_bytes == intent.declared_size_bytes,
        row.declared_sha256 == intent.declared_sha256,
        row.reserved_by == intent.reserved_by,
        row.created_by_ref == intent.created_by_ref,
        row.asset_id is None,
        row.status == "reserved_no_asset",
    ))


class DBIScientificRasterBindingRepository:
    """No commit/rollback: la API es dueña de la misma transacción Campaign."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise ScientificRasterBindingConflict("Requiere Session SQL transaccional.")
        self._session = session

    def persist_binding(
        self, intent: ScientificRasterBindingIntent,
    ) -> tuple[DBIScientificRasterBinding, bool]:
        value = _canonical(intent)
        inserted = self._session.execute(
            pg_insert(DBIScientificRasterBinding).values(
                id=value.binding_id,
                tenant_ref=value.tenant_ref,
                organization_ref=value.organization_ref,
                farm_id=value.farm_id,
                plot_id=value.plot_id,
                campaign_id=value.campaign_id,
                analysis_type="multispectral",
                manifest_object_id=value.manifest_object_id,
                manifest_sha256=value.manifest_sha256,
                slot_object_id=value.slot_object_id,
                slot_sha256=value.slot_sha256,
                role=value.role,
                index_ref=value.index_ref,
                target_object_id=value.target_object_id,
                declared_size_bytes=value.declared_size_bytes,
                declared_sha256=value.declared_sha256,
                reserved_by=value.reserved_by,
                created_by_ref=value.created_by_ref,
                status="reserved_no_asset",
                asset_id=None,
            ).on_conflict_do_nothing().returning(DBIScientificRasterBinding.id)
        ).scalar_one_or_none()
        row = self._session.execute(
            select(DBIScientificRasterBinding).where(
                DBIScientificRasterBinding.tenant_ref == value.tenant_ref,
                DBIScientificRasterBinding.campaign_id == value.campaign_id,
                DBIScientificRasterBinding.role == value.role,
                DBIScientificRasterBinding.index_ref == value.index_ref,
            ).with_for_update()
        ).scalar_one_or_none()
        if row is None or not _same(row, value):
            raise ScientificRasterBindingConflict("Registro científico existente divergente.")
        return row, inserted is not None
