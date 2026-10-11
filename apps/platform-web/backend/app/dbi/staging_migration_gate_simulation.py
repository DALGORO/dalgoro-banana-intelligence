"""Cruce E2/E3 y huellas de evidencias: simulación OFFLINE, sin permisos de apply.

No crea conexiones, no adquiere locks y no autentica documentos externos.
Los hashes coincidentes de archivos controlados por un operador no son firmas.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Sequence

from app.dbi import staging_migration_change_review as change_review
from app.dbi.staging_migration_verify import AUDITOR_ROLE

AUDIT_FIELDS = frozenset({
    "operation", "environment", "database", "role",
    "code_head_revision", "database_revision", "is_at_head",
    "postgis_available", "dbi_schema_available",
    "migration_apply", "deployment_readiness",
})
EVIDENCE_ARGUMENTS = (
    ("backup_manifest_sha256", "backup_manifest"),
    ("restore_test_report_sha256", "restore_report"),
    ("rollback_runbook_sha256", "rollback_runbook"),
    ("independent_approval_sha256", "approval_document"),
)
AUDIT_LIMIT = 8192
EVIDENCE_LIMIT = 262144


class StagingGateBlocked(ValueError):
    """El cruce documental falló y no puede autorizar ninguna escritura."""


def _safe_read(path: Path, max_size: int, seen: set[tuple[int, int]]) -> bytes:
    """Lee solo archivos regulares distintos, sin symlinks ni FIFO bloqueantes."""
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except OSError:
        raise StagingGateBlocked("file_unavailable") from None
    try:
        meta = os.fstat(fd)
        identity = (meta.st_dev, meta.st_ino)
        if (
            not stat.S_ISREG(meta.st_mode)
            or not 1 <= meta.st_size <= max_size
            or identity in seen
        ):
            raise StagingGateBlocked("file_invalid")
        content = os.read(fd, max_size + 1)
        if len(content) != meta.st_size:
            raise StagingGateBlocked("file_changed")
        seen.add(identity)
        return content
    finally:
        os.close(fd)


def _strict_json(raw: bytes) -> dict:
    def object_pairs(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise StagingGateBlocked("duplicate_json_key")
            result[name] = value
        return result

    try:
        result = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                StagingGateBlocked("json_constant_invalid")
            ),
        )
    except (UnicodeError, json.JSONDecodeError):
        raise StagingGateBlocked("json_invalid") from None
    if type(result) is not dict:
        raise StagingGateBlocked("json_object_required")
    return result


def simulate(
    *,
    packet_path: Path,
    audit_path: Path,
    backup_manifest: Path,
    restore_report: Path,
    rollback_runbook: Path,
    approval_document: Path,
) -> dict:
    """Sin red ni E/S DB: cruza informe E2, expediente E3 y cinco digests."""
    known, plan = change_review._plan()
    seen: set[tuple[int, int]] = set()
    packet = _strict_json(
        _safe_read(packet_path, change_review.MAX_PACKET_BYTES, seen)
    )
    review = change_review.review_packet(packet, known, plan)
    audit_raw = _safe_read(audit_path, AUDIT_LIMIT, seen)
    if sha256(audit_raw).hexdigest() != packet["readonly_verify_report_sha256"]:
        raise StagingGateBlocked("audit_digest_mismatch")
    audit = _strict_json(audit_raw)
    if set(audit) != AUDIT_FIELDS:
        raise StagingGateBlocked("audit_schema_invalid")
    expected = {
        "operation": "verify-staging-readonly",
        "environment": "staging",
        "database": "dbi_staging",
        "role": AUDITOR_ROLE,
        "code_head_revision": plan.head_revision,
        "database_revision": packet["current_revision"],
        "is_at_head": False,
        "postgis_available": True,
        "dbi_schema_available": True,
        "migration_apply": "BLOCKED",
        "deployment_readiness": "NOT_VERIFIED",
    }
    if any(type(audit[key]) is not type(value) or audit[key] != value
           for key, value in expected.items()):
        raise StagingGateBlocked("audit_scope_or_revision_invalid")

    files = {
        "backup_manifest": backup_manifest,
        "restore_report": restore_report,
        "rollback_runbook": rollback_runbook,
        "approval_document": approval_document,
    }
    for digest_field, argument in EVIDENCE_ARGUMENTS:
        contents = _safe_read(files[argument], EVIDENCE_LIMIT, seen)
        if sha256(contents).hexdigest() != packet[digest_field]:
            raise StagingGateBlocked("evidence_digest_mismatch")

    return {
        "operation": "simulate-staging-migration-gate",
        "environment": "staging",
        "database": "dbi_staging",
        "head_revision": plan.head_revision,
        "database_revision": packet["current_revision"],
        "plan_sha256": plan.fingerprint,
        "packet_sha256": review["packet_sha256"],
        "local_file_integrity": "MATCHED_UNTRUSTED_INPUTS",
        "matched_file_count": 6,
        "evidence_authenticity": "NOT_VERIFIED",
        "backup_restorability": "NOT_VERIFIED",
        "approval_authenticity": "NOT_VERIFIED",
        "audit_freshness": "NOT_VERIFIED",
        "advisory_lock": "NOT_ACQUIRED",
        "postflight": "NOT_EXECUTED",
        "authorization": "PENDING_INDEPENDENT_EXTERNAL_REVIEW",
        "migration_apply": "BLOCKED",
        "deployment_readiness": "NOT_VERIFIED",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dbi-staging-gate-simulation",
        description="Simular cruces documentales E2/E3 sin conexión ni escrituras.",
    )
    parser.add_argument("--simulate", action="store_true", required=True)
    for name in (
        "packet", "audit", "backup-manifest", "restore-report",
        "rollback-runbook", "approval-document",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = simulate(
            packet_path=args.packet,
            audit_path=args.audit,
            backup_manifest=args.backup_manifest,
            restore_report=args.restore_report,
            rollback_runbook=args.rollback_runbook,
            approval_document=args.approval_document,
        )
        status = 0
    except (StagingGateBlocked, change_review.PacketInvalid, OSError, ValueError):
        report = {
            "operation": "simulate-staging-migration-gate",
            "result": "BLOCKED",
            "migration_apply": "BLOCKED",
            "deployment_readiness": "NOT_VERIFIED",
        }
        status = 2
    except Exception:
        # Mensajes y rutas de proveedor/documentos nunca se exponen.
        report = {
            "operation": "simulate-staging-migration-gate",
            "result": "UNAVAILABLE",
            "migration_apply": "BLOCKED",
            "deployment_readiness": "NOT_VERIFIED",
        }
        status = 3
    print(json.dumps(report, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
