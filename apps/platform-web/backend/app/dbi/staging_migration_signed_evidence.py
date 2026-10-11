"""Verificación OFFLINE de firmas E5 sobre E2/E3; NUNCA autorización de apply.

La política y su huella deben ser administradas por un custodio independiente.
Sin confianza externa en esa política, un resultado de firmas es condicional.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.dbi import staging_migration_gate_simulation as gate

POLICY_SCHEMA = "dbi-staging-trust-policy.v1"
SIGNATURE_SCHEMA = "dbi-staging-attestation.v1"
PIN_ENV = "DBI_STAGING_TRUST_POLICY_SHA256"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{5,63}\Z")
POLICY_FIELDS = frozenset({"schema", "environment", "database", "keys"})
KEY_FIELDS = frozenset({"key_id", "principal_ref", "role", "public_key_b64"})
ATTEST_FIELDS = frozenset({
    "schema", "purpose", "signer_ref", "key_id", "environment",
    "database", "artifact_sha256", "head_revision", "current_revision",
    "plan_sha256", "change_ticket", "window_start_utc", "window_end_utc",
    "issued_at_utc", "expires_at_utc", "signature_b64",
})
PURPOSES = {
    "audit_report": ("staging_auditor", timedelta(minutes=15)),
    "change_approval": ("independent_approver", timedelta(hours=24)),
}


class SignaturesBlocked(ValueError):
    """Toda evidencia/identidad/tiempo no confiable se rechaza sin filtrar datos."""


def _base64(raw: object, length: int) -> bytes:
    if type(raw) is not str or len(raw) > 128:
        raise SignaturesBlocked("invalid_encoding")
    try:
        value = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        raise SignaturesBlocked("invalid_encoding") from None
    if len(value) != length:
        raise SignaturesBlocked("invalid_encoding")
    return value


def _valid_ref(value: object) -> bool:
    return type(value) is str and REF.fullmatch(value) is not None


def _canonical(data: dict) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _time(raw: object) -> datetime:
    try:
        return gate.change_review._utc_window(raw)
    except gate.change_review.PacketInvalid:
        raise SignaturesBlocked("invalid_time") from None


def _trusted_keys(path: Path, expected_pin: str, seen: set[tuple[int, int]]) -> dict:
    # El pin es externo a la política. No aceptar un pin dentro del propio JSON.
    if type(expected_pin) is not str or HEX64.fullmatch(expected_pin) is None:
        raise SignaturesBlocked("trust_policy_pin_required")
    try:
        metadata = path.lstat()
    except OSError:
        raise SignaturesBlocked("trust_policy_unavailable") from None
    if (not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o022
            or metadata.st_uid not in {0, os.getuid()}
            or metadata.st_nlink != 1):
        raise SignaturesBlocked("trust_policy_permissions")
    raw = gate._safe_read(path, 8192, seen)
    if sha256(raw).hexdigest() != expected_pin:
        raise SignaturesBlocked("trust_policy_pin_mismatch")
    data = gate._strict_json(raw)
    if (set(data) != POLICY_FIELDS
            or data["schema"] != POLICY_SCHEMA
            or data["environment"] != "staging"
            or data["database"] != "dbi_staging"
            or type(data["keys"]) is not list
            or len(data["keys"]) != 2):
        raise SignaturesBlocked("trust_policy_invalid")
    keys = {}
    principals = set()
    key_ids = set()
    public_bytes = set()
    for entry in data["keys"]:
        if (type(entry) is not dict or set(entry) != KEY_FIELDS
                or not _valid_ref(entry["key_id"])
                or not _valid_ref(entry["principal_ref"])
                or type(entry["role"]) is not str
                or entry["role"] not in {p[0] for p in PURPOSES.values()}
                or entry["role"] in keys
                or entry["principal_ref"] in principals
                or entry["key_id"] in key_ids):
            raise SignaturesBlocked("trust_key_invalid")
        raw_key = _base64(entry["public_key_b64"], 32)
        if raw_key in public_bytes:
            raise SignaturesBlocked("trust_key_reused")
        keys[entry["role"]] = entry["key_id"], entry["principal_ref"], raw_key
        principals.add(entry["principal_ref"])
        key_ids.add(entry["key_id"])
        public_bytes.add(raw_key)
    if len(keys) != 2:
        raise SignaturesBlocked("trust_roles_missing")
    return keys


def _verify_attestation(
    raw: bytes, purpose: str, trusted: tuple, packet: dict,
    artifact_sha: str, now: datetime,
) -> None:
    attestation = gate._strict_json(raw)
    if set(attestation) != ATTEST_FIELDS:
        raise SignaturesBlocked("attestation_schema_invalid")
    role, max_age = PURPOSES[purpose]
    key_id, principal, public_key = trusted
    exact = {
        "schema": SIGNATURE_SCHEMA,
        "purpose": purpose,
        "signer_ref": principal,
        "key_id": key_id,
        "environment": "staging",
        "database": "dbi_staging",
        "artifact_sha256": artifact_sha,
        "head_revision": packet["head_revision"],
        "current_revision": packet["current_revision"],
        "plan_sha256": packet["plan_sha256"],
        "change_ticket": packet["change_ticket"],
        "window_start_utc": packet["window_start_utc"],
        "window_end_utc": packet["window_end_utc"],
    }
    if any(type(attestation[k]) is not str or attestation[k] != v
           for k, v in exact.items()):
        raise SignaturesBlocked("attestation_binding_invalid")
    if purpose == "change_approval":
        if principal != packet["approver_ref"]:
            raise SignaturesBlocked("approver_mismatch")
    elif principal in {packet["operator_ref"], packet["approver_ref"]}:
        raise SignaturesBlocked("auditor_not_independent")

    issued = _time(attestation["issued_at_utc"])
    expires = _time(attestation["expires_at_utc"])
    if (issued > now or expires <= now or expires <= issued
            or now - issued > max_age or expires - issued > max_age
            or expires > _time(packet["window_end_utc"])):
        raise SignaturesBlocked("attestation_expired")
    signature = _base64(attestation["signature_b64"], 64)
    payload = {k: v for k, v in attestation.items() if k != "signature_b64"}
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, _canonical(payload),
        )
    except (InvalidSignature, ValueError):
        raise SignaturesBlocked("invalid_signature") from None


def verify_signed_evidence(
    *, packet: Path, audit: Path, backup_manifest: Path,
    restore_report: Path, rollback_runbook: Path, approval_document: Path,
    trust_policy: Path, audit_attestation: Path, approval_attestation: Path,
    expected_pin: str, now: datetime | None = None,
) -> dict:
    """Cruce E4 primero; luego verificar política anclada y dos firmas."""
    checkpoint = datetime.now(timezone.utc) if now is None else now
    if checkpoint.tzinfo is None:
        raise SignaturesBlocked("invalid_clock")
    if type(expected_pin) is not str or HEX64.fullmatch(expected_pin) is None:
        raise SignaturesBlocked("trust_policy_pin_required")
    e4 = gate.simulate(
        packet_path=packet, audit_path=audit,
        backup_manifest=backup_manifest, restore_report=restore_report,
        rollback_runbook=rollback_runbook, approval_document=approval_document,
    )
    seen: set[tuple[int, int]] = set()
    packet_raw = gate._safe_read(packet, gate.change_review.MAX_PACKET_BYTES, seen)
    packet_data = gate._strict_json(packet_raw)
    known, plan = gate.change_review._plan()
    review = gate.change_review.review_packet(packet_data, known, plan, now=checkpoint)
    if review["packet_sha256"] != e4["packet_sha256"]:
        raise SignaturesBlocked("packet_changed_since_crosscheck")
    audit_raw = gate._safe_read(audit, gate.AUDIT_LIMIT, seen)
    if sha256(audit_raw).hexdigest() != packet_data["readonly_verify_report_sha256"]:
        raise SignaturesBlocked("audit_changed_since_crosscheck")

    trusted = _trusted_keys(trust_policy, expected_pin, seen)
    auditor_raw = gate._safe_read(audit_attestation, 4096, seen)
    approver_raw = gate._safe_read(approval_attestation, 4096, seen)
    _verify_attestation(
        auditor_raw, "audit_report", trusted["staging_auditor"],
        packet_data, sha256(audit_raw).hexdigest(), checkpoint,
    )
    _verify_attestation(
        approver_raw, "change_approval", trusted["independent_approver"],
        packet_data, review["packet_sha256"], checkpoint,
    )
    return {
        "operation": "verify-staging-signed-evidence-offline",
        "environment": "staging",
        "database": "dbi_staging",
        "packet_sha256": review["packet_sha256"],
        "plan_sha256": plan.fingerprint,
        "signature_alg": "Ed25519",
        "verified_signature_count": 2,
        "signature_scope": "PINNED_POLICY_KEYS_ONLY",
        "trust_policy_pin": "MATCHED_UNVERIFIED_CUSTODY",
        "attested_artifacts": "AUDIT_REPORT_AND_CHANGE_PACKET",
        "evidence_authenticity": "OTHER_EVIDENCE_NOT_ATTESTED",
        "audit_freshness": "SIGNATURE_TIME_ONLY",
        "backup_restorability": "NOT_VERIFIED",
        "approval_authority": "NOT_EXTERNALLY_VERIFIED",
        "authorization": "PENDING_INDEPENDENT_EXTERNAL_REVIEW",
        "advisory_lock": "NOT_ACQUIRED",
        "postflight": "NOT_EXECUTED",
        "migration_apply": "BLOCKED",
        "deployment_readiness": "NOT_VERIFIED",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dbi-staging-signed-evidence",
        description="Verifica firmas Ed25519 offline; no habilita migraciones.",
    )
    parser.add_argument("--verify-signatures", action="store_true", required=True)
    for name in (
        "packet", "audit", "backup-manifest", "restore-report",
        "rollback-runbook", "approval-document", "trust-policy",
        "audit-attestation", "approval-attestation",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = verify_signed_evidence(
            packet=args.packet, audit=args.audit,
            backup_manifest=args.backup_manifest,
            restore_report=args.restore_report,
            rollback_runbook=args.rollback_runbook,
            approval_document=args.approval_document,
            trust_policy=args.trust_policy,
            audit_attestation=args.audit_attestation,
            approval_attestation=args.approval_attestation,
            expected_pin=os.environ.get(PIN_ENV, ""),
        )
        status = 0
    except (SignaturesBlocked, gate.StagingGateBlocked,
            gate.change_review.PacketInvalid, OSError, ValueError):
        report = {
            "operation": "verify-staging-signed-evidence-offline",
            "result": "BLOCKED", "migration_apply": "BLOCKED",
            "deployment_readiness": "NOT_VERIFIED",
        }
        status = 2
    except Exception:
        report = {
            "operation": "verify-staging-signed-evidence-offline",
            "result": "UNAVAILABLE", "migration_apply": "BLOCKED",
            "deployment_readiness": "NOT_VERIFIED",
        }
        status = 3
    print(json.dumps(report, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
