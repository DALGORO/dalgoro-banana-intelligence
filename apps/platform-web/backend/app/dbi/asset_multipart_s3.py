"""Adaptador multipartes S3-compatible no productivo y sin persistencia."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from secrets import token_urlsafe
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlencode, urlparse

from botocore.exceptions import BotoCoreError, ClientError

from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm,
)
from app.dbi.asset_multipart_provider import (
    DBIMultipartProviderAbortConfirmation,
    DBIMultipartProviderAbortRequest,
    DBIMultipartProviderCompletion,
    DBIMultipartProviderCompleteRequest,
    DBIMultipartProviderConflict,
    DBIMultipartProviderDenied,
    DBIMultipartProviderError,
    DBIMultipartProviderInitiateRequest,
    DBIMultipartProviderIntegrityError,
    DBIMultipartProviderNotFound,
    DBIMultipartProviderPartGrant,
    DBIMultipartProviderPartGrantRequest,
    DBIMultipartProviderPolicy,
    DBIMultipartProviderUpload,
)
from app.dbi.storage_s3 import DBIS3ObjectStoreConfig, build_s3_client


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_GRANT_REF_RE = re.compile(r"^[A-Za-z0-9._~-]{16,256}$")
_META_SHA256 = "dbi-sha256"
_META_SIZE = "dbi-size"
_META_PURPOSE = "dbi-purpose"
_META_OBJECT_ID = "dbi-object-id"
_TAG_STATE = "dbi-state"
_ABORT_DISCOVERY_PAGE_SIZE = 100
_MAX_ABORT_DISCOVERY_PAGES = 10


_CHECKSUM_MEMBERS = {
    DBIMultipartChecksumAlgorithm.SHA256: (
        "ChecksumSHA256",
        "x-amz-checksum-sha256",
    ),
    DBIMultipartChecksumAlgorithm.CRC32: (
        "ChecksumCRC32",
        "x-amz-checksum-crc32",
    ),
    DBIMultipartChecksumAlgorithm.CRC32C: (
        "ChecksumCRC32C",
        "x-amz-checksum-crc32c",
    ),
    DBIMultipartChecksumAlgorithm.CRC64NVME: (
        "ChecksumCRC64NVME",
        "x-amz-checksum-crc64nvme",
    ),
}


@dataclass(frozen=True, slots=True)
class DBIS3ResolvedMultipartPartAccess:
    """Material efímero; URL, cabeceras y grant quedan fuera de repr."""

    grant: DBIMultipartProviderPartGrant = field(repr=False)
    method: str
    url: str = field(repr=False)
    headers: tuple[tuple[str, str], ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class _StoredPartAccess:
    access: DBIS3ResolvedMultipartPartAccess


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _opaque_grant_ref() -> str:
    return token_urlsafe(32)


def _client_error_code(error: ClientError) -> str:
    response = error.response if isinstance(error.response, dict) else {}
    details = response.get("Error", {})
    return str(details.get("Code", ""))


def _translate_client_error(error: ClientError) -> DBIMultipartProviderError:
    code = _client_error_code(error).casefold()
    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if status == 404 or code in {
        "404",
        "nosuchkey",
        "nosuchupload",
        "notfound",
    }:
        return DBIMultipartProviderNotFound()
    if status == 403 or code in {"403", "accessdenied", "invalidaccesskeyid"}:
        return DBIMultipartProviderDenied()
    if status in {409, 412} or code in {
        "409",
        "412",
        "conflict",
        "preconditionfailed",
        "conditionalrequestconflict",
    }:
        return DBIMultipartProviderConflict(
            "el proveedor detectó una operación multipartes concurrente."
        )
    if code == "baddigest":
        return DBIMultipartProviderIntegrityError(
            "el proveedor rechazó el checksum multipartes."
        )
    return DBIMultipartProviderError(
        "el proveedor S3 rechazó la operación multipartes privada."
    )


def _object_metadata(request: DBIMultipartProviderInitiateRequest) -> dict[str, str]:
    metadata = request.metadata
    return {
        _META_SHA256: metadata.sha256,
        _META_SIZE: str(metadata.size_bytes),
        _META_PURPOSE: metadata.address.purpose.value,
        _META_OBJECT_ID: str(metadata.address.object_id),
    }


def _active_tagging() -> str:
    return urlencode({_TAG_STATE: "active"})


def _opaque_provider_value(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise DBIMultipartProviderIntegrityError(
            f"{field_name} del proveedor no es canónico."
        )
    return value


def _confirms_composite_shape(value: str, *, part_count: int) -> bool:
    payload, separator, count = value.rpartition("-")
    return (
        separator == "-"
        and count == str(part_count)
        and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", payload) is not None
    )


class DBIS3MultipartAdapter:
    """Mapea el puerto a S3 usando solo endpoint loopback y cliente inyectable."""

    def __init__(
        self,
        config: DBIS3ObjectStoreConfig,
        *,
        client: Any | None = None,
        clock: Callable[[], datetime] = _utc_now,
        grant_ref_factory: Callable[[], str] = _opaque_grant_ref,
    ) -> None:
        if not isinstance(config, DBIS3ObjectStoreConfig):
            raise TypeError("config debe ser DBIS3ObjectStoreConfig.")
        hostname = urlparse(config.endpoint_url).hostname
        if hostname not in _LOOPBACK_HOSTS:
            raise ValueError(
                "el adaptador multipartes no productivo exige endpoint loopback."
            )
        if not callable(clock) or not callable(grant_ref_factory):
            raise TypeError("clock y grant_ref_factory deben ser invocables.")
        self._config = config
        self._client = client if client is not None else build_s3_client(config)
        self._clock = clock
        self._grant_ref_factory = grant_ref_factory
        self._grants: dict[str, _StoredPartAccess] = {}
        self._grant_lock = RLock()

    def _call(self, operation: str, /, **kwargs: Any) -> Any:
        method = getattr(self._client, operation, None)
        if not callable(method):
            raise DBIMultipartProviderError(
                "el cliente S3 no implementa la operación requerida."
            )
        try:
            return method(**kwargs)
        except ClientError as error:
            raise _translate_client_error(error) from None
        except BotoCoreError:
            raise DBIMultipartProviderError(
                "no se pudo completar la operación multipartes S3."
            ) from None

    def initiate(
        self,
        request: DBIMultipartProviderInitiateRequest,
    ) -> DBIMultipartProviderUpload:
        canonical = DBIMultipartProviderPolicy.validate_initiate_request(request)
        response = self._call(
            "create_multipart_upload",
            Bucket=self._config.bucket,
            Key=canonical.metadata.address.object_key,
            ContentType=canonical.metadata.content_type,
            Metadata=_object_metadata(canonical),
            Tagging=_active_tagging(),
            ChecksumAlgorithm=canonical.plan.checksum_algorithm.value,
            ChecksumType=canonical.plan.checksum_type.value,
        )
        upload_ref = DBIMultipartProviderPolicy.provider_ref(
            response.get("UploadId")
        )
        return DBIMultipartProviderUpload(
            provider_upload_ref=upload_ref,
            session_id=canonical.session_id,
            metadata=canonical.metadata,
            plan=canonical.plan,
            initiated_at=canonical.initiated_at,
        )

    def issue_part_access(
        self,
        request: DBIMultipartProviderPartGrantRequest,
    ) -> DBIMultipartProviderPartGrant:
        canonical = DBIMultipartProviderPolicy.validate_part_grant_request(request)
        upload = canonical.upload
        checksum_member, checksum_header = _CHECKSUM_MEMBERS[
            upload.plan.checksum_algorithm
        ]
        params = {
            "Bucket": self._config.bucket,
            "Key": upload.metadata.address.object_key,
            "UploadId": upload.provider_upload_ref,
            "PartNumber": canonical.part_number,
            "ContentLength": canonical.size_bytes,
            checksum_member: canonical.checksum,
        }
        ttl_seconds = int(
            (canonical.expires_at - canonical.issued_at).total_seconds()
        )
        try:
            url = self._client.generate_presigned_url(
                "upload_part",
                Params=params,
                ExpiresIn=ttl_seconds,
                HttpMethod="PUT",
            )
        except (ClientError, BotoCoreError):
            raise DBIMultipartProviderError(
                "no se pudo emitir acceso temporal para la parte."
            ) from None
        if not isinstance(url, str) or not url:
            raise DBIMultipartProviderIntegrityError(
                "el proveedor no devolvió acceso temporal válido."
            )
        grant_ref = self._grant_ref_factory()
        if not isinstance(grant_ref, str) or not _GRANT_REF_RE.fullmatch(grant_ref):
            raise DBIMultipartProviderIntegrityError(
                "grant_ref no es canónico."
            )
        grant = DBIMultipartProviderPartGrant(
            grant_ref=grant_ref,
            session_id=upload.session_id,
            part_number=canonical.part_number,
            size_bytes=canonical.size_bytes,
            checksum_algorithm=upload.plan.checksum_algorithm,
            issued_at=canonical.issued_at,
            expires_at=canonical.expires_at,
        )
        access = DBIS3ResolvedMultipartPartAccess(
            grant=grant,
            method="PUT",
            url=url,
            headers=tuple(
                sorted(
                    {
                        "content-length": str(canonical.size_bytes),
                        checksum_header: canonical.checksum,
                    }.items()
                )
            ),
        )
        with self._grant_lock:
            self._grants[grant_ref] = _StoredPartAccess(access=access)
        return grant

    def resolve_part_access(
        self,
        grant_ref: str,
        *,
        now: datetime | None = None,
    ) -> DBIS3ResolvedMultipartPartAccess:
        if not isinstance(grant_ref, str) or not _GRANT_REF_RE.fullmatch(grant_ref):
            raise DBIMultipartProviderNotFound()
        timestamp = DBIMultipartProviderPolicy.utc(
            self._clock() if now is None else now,
            field_name="now",
        )
        with self._grant_lock:
            stored = self._grants.get(grant_ref)
            if stored is None:
                raise DBIMultipartProviderNotFound()
            if timestamp >= stored.access.grant.expires_at:
                self._grants.pop(grant_ref, None)
                raise DBIMultipartProviderNotFound()
            return stored.access

    def _inspect_completed(
        self,
        upload: DBIMultipartProviderUpload,
        *,
        created: bool,
    ) -> DBIMultipartProviderCompletion:
        canonical = DBIMultipartProviderPolicy.validate_upload(upload)
        checksum_member, _checksum_header = _CHECKSUM_MEMBERS[
            canonical.plan.checksum_algorithm
        ]
        head = self._call(
            "head_object",
            Bucket=self._config.bucket,
            Key=canonical.metadata.address.object_key,
            ChecksumMode="ENABLED",
        )
        raw_metadata = head.get("Metadata", {})
        expected_metadata = _object_metadata(
            DBIMultipartProviderInitiateRequest(
                session_id=canonical.session_id,
                metadata=canonical.metadata,
                plan=canonical.plan,
                initiated_at=canonical.initiated_at,
            )
        )
        if (
            head.get("ContentLength") != canonical.metadata.size_bytes
            or head.get("ContentType") != canonical.metadata.content_type
            or raw_metadata != expected_metadata
        ):
            raise DBIMultipartProviderIntegrityError(
                "el objeto completado no coincide con la metadata DBI."
            )
        checksum = _opaque_provider_value(
            head.get(checksum_member),
            field_name=checksum_member,
        )
        reported_checksum_type = head.get("ChecksumType")
        expected_checksum_type = canonical.plan.checksum_type.value
        checksum_type_confirmed = (
            reported_checksum_type == expected_checksum_type
            if reported_checksum_type is not None
            else expected_checksum_type == "COMPOSITE"
            and _confirms_composite_shape(
                checksum,
                part_count=canonical.plan.part_count,
            )
        )
        if not checksum_type_confirmed:
            raise DBIMultipartProviderIntegrityError(
                "el proveedor no confirmó el tipo de checksum multipartes."
            )
        etag = _opaque_provider_value(head.get("ETag"), field_name="ETag")
        completed_at = DBIMultipartProviderPolicy.utc(
            head.get("LastModified"),
            field_name="LastModified",
        )
        return DBIMultipartProviderCompletion(
            session_id=canonical.session_id,
            metadata=canonical.metadata,
            checksum_algorithm=canonical.plan.checksum_algorithm,
            checksum_type=canonical.plan.checksum_type,
            transport_checksum=checksum,
            etag=etag,
            completed_at=completed_at,
            created=created,
        )

    def inspect_completed(
        self,
        upload: DBIMultipartProviderUpload,
    ) -> DBIMultipartProviderCompletion:
        return self._inspect_completed(upload, created=False)

    def complete(
        self,
        request: DBIMultipartProviderCompleteRequest,
    ) -> DBIMultipartProviderCompletion:
        canonical = DBIMultipartProviderPolicy.validate_complete_request(request)
        upload = canonical.upload
        checksum_member, _checksum_header = _CHECKSUM_MEMBERS[
            upload.plan.checksum_algorithm
        ]
        parts = [
            {
                "ETag": f'"{part.etag}"',
                "PartNumber": part.part_number,
                checksum_member: part.checksum,
            }
            for part in canonical.parts
        ]
        params: dict[str, Any] = {
            "Bucket": self._config.bucket,
            "Key": upload.metadata.address.object_key,
            "UploadId": upload.provider_upload_ref,
            "MultipartUpload": {"Parts": parts},
            "ChecksumType": upload.plan.checksum_type.value,
            "MpuObjectSize": upload.plan.size_bytes,
            "IfNoneMatch": "*",
        }
        if canonical.full_object_checksum is not None:
            params[checksum_member] = canonical.full_object_checksum
        try:
            self._call("complete_multipart_upload", **params)
        except DBIMultipartProviderNotFound:
            return self._inspect_completed(upload, created=False)
        return self._inspect_completed(upload, created=True)

    def _list_exact_upload_refs(self, object_key: str) -> tuple[str, ...]:
        key_marker: str | None = None
        upload_marker: str | None = None
        references: list[str] = []
        for _page in range(_MAX_ABORT_DISCOVERY_PAGES):
            params: dict[str, Any] = {
                "Bucket": self._config.bucket,
                "Prefix": object_key,
                "MaxUploads": _ABORT_DISCOVERY_PAGE_SIZE,
            }
            if key_marker is not None:
                params["KeyMarker"] = key_marker
            if upload_marker is not None:
                params["UploadIdMarker"] = upload_marker
            response = self._call("list_multipart_uploads", **params)
            uploads = response.get("Uploads", [])
            if not isinstance(uploads, list):
                raise DBIMultipartProviderIntegrityError(
                    "el proveedor devolvió una lista de cargas inválida."
                )
            for upload in uploads:
                if not isinstance(upload, dict) or upload.get("Key") != object_key:
                    continue
                references.append(
                    DBIMultipartProviderPolicy.provider_ref(upload.get("UploadId"))
                )
            if not response.get("IsTruncated", False):
                return tuple(references)
            key_marker = response.get("NextKeyMarker")
            upload_marker = response.get("NextUploadIdMarker")
            if not isinstance(key_marker, str) or not isinstance(upload_marker, str):
                raise DBIMultipartProviderIntegrityError(
                    "la paginación de cargas del proveedor es inválida."
                )
        raise DBIMultipartProviderConflict(
            "la limpieza superó el lote máximo de cargas remotas."
        )

    def _abort_ref(self, *, object_key: str, upload_ref: str) -> bool:
        try:
            self._call(
                "abort_multipart_upload",
                Bucket=self._config.bucket,
                Key=object_key,
                UploadId=upload_ref,
            )
        except DBIMultipartProviderNotFound:
            return False
        return True

    def _bound_abort_confirmed(self, *, object_key: str, upload_ref: str) -> bool:
        try:
            self._call(
                "list_parts",
                Bucket=self._config.bucket,
                Key=object_key,
                UploadId=upload_ref,
                MaxParts=1,
            )
        except DBIMultipartProviderNotFound:
            return True
        return False

    def _ensure_no_completed_object(
        self,
        request: DBIMultipartProviderAbortRequest,
    ) -> None:
        if request.provider_upload_ref is None:
            raise DBIMultipartProviderIntegrityError(
                "la inspección completada requiere referencia remota."
            )
        upload = DBIMultipartProviderUpload(
            provider_upload_ref=request.provider_upload_ref,
            session_id=request.session_id,
            metadata=request.metadata,
            plan=request.plan,
            initiated_at=request.initiated_at,
        )
        try:
            self._inspect_completed(upload, created=False)
        except DBIMultipartProviderNotFound:
            return
        raise DBIMultipartProviderConflict(
            "el objeto ya fue completado y no admite aborto."
        )

    def abort(
        self,
        request: DBIMultipartProviderAbortRequest,
    ) -> DBIMultipartProviderAbortConfirmation:
        """Aborta solo cargas incompletas; nunca elimina el objeto completado."""

        canonical = DBIMultipartProviderPolicy.validate_abort_request(request)
        object_key = canonical.metadata.address.object_key
        aborted_count = 0
        if canonical.provider_upload_ref is not None:
            remote_changed = self._abort_ref(
                object_key=object_key,
                upload_ref=canonical.provider_upload_ref,
            )
            if remote_changed:
                aborted_count = 1
            else:
                self._ensure_no_completed_object(canonical)
            cleanup_confirmed = self._bound_abort_confirmed(
                object_key=object_key,
                upload_ref=canonical.provider_upload_ref,
            )
        else:
            references = self._list_exact_upload_refs(object_key)
            for reference in references:
                if self._abort_ref(object_key=object_key, upload_ref=reference):
                    aborted_count += 1
            cleanup_confirmed = not self._list_exact_upload_refs(object_key)

        if cleanup_confirmed:
            with self._grant_lock:
                stale_grants = tuple(
                    grant_ref
                    for grant_ref, stored in self._grants.items()
                    if stored.access.grant.session_id == canonical.session_id
                )
                for grant_ref in stale_grants:
                    self._grants.pop(grant_ref, None)

        confirmation = DBIMultipartProviderAbortConfirmation(
            session_id=canonical.session_id,
            aborted_at=canonical.requested_at,
            provider_uploads_aborted=aborted_count,
            cleanup_confirmed=cleanup_confirmed,
        )
        return DBIMultipartProviderPolicy.validate_abort_confirmation(confirmation)
