"""Plan puro e idempotente para registrar activos de entrada DBI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.dbi.storage_contracts import DBIStorageConflict, DBIStorageObjectMetadata, DBIStoragePurpose
from app.dbi.storage_policy import DBIStoragePolicy


class DBIAssetRegistrationConflict(ValueError):
    """La identidad del activo ya existe con una declaración divergente."""


class DBIAssetRegistrationAction(str, Enum):
    CREATE = "create"
    REUSE = "reuse"


@dataclass(frozen=True, slots=True)
class DBIAssetRegistrationIntent:
    asset_id: UUID
    tenant_ref: str
    farm_id: UUID
    plot_id: UUID | None
    asset_kind: str
    content_type: str
    size_bytes: int
    sha256: str
    crs: str | None
    created_by_ref: str


@dataclass(frozen=True, slots=True)
class DBIAssetRegistrationSnapshot:
    asset_id: UUID
    tenant_ref: str
    farm_id: UUID
    plot_id: UUID | None
    asset_kind: str
    status: str
    object_key: str
    content_type: str
    size_bytes: int
    sha256: str
    crs: str | None
    created_by_ref: str


@dataclass(frozen=True, slots=True)
class DBIAssetRegistrationPlan:
    action: DBIAssetRegistrationAction
    metadata: DBIStorageObjectMetadata
    asset_id: UUID
    tenant_ref: str
    farm_id: UUID
    plot_id: UUID | None
    asset_kind: str
    status: str
    crs: str | None
    created_by_ref: str

    @property
    def created(self) -> bool:
        return self.action is DBIAssetRegistrationAction.CREATE


_ALLOWED_ASSET_KINDS = frozenset({"orthophoto", "boundary", "exclusions"})
_ALLOWED_EXISTING_STATUSES = frozenset({"registered", "verified", "quarantined", "retired"})


def _required_uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise DBIAssetRegistrationConflict(f"{field_name} debe ser UUID.")
    return value


def _required_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise DBIAssetRegistrationConflict(f"{field_name} debe ser texto.")
    normalized = value.strip()
    if not normalized or normalized != value or len(normalized) > 128:
        raise DBIAssetRegistrationConflict(f"{field_name} no es canónico.")
    return normalized


def _canonical_crs(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DBIAssetRegistrationConflict("crs debe ser texto o null.")
    if not value or value != value.strip() or len(value) > 80:
        raise DBIAssetRegistrationConflict("crs no es canónico.")
    return value


def _validated_intent(intent: object) -> tuple[DBIAssetRegistrationIntent, DBIStorageObjectMetadata]:
    if not isinstance(intent, DBIAssetRegistrationIntent):
        raise DBIAssetRegistrationConflict("intent debe ser DBIAssetRegistrationIntent.")
    asset_id = _required_uuid(intent.asset_id, field_name="asset_id")
    tenant_ref = _required_ref(intent.tenant_ref, field_name="tenant_ref")
    _required_uuid(intent.farm_id, field_name="farm_id")
    if intent.plot_id is not None:
        _required_uuid(intent.plot_id, field_name="plot_id")
    if intent.asset_kind not in _ALLOWED_ASSET_KINDS:
        raise DBIAssetRegistrationConflict("asset_kind no está permitido.")
    _required_ref(intent.created_by_ref, field_name="created_by_ref")
    crs = _canonical_crs(intent.crs)
    try:
        address = DBIStoragePolicy.build_address(
            tenant_ref=tenant_ref,
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=asset_id,
        )
        metadata = DBIStoragePolicy.build_metadata(
            address=address,
            content_type=intent.content_type,
            size_bytes=intent.size_bytes,
            sha256_hex=intent.sha256,
        )
    except DBIStorageConflict as error:
        raise DBIAssetRegistrationConflict(str(error)) from error
    if crs != intent.crs:
        raise DBIAssetRegistrationConflict("crs no es canónico.")
    return intent, metadata


def build_asset_registration_plan(
    *,
    intent: DBIAssetRegistrationIntent,
    existing: DBIAssetRegistrationSnapshot | None,
) -> DBIAssetRegistrationPlan:
    """Decide crear o reutilizar un activo sin sesión, red ni efectos laterales."""

    canonical, metadata = _validated_intent(intent)
    expected = DBIAssetRegistrationPlan(
        action=DBIAssetRegistrationAction.CREATE,
        metadata=metadata,
        asset_id=canonical.asset_id,
        tenant_ref=canonical.tenant_ref,
        farm_id=canonical.farm_id,
        plot_id=canonical.plot_id,
        asset_kind=canonical.asset_kind,
        status="registered",
        crs=canonical.crs,
        created_by_ref=canonical.created_by_ref,
    )
    if existing is None:
        return expected
    if not isinstance(existing, DBIAssetRegistrationSnapshot):
        raise DBIAssetRegistrationConflict("existing debe ser snapshot o null.")
    if existing.status not in _ALLOWED_EXISTING_STATUSES:
        raise DBIAssetRegistrationConflict("El estado existente no es válido.")

    exact_match = (
        existing.asset_id == expected.asset_id
        and existing.tenant_ref == expected.tenant_ref
        and existing.farm_id == expected.farm_id
        and existing.plot_id == expected.plot_id
        and existing.asset_kind == expected.asset_kind
        and existing.object_key == expected.metadata.address.object_key
        and existing.content_type == expected.metadata.content_type
        and existing.size_bytes == expected.metadata.size_bytes
        and existing.sha256 == expected.metadata.sha256
        and existing.crs == expected.crs
        and existing.created_by_ref == expected.created_by_ref
    )
    if not exact_match:
        raise DBIAssetRegistrationConflict(
            "El asset_id existente no coincide con la declaración idempotente."
        )
    return DBIAssetRegistrationPlan(
        action=DBIAssetRegistrationAction.REUSE,
        metadata=expected.metadata,
        asset_id=expected.asset_id,
        tenant_ref=expected.tenant_ref,
        farm_id=expected.farm_id,
        plot_id=expected.plot_id,
        asset_kind=expected.asset_kind,
        status=existing.status,
        crs=expected.crs,
        created_by_ref=expected.created_by_ref,
    )
