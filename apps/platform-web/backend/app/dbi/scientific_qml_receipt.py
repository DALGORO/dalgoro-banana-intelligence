"""H14: recepción privada *individual* de QML, sin expediente ni publicación.

Solo modela un objeto científico auxiliar pequeño y exacto. Los COG/RGB grandes
necesitan una fase multipartes con catálogo transaccional independiente.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dbi.storage_contracts import DBIStorageObjectMetadata, DBIStoragePurpose
from app.dbi.storage_policy import DBIStoragePolicy

QML_MAX_BYTES = 256 * 1024
_QML_NAMESPACE = UUID("18e0f39b-1b8f-4aec-b9d9-17818aa29b14")
ScientificIndex = Literal["ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"]


class ScientificQMLIntakeItem(BaseModel):
    """Declaración estricta: el servidor verifica bytes y hash posteriormente."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    index: ScientificIndex
    relative_path: str = Field(min_length=5, max_length=512)
    size_bytes: int = Field(strict=True, gt=0, le=QML_MAX_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("relative_path")
    @classmethod
    def require_safe_relative_path(cls, value: str) -> str:
        segments = value.split("/")
        if (
            len(segments) < 2
            or "\\" in value
            or not segments[-1].lower().endswith(".qml")
            or any(
                not part or part in {".", ".."}
                or any(ord(char) < 32 or ord(char) == 127 for char in part)
                for part in segments
            )
        ):
            raise ValueError("Ruta original QML inválida.")
        return value


@dataclass(frozen=True, slots=True)
class ScientificQMLPrivatePlan:
    item: ScientificQMLIntakeItem
    metadata: DBIStorageObjectMetadata


def plan_scientific_qml_private_receipt(
    *, tenant_ref: str, organization_ref: str,
    farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    item: ScientificQMLIntakeItem,
) -> ScientificQMLPrivatePlan:
    """Identidad inmutable por scope + contenido; un original distinto nunca reemplaza otro."""
    # Validar también tenant aunque no se muestre en la clave pública.
    DBIStoragePolicy.tenant_namespace(tenant_ref)
    if not isinstance(organization_ref, str) or not organization_ref or organization_ref.strip() != organization_ref:
        raise ValueError("Organización inválida.")
    identity = "\0".join((
        "dbi:h14:scientific-qml:v1", tenant_ref, organization_ref,
        str(farm_id), str(plot_id), str(campaign_id), item.index,
        item.relative_path, str(item.size_bytes), item.sha256,
    ))
    object_id = uuid5(_QML_NAMESPACE, identity)
    address = DBIStoragePolicy.build_address(
        tenant_ref=tenant_ref, purpose=DBIStoragePurpose.TECHNICAL_SOURCE,
        object_id=object_id,
    )
    metadata = DBIStoragePolicy.build_metadata(
        address=address, content_type="text/plain",
        size_bytes=item.size_bytes, sha256_hex=item.sha256,
    )
    return ScientificQMLPrivatePlan(item=item, metadata=metadata)


class ScientificQMLPrivateReceipt(BaseModel):
    """Recibo del *único* objeto, nunca del conjunto 13/13."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["dbi-h14-scientific-qml-private-receipt.v1"]
    disposition: Literal["private_qml_original_received_pending_review"]
    campaign_id: UUID
    index: ScientificIndex
    relative_path: str
    object_id: UUID
    size_bytes: int
    sha256: str
    created: bool
    transport_hash_verified: Literal[True]
    bundle_complete: Literal[False]
    scientific_validated: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]
