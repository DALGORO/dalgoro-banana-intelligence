"""Contratos inmutables para objetos privados DBI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import BinaryIO, Callable, ContextManager, Protocol
from uuid import UUID


class DBIStoragePurpose(StrEnum):
    """Namespaces funcionales admitidos por la frontera de objetos."""

    ANALYSIS_INPUT = "analysis-inputs"
    ANALYSIS_ARTIFACT = "analysis-artifacts"
    MODEL_ARTIFACT = "model-artifacts"
    TECHNICAL_SOURCE = "technical-sources"


class DBIStorageAccessMode(StrEnum):
    """Operaciones temporales explícitas; no existe modo público."""

    READ = "read"
    WRITE = "write"


class DBIStorageObjectState(StrEnum):
    """Estados lógicos del objeto dentro del puerto privado."""

    ACTIVE = "active"
    RETIRED = "retired"


class DBIStorageError(RuntimeError):
    """Error base normalizado de la frontera de almacenamiento."""


class DBIStorageDenied(DBIStorageError):
    """La operación no pertenece al namespace solicitado."""


class DBIStorageConflict(DBIStorageError):
    """La clave existe con identidad o contenido divergente."""


class DBIStorageNotFound(DBIStorageError):
    """El objeto no está disponible dentro del namespace solicitado."""


class DBIStorageIntegrityError(DBIStorageError):
    """El contenido no coincide con tamaño, MIME o huella declarados."""


@dataclass(frozen=True, slots=True)
class DBIStorageAddress:
    """Dirección canónica derivada; nunca contiene URL o ruta local."""

    tenant_ref: str
    purpose: DBIStoragePurpose
    object_id: UUID
    object_key: str


@dataclass(frozen=True, slots=True)
class DBIStorageObjectMetadata:
    """Identidad verificable de un objeto privado."""

    address: DBIStorageAddress
    content_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class DBIStorageWriteRequest:
    """Solicitud de escritura inmutable, independiente del transporte."""

    metadata: DBIStorageObjectMetadata


@dataclass(frozen=True, slots=True)
class DBIStorageObjectRecord:
    """Estado observable del objeto sin URL, secreto o contenido."""

    metadata: DBIStorageObjectMetadata
    state: DBIStorageObjectState
    created_at: datetime
    retired_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DBIStorageWriteResult:
    """Resultado de creación o reintento exacto."""

    record: DBIStorageObjectRecord
    created: bool


@dataclass(frozen=True, slots=True)
class DBIStorageTemporaryGrant:
    """Autorización efímera vinculada a metadatos verificables completos."""

    grant_ref: str = field(repr=False)
    metadata: DBIStorageObjectMetadata
    mode: DBIStorageAccessMode
    issued_at: datetime
    expires_at: datetime

    @property
    def address(self) -> DBIStorageAddress:
        """Expone la dirección canónica sin duplicar autoridad."""

        return self.metadata.address


class DBIPrivateObjectStore(Protocol):
    """Puerto proveedor-neutral para objetos privados DBI."""

    def put(
        self,
        request: DBIStorageWriteRequest,
        content: BinaryIO,
    ) -> DBIStorageWriteResult: ...

    def stat(self, address: DBIStorageAddress) -> DBIStorageObjectRecord: ...

    def open_read(
        self,
        address: DBIStorageAddress,
    ) -> ContextManager[BinaryIO]: ...

    def copy_to(
        self,
        address: DBIStorageAddress,
        destination: BinaryIO,
        *,
        progress: Callable[[int], None] | None = None,
    ) -> DBIStorageObjectRecord:
        """Copia un objeto activo por streaming y verifica tamaño + SHA-256."""

        ...

    def retire(
        self,
        address: DBIStorageAddress,
        *,
        retired_at: datetime,
    ) -> bool: ...

    def issue_temporary_access(
        self,
        metadata: DBIStorageObjectMetadata,
        *,
        mode: DBIStorageAccessMode,
        issued_at: datetime,
        expires_at: datetime,
    ) -> DBIStorageTemporaryGrant: ...
