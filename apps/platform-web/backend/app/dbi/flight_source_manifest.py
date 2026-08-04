"""Contratos y servicio autorizado para manifiestos de fuentes de vuelo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Protocol, Sequence
from uuid import UUID

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)


SCHEMA_VERSION = "flight-source-bundle.v1"
MAX_MANIFEST_ENTRIES = 10_000
_CONTENT_TYPE = re.compile(r"^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DBIFlightSourceManifestError(ValueError):
    """El manifiesto no es canónico o diverge de la evidencia durable."""


class DBIFlightSourceManifestUnavailable(DBIFlightSourceManifestError):
    """El manifiesto o uno de sus activos no está disponible en el ámbito."""


@dataclass(frozen=True, slots=True)
class DBIFlightSourceEntryIntent:
    asset_id: UUID
    logical_name: str
    role: str
    sensor_camera: str | None = None
    captured_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DBIFlightSourceAssetSnapshot:
    asset_id: UUID
    tenant_ref: str
    farm_id: UUID
    plot_id: UUID | None
    asset_kind: str
    status: str
    content_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class DBIFlightSourceEntrySnapshot:
    asset_id: UUID
    ordinal: int
    role: str
    logical_name: str
    content_type: str
    size_bytes: int
    sha256: str
    sensor_camera: str | None
    captured_at: datetime | None


@dataclass(frozen=True, slots=True)
class DBIFlightSourceManifestRecord:
    bundle_id: UUID
    tenant_ref: str
    farm_id: UUID
    plot_id: UUID | None
    flight_ref: str
    master_asset_id: UUID
    schema_version: str
    manifest_sha256: str
    entry_count: int
    total_size_bytes: int
    created_by_ref: str
    created_at: datetime
    entries: tuple[DBIFlightSourceEntrySnapshot, ...]


@dataclass(frozen=True, slots=True)
class DBIFlightSourceManifestPage:
    manifest: DBIFlightSourceManifestRecord
    entries: tuple[DBIFlightSourceEntrySnapshot, ...]
    offset: int
    limit: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class DBIFlightSourcePersistedManifest:
    manifest: DBIFlightSourceManifestRecord
    created: bool


class DBIFlightSourceRepositoryPort(Protocol):
    def get_assets_for_manifest(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        asset_ids: frozenset[UUID],
    ) -> dict[UUID, DBIFlightSourceAssetSnapshot]: ...

    def persist_manifest(
        self, *, record: DBIFlightSourceManifestRecord
    ) -> DBIFlightSourcePersistedManifest: ...

    def get_manifest_page(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        master_asset_id: UUID,
        bundle_id: UUID,
        offset: int,
        limit: int,
    ) -> DBIFlightSourceManifestPage | None: ...


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, UUID):
        raise DBIFlightSourceManifestError(f"{name} debe ser UUID.")
    return value


def _ref(value: object, name: str, maximum: int = 128) -> str:
    if not isinstance(value, str):
        raise DBIFlightSourceManifestError(f"{name} debe ser texto.")
    if (
        not value
        or value != value.strip()
        or len(value) > maximum
        or "*" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise DBIFlightSourceManifestError(f"{name} no es canónico.")
    return value


def _logical_name(value: object) -> str:
    name = _ref(value, "logical_name", 512)
    if name.startswith("/") or "//" in name or any(
        part in {".", ".."} for part in name.split("/")
    ):
        raise DBIFlightSourceManifestError("logical_name no es seguro.")
    return name


def _utc(value: object, name: str, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIFlightSourceManifestError(f"{name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _canonical_json(record: dict[str, object]) -> bytes:
    return json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_flight_source_manifest_record(
    *,
    bundle_id: UUID,
    tenant_ref: str,
    farm_id: UUID,
    plot_id: UUID | None,
    flight_ref: str,
    master_asset_id: UUID,
    entries: Sequence[DBIFlightSourceEntryIntent],
    assets: dict[UUID, DBIFlightSourceAssetSnapshot],
    created_by_ref: str,
    created_at: datetime,
) -> DBIFlightSourceManifestRecord:
    """Construye un manifiesto determinista usando metadata durable, no binarios."""

    bundle = _uuid(bundle_id, "bundle_id")
    tenant = _ref(tenant_ref, "tenant_ref")
    farm = _uuid(farm_id, "farm_id")
    plot = None if plot_id is None else _uuid(plot_id, "plot_id")
    flight = _ref(flight_ref, "flight_ref")
    master_id = _uuid(master_asset_id, "master_asset_id")
    actor = _ref(created_by_ref, "created_by_ref")
    timestamp = _utc(created_at, "created_at")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise DBIFlightSourceManifestError("entries debe ser una secuencia.")
    if not 1 <= len(entries) <= MAX_MANIFEST_ENTRIES:
        raise DBIFlightSourceManifestError(
            "entries debe contener entre 1 y 10000 objetos."
        )

    master = assets.get(master_id)
    if (
        not isinstance(master, DBIFlightSourceAssetSnapshot)
        or master.tenant_ref != tenant
        or master.farm_id != farm
        or master.plot_id != plot
        or master.asset_kind != "orthophoto"
        or master.status not in {"registered", "verified"}
    ):
        raise DBIFlightSourceManifestUnavailable("ortofoto maestra no disponible.")

    normalized: list[
        tuple[DBIFlightSourceEntryIntent, DBIFlightSourceAssetSnapshot]
    ] = []
    seen_assets: set[UUID] = set()
    seen_names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, DBIFlightSourceEntryIntent):
            raise DBIFlightSourceManifestError("entrada de manifiesto inválida.")
        asset_id = _uuid(entry.asset_id, "asset_id")
        name = _logical_name(entry.logical_name)
        role = _ref(entry.role, "role", 24)
        if role not in {"source_photo", "auxiliary"}:
            raise DBIFlightSourceManifestError("role no está permitido.")
        sensor = (
            None
            if entry.sensor_camera is None
            else _ref(entry.sensor_camera, "sensor_camera", 160)
        )
        captured = _utc(entry.captured_at, "captured_at", optional=True)
        if asset_id in seen_assets or name in seen_names:
            raise DBIFlightSourceManifestError(
                "assets y nombres lógicos deben ser únicos."
            )
        seen_assets.add(asset_id)
        seen_names.add(name)
        asset = assets.get(asset_id)
        expected_kind = "flight_photo" if role == "source_photo" else "flight_auxiliary"
        if (
            not isinstance(asset, DBIFlightSourceAssetSnapshot)
            or asset.tenant_ref != tenant
            or asset.farm_id != farm
            or asset.plot_id != plot
            or asset.asset_kind != expected_kind
            or asset.status not in {"registered", "verified"}
            or not _CONTENT_TYPE.fullmatch(asset.content_type)
            or asset.size_bytes <= 0
            or not _SHA256.fullmatch(asset.sha256)
        ):
            raise DBIFlightSourceManifestUnavailable("fuente de vuelo no disponible.")
        normalized.append(
            (
                DBIFlightSourceEntryIntent(
                    asset_id=asset_id,
                    logical_name=name,
                    role=role,
                    sensor_camera=sensor,
                    captured_at=captured,
                ),
                asset,
            )
        )

    normalized.sort(key=lambda item: (item[0].logical_name, str(item[0].asset_id)))
    snapshots = tuple(
        DBIFlightSourceEntrySnapshot(
            asset_id=intent.asset_id,
            ordinal=ordinal,
            role=intent.role,
            logical_name=intent.logical_name,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            sha256=asset.sha256,
            sensor_camera=intent.sensor_camera,
            captured_at=intent.captured_at,
        )
        for ordinal, (intent, asset) in enumerate(normalized, start=1)
    )
    total_size = sum(entry.size_bytes for entry in snapshots)
    digest_body = {
        "bundle_id": str(bundle),
        "tenant_ref": tenant,
        "farm_id": str(farm),
        "plot_id": str(plot) if plot is not None else None,
        "flight_ref": flight,
        "master_asset_id": str(master_id),
        "schema_version": SCHEMA_VERSION,
        "entries": [
            {
                "asset_id": str(entry.asset_id),
                "ordinal": entry.ordinal,
                "role": entry.role,
                "logical_name": entry.logical_name,
                "content_type": entry.content_type,
                "size_bytes": entry.size_bytes,
                "sha256": entry.sha256,
                "sensor_camera": entry.sensor_camera,
                "captured_at": (
                    entry.captured_at.isoformat().replace("+00:00", "Z")
                    if entry.captured_at is not None
                    else None
                ),
            }
            for entry in snapshots
        ],
    }
    return DBIFlightSourceManifestRecord(
        bundle_id=bundle,
        tenant_ref=tenant,
        farm_id=farm,
        plot_id=plot,
        flight_ref=flight,
        master_asset_id=master_id,
        schema_version=SCHEMA_VERSION,
        manifest_sha256=sha256(_canonical_json(digest_body)).hexdigest(),
        entry_count=len(snapshots),
        total_size_bytes=total_size,
        created_by_ref=actor,
        created_at=timestamp,
        entries=snapshots,
    )


class DBIFlightSourceManifestService:
    """Autoriza, crea e inspecciona manifiestos sin abrir archivos de campo."""

    def __init__(self, repository: DBIFlightSourceRepositoryPort) -> None:
        for method in (
            "get_assets_for_manifest",
            "persist_manifest",
            "get_manifest_page",
        ):
            if not hasattr(repository, method):
                raise TypeError(f"repository no implementa {method}.")
        self._repository = repository

    @staticmethod
    def _authorize(
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        permission: DBIPermission,
    ) -> None:
        if not isinstance(context, DBIAccessContext):
            raise DBIAccessDenied()
        if plot_id is None:
            DBIAuthorizationPolicy.require_farm(
                context,
                tenant_ref=context.tenant_ref,
                organization_ref=organization_ref,
                farm_id=farm_id,
                permission=permission,
            )
        else:
            DBIAuthorizationPolicy.require_plot(
                context,
                tenant_ref=context.tenant_ref,
                organization_ref=organization_ref,
                farm_id=farm_id,
                plot_id=plot_id,
                permission=permission,
            )

    def create(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        master_asset_id: UUID,
        bundle_id: UUID,
        flight_ref: str,
        entries: Sequence[DBIFlightSourceEntryIntent],
        created_at: datetime,
    ) -> DBIFlightSourcePersistedManifest:
        self._authorize(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.WRITE,
        )
        asset_ids = frozenset({master_asset_id, *(entry.asset_id for entry in entries)})
        assets = self._repository.get_assets_for_manifest(
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            asset_ids=asset_ids,
        )
        if set(assets) != set(asset_ids):
            raise DBIFlightSourceManifestUnavailable(
                "activos de manifiesto no disponibles."
            )
        record = build_flight_source_manifest_record(
            bundle_id=bundle_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            flight_ref=flight_ref,
            master_asset_id=master_asset_id,
            entries=entries,
            assets=assets,
            created_by_ref=context.principal_ref,
            created_at=created_at,
        )
        persisted = self._repository.persist_manifest(record=record)
        if (
            not isinstance(persisted, DBIFlightSourcePersistedManifest)
            or persisted.manifest.manifest_sha256 != record.manifest_sha256
            or persisted.manifest.bundle_id != record.bundle_id
        ):
            raise DBIFlightSourceManifestError("resultado durable divergente.")
        return persisted

    def inspect(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID | None,
        master_asset_id: UUID,
        bundle_id: UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> DBIFlightSourceManifestPage:
        self._authorize(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.READ,
        )
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise DBIFlightSourceManifestError("offset inválido.")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 500
        ):
            raise DBIFlightSourceManifestError("limit debe estar entre 1 y 500.")
        page = self._repository.get_manifest_page(
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            master_asset_id=master_asset_id,
            bundle_id=bundle_id,
            offset=offset,
            limit=limit,
        )
        if page is None:
            raise DBIFlightSourceManifestUnavailable("manifiesto no disponible.")
        return page
