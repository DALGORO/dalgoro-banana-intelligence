"""Política pura de verificación criptográfica para activos DBI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import BinaryIO

from app.dbi.storage_contracts import DBIStorageObjectMetadata
from app.dbi.storage_policy import DBIStoragePolicy


class DBIAssetVerificationDecision(StrEnum):
    """Decisiones persistibles del proceso de verificación."""

    VERIFIED = "verified"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class DBIAssetVerificationResult:
    """Resultado no sensible de una lectura completa del objeto."""

    decision: DBIAssetVerificationDecision
    observed_size_bytes: int
    observed_sha256: str
    content_type_matches: bool

    @property
    def matches(self) -> bool:
        return self.decision is DBIAssetVerificationDecision.VERIFIED


def verify_asset_content(
    *,
    expected: DBIStorageObjectMetadata,
    observed_content_type: str,
    content: BinaryIO,
    chunk_size: int = 1024 * 1024,
) -> DBIAssetVerificationResult:
    """Lee el objeto completo y compara MIME, tamaño y SHA-256 declarados."""

    canonical = DBIStoragePolicy.validate_metadata(expected)
    if not isinstance(observed_content_type, str):
        raise TypeError("observed_content_type debe ser texto.")
    if not hasattr(content, "read"):
        raise TypeError("content debe implementar read().")
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size <= 0:
        raise ValueError("chunk_size debe ser un entero positivo.")

    digest = sha256()
    observed_size = 0
    while True:
        chunk = content.read(chunk_size)
        if chunk in (b"", None):
            break
        if not isinstance(chunk, bytes):
            raise TypeError("La lectura del objeto debe devolver bytes.")
        observed_size += len(chunk)
        digest.update(chunk)

    observed_sha = digest.hexdigest()
    mime_matches = observed_content_type == canonical.content_type
    matches = (
        mime_matches
        and observed_size == canonical.size_bytes
        and observed_sha == canonical.sha256
    )
    return DBIAssetVerificationResult(
        decision=(
            DBIAssetVerificationDecision.VERIFIED
            if matches
            else DBIAssetVerificationDecision.QUARANTINED
        ),
        observed_size_bytes=observed_size,
        observed_sha256=observed_sha,
        content_type_matches=mime_matches,
    )
