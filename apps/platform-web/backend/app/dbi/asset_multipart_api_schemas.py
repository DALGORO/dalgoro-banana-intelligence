"""Esquemas HTTP no sensibles para coordinar cargas multipartes DBI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm,
    DBIMultipartChecksumType,
    DBIMultipartRoutingDecision,
    DBIMultipartSessionState,
)


class _MultipartAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _canonical_organization_ref(value: object) -> object:
    if not isinstance(value, str):
        return value
    if (
        value != value.strip()
        or "*" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("organization_ref debe ser canónica.")
    return value


class DBIMultipartScopeRequest(_MultipartAPIModel):
    organization_ref: str = Field(min_length=1, max_length=128)
    farm_id: UUID
    plot_id: UUID | None = None

    @field_validator("organization_ref", mode="before")
    @classmethod
    def require_canonical_organization(cls, value: object) -> object:
        return _canonical_organization_ref(value)


class DBIMultipartInitiateRequest(DBIMultipartScopeRequest):
    idempotency_key: str = Field(
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9._~-]+$",
        repr=False,
    )
    checksum_algorithm: DBIMultipartChecksumAlgorithm = (
        DBIMultipartChecksumAlgorithm.SHA256
    )
    checksum_type: DBIMultipartChecksumType = (
        DBIMultipartChecksumType.COMPOSITE
    )


class DBIMultipartPartAuthorizationRequest(_MultipartAPIModel):
    part_number: int = Field(ge=1, le=10_000)
    checksum: str = Field(min_length=1, max_length=128, repr=False)


class DBIMultipartGrantPartsRequest(DBIMultipartScopeRequest):
    parts: list[DBIMultipartPartAuthorizationRequest] = Field(
        min_length=1,
        max_length=64,
    )


class DBIMultipartRecordPartRequest(DBIMultipartScopeRequest):
    part_number: int = Field(ge=1, le=10_000)
    size_bytes: int = Field(gt=0)
    checksum: str = Field(min_length=1, max_length=128, repr=False)
    etag: str = Field(min_length=1, max_length=256, repr=False)


class DBIMultipartCompleteRequest(DBIMultipartScopeRequest):
    full_object_checksum: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        repr=False,
    )


class DBIMultipartInspectRequest(DBIMultipartScopeRequest):
    pass


class DBIMultipartAbortRequest(DBIMultipartScopeRequest):
    pass


class DBIMultipartSessionResponse(_MultipartAPIModel):
    session_id: UUID
    asset_id: UUID
    state: DBIMultipartSessionState
    reason_code: str | None
    size_bytes: int
    part_size_bytes: int | None
    part_count: int | None
    max_grants_per_window: int | None
    max_client_concurrency: int | None
    checksum_algorithm: DBIMultipartChecksumAlgorithm
    checksum_type: DBIMultipartChecksumType
    version: int
    expires_at: datetime | None
    last_activity_at: datetime
    completed_at: datetime | None
    aborted_at: datetime | None
    expired_at: datetime | None


class DBIMultipartInitiateResponse(_MultipartAPIModel):
    decision: DBIMultipartRoutingDecision
    created: bool
    provider_started: bool
    session: DBIMultipartSessionResponse | None


class DBIMultipartPartAccessResponse(_MultipartAPIModel):
    part_number: int
    size_bytes: int
    method: Literal["PUT"]
    url: str = Field(min_length=1, repr=False)
    headers: dict[str, str] = Field(default_factory=dict, repr=False)
    expires_at: datetime


class DBIMultipartGrantPartsResponse(_MultipartAPIModel):
    session_id: UUID
    state: Literal[DBIMultipartSessionState.UPLOADING]
    max_client_concurrency: int
    grants: list[DBIMultipartPartAccessResponse] = Field(repr=False)


class DBIMultipartRecordPartResponse(_MultipartAPIModel):
    session_id: UUID
    state: Literal[DBIMultipartSessionState.UPLOADING]
    part_number: int
    created: bool
    recorded_part_count: int
    expected_part_count: int


class DBIMultipartCompleteResponse(_MultipartAPIModel):
    session_id: UUID
    state: Literal[
        DBIMultipartSessionState.COMPLETED_PENDING_CONTENT_VERIFICATION
    ]
    changed: bool
    transport_integrity: Literal["confirmed"]
    content_verification: Literal["pending"]
    completed_at: datetime


class DBIMultipartInspectResponse(_MultipartAPIModel):
    session: DBIMultipartSessionResponse
    recorded_part_count: int


class DBIMultipartAbortResponse(_MultipartAPIModel):
    session_id: UUID
    state: Literal[DBIMultipartSessionState.ABORTED]
    changed: bool
    cleanup_confirmed: Literal[True]
    aborted_at: datetime
