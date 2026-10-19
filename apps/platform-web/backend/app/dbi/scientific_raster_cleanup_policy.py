"""H14/2H-2D/3D: política pura de propuesta de limpieza, SIEMPRE sin permisos.

No existe un ejecutor en este módulo. Una huella SHA-256 identifica una lectura
puntual; no es firma, autorización, registro durable ni prueba de consistencia
transaccional entre PostgreSQL y S3.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID

from app.api.v1.dbi_scientific_raster_postapproval_audit import PostApprovalAuditReceipt

ProposedAction = Literal[
    "none_no_remote_uploads",
    "review_exact_recorded_upload",
    "investigate_unknown_remote_uploads",
    "investigate_missing_recorded_upload",
]


class CleanupPlanEvidenceConflict(ValueError):
    """La evidencia de lectura postaprobación no es internamente coherente."""


@dataclass(frozen=True, slots=True)
class CleanupEvidenceScope:
    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    campaign_id: UUID
    actor_ref: str
    manifest_sha256: str
    reservation_sha256: str


@dataclass(frozen=True, slots=True)
class CleanupDryRunDecision:
    action: ProposedAction
    evidence_sha256: str
    manual_review_required: bool
    candidate_exact_recorded_upload: bool
    incomplete_upload_count: int
    unexpected_upload_count: int


def build_cleanup_dry_run(
    audit: PostApprovalAuditReceipt, *, scope: CleanupEvidenceScope,
) -> CleanupDryRunDecision:
    if not isinstance(audit, PostApprovalAuditReceipt):
        raise CleanupPlanEvidenceConflict("Se exige auditoría interna verificada.")
    if not isinstance(scope, CleanupEvidenceScope):
        raise CleanupPlanEvidenceConflict("Falta el ámbito administrativo verificado.")
    if (
        any(not isinstance(x, UUID) for x in (
            scope.farm_id, scope.plot_id, scope.campaign_id,
        ))
        or audit.campaign_id != scope.campaign_id
        or any(
            not isinstance(x, str) or not (1 <= len(x) <= 128)
            or x.strip() != x
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in x)
            for x in (scope.tenant_ref, scope.organization_ref, scope.actor_ref)
        )
        or any(
            not isinstance(x, str) or len(x) != 64
            or any(ch not in "0123456789abcdef" for ch in x)
            for x in (scope.manifest_sha256, scope.reservation_sha256)
        )
    ):
        raise CleanupPlanEvidenceConflict("Huella o identidad de ámbito no canónica.")
    count, unexpected, present, sql = (
        audit.incomplete_upload_count, audit.unexpected_upload_count,
        audit.recorded_upload_present, audit.sql_start_recorded,
    )
    if (
        type(count) is not int or type(unexpected) is not int
        or not 0 <= unexpected <= count
        or type(present) is not bool or type(sql) is not bool
        or audit.campaign_status not in {"APPROVED", "PUBLISHED"}
        or any((audit.ready_for_upload, audit.grants_issued,
                audit.parts_received, audit.file_received, audit.content_verified,
                audit.asset_institutionally_approved, audit.asset_published,
                audit.cleanup_performed))
        or audit.remote_cleanup_required != (count > 0)
        or unexpected != count - int(present)
    ):
        raise CleanupPlanEvidenceConflict("Contadores o banderas incompatibles.")

    status = audit.reconciliation_status
    if status == "no_remote_no_sql":
        valid = count == 0 and not sql and not present
    elif status == "remote_orphan_without_sql":
        valid = count > 0 and not sql and not present
    elif status == "active_exact_single_upload":
        valid = count == 1 and sql and present and unexpected == 0
    elif status == "sql_active_remote_missing":
        valid = count == 0 and sql and not present
    elif status == "sql_active_remote_replaced":
        valid = count > 0 and sql and not present
    elif status == "sql_active_remote_extra":
        valid = count > 1 and sql and present and unexpected > 0
    elif status == "sql_aborted_no_remote":
        valid = count == 0 and sql and not present
    elif status == "sql_aborted_remote_remains":
        valid = count > 0 and sql
    else:
        valid = False
    if not valid:
        raise CleanupPlanEvidenceConflict("Estado S3/SQL incompatible con inventario.")

    # Safe planning is not authorization to abort: even one exact match requires
    # institutional approval and a separate durable audit/retention contract.
    if count == 0 and status in {"no_remote_no_sql", "sql_aborted_no_remote"}:
        action: ProposedAction = "none_no_remote_uploads"
    elif status == "active_exact_single_upload":
        action = "review_exact_recorded_upload"
    elif status == "sql_active_remote_missing":
        action = "investigate_missing_recorded_upload"
    else:
        action = "investigate_unknown_remote_uploads"

    expected_review = status not in {"no_remote_no_sql", "sql_aborted_no_remote"}
    if audit.manual_review_required != expected_review:
        raise CleanupPlanEvidenceConflict("Decisión de revisión institucional divergente.")

    evidence = {
        "schema_version": "dbi-h14-cleanup-evidence.v1",
        "scope": {
            "tenant_ref": scope.tenant_ref,
            "organization_ref": scope.organization_ref,
            "farm_id": str(scope.farm_id),
            "plot_id": str(scope.plot_id),
            "campaign_id": str(scope.campaign_id),
            "actor_ref": scope.actor_ref,
            "preparation_id": str(audit.preparation_id),
            "asset_id": str(audit.asset_id),
            "role": audit.role, "index": audit.index,
            "manifest_sha256": scope.manifest_sha256,
            "reservation_sha256": scope.reservation_sha256,
        },
        "campaign_status": audit.campaign_status,
        "reconciliation_status": status,
        "incomplete_upload_count": count,
        "unexpected_upload_count": unexpected,
        "recorded_upload_present": present,
        "sql_start_recorded": sql,
        "manual_review_required": audit.manual_review_required,
    }
    digest = sha256(
        b"dalgoro-dbi:h14:cleanup-evidence:v1\0"
        + json.dumps(
            evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return CleanupDryRunDecision(
        action=action,
        evidence_sha256=digest,
        manual_review_required=expected_review,
        candidate_exact_recorded_upload=(action == "review_exact_recorded_upload"),
        incomplete_upload_count=count,
        unexpected_upload_count=unexpected,
    )
