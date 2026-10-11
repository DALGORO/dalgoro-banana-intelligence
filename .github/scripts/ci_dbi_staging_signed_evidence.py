"""E5: firmas Ed25519 sintéticas, política anclada y rechazo sin network/apply."""
from __future__ import annotations

import base64
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))
sys.path.insert(0, str(ROOT / ".github" / "scripts"))

from app.dbi import staging_migration_signed_evidence as signed  # noqa: E402
from ci_dbi_staging_migration_change_review import data  # noqa: E402


def jbytes(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def timestamp(t):
    return t.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def b64(data):
    return base64.b64encode(data).decode("ascii")


def arguments(paths):
    args = ["--verify-signatures"]
    for opt in ("packet", "audit", "backup_manifest", "restore_report",
                "rollback_runbook", "approval_document", "trust_policy",
                "audit_attestation", "approval_attestation"):
        args += ["--" + opt.replace("_", "-"), str(paths[opt])]
    return args


def run_cli(paths, pin):
    sink = StringIO()
    with patch.dict(os.environ, {signed.PIN_ENV: pin}, clear=True):
        with redirect_stdout(sink):
            code = signed.main(arguments(paths))
    out = sink.getvalue()
    assert out.count("\n") == 1
    for forbidden in ("audit_ci01", "approver_ci01", "operator_ci01",
                      "CHG_ci_001", "private-bucket", "s3-secret", "127.0.0.1"):
        assert forbidden not in out, forbidden
    return code, json.loads(out)


def blocked(paths, pin):
    code, report = run_cli(paths, pin)
    assert code == 2 and report["result"] == "BLOCKED", report
    assert report["migration_apply"] == "BLOCKED"


def run():
    _, plan = signed.gate.change_review._plan()
    packet = data(plan)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    audit = {
        "operation": "verify-staging-readonly",
        "environment": "staging", "database": "dbi_staging",
        "role": signed.gate.AUDITOR_ROLE,
        "code_head_revision": plan.head_revision,
        "database_revision": packet["current_revision"],
        "is_at_head": False,
        "postgis_available": True,
        "dbi_schema_available": True,
        "migration_apply": "BLOCKED", "deployment_readiness": "NOT_VERIFIED",
    }
    auditor_private = Ed25519PrivateKey.generate()
    reviewer_private = Ed25519PrivateKey.generate()
    secrets = {
        "audit_report": auditor_private,
        "change_approval": reviewer_private,
    }
    policy = {
        "schema": signed.POLICY_SCHEMA,
        "environment": "staging", "database": "dbi_staging",
        "keys": [
            {
                "key_id": "audit_key01",
                "principal_ref": "audit_ci01",
                "role": "staging_auditor",
                "public_key_b64": b64(auditor_private.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw,
                )),
            },
            {
                "key_id": "review_key01",
                "principal_ref": "approver_ci01",
                "role": "independent_approver",
                "public_key_b64": b64(reviewer_private.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw,
                )),
            },
        ],
    }
    with TemporaryDirectory(prefix="dbi-e5-signed-") as folder:
        root = Path(folder)
        paths = {name: root / (name + ".json") for name in (
            "packet", "audit", "backup_manifest", "restore_report",
            "rollback_runbook", "approval_document", "trust_policy",
            "audit_attestation", "approval_attestation",
        )}
        evidence = {
            "backup_manifest": b"private-bucket synthetic backup bytes",
            "restore_report": b"synthetic restore report",
            "rollback_runbook": b"synthetic rollback document",
            "approval_document": b"approver_ci01 synthetic review",
        }
        paths["audit"].write_bytes(jbytes(audit))
        packet["readonly_verify_report_sha256"] = sha256(
            paths["audit"].read_bytes()
        ).hexdigest()
        for field, attr in signed.gate.EVIDENCE_ARGUMENTS:
            paths[attr].write_bytes(evidence[attr])
            packet[field] = sha256(evidence[attr]).hexdigest()
        paths["packet"].write_bytes(jbytes(packet))
        paths["trust_policy"].write_bytes(jbytes(policy))
        paths["trust_policy"].chmod(0o600)
        pin = sha256(paths["trust_policy"].read_bytes()).hexdigest()
        canonical_packet_sha = signed.gate.change_review.review_packet(
            packet, *signed.gate.change_review._plan(),
        )["packet_sha256"]

        def attestation(purpose, issued=None, expires=None):
            is_audit = purpose == "audit_report"
            issued = now - timedelta(minutes=1) if issued is None else issued
            expires = now + timedelta(minutes=9 if is_audit else 59) if expires is None else expires
            body = {
                "schema": signed.SIGNATURE_SCHEMA,
                "purpose": purpose,
                "signer_ref": "audit_ci01" if is_audit else "approver_ci01",
                "key_id": "audit_key01" if is_audit else "review_key01",
                "environment": "staging",
                "database": "dbi_staging",
                "artifact_sha256": (
                    packet["readonly_verify_report_sha256"] if is_audit
                    else canonical_packet_sha
                ),
                "head_revision": packet["head_revision"],
                "current_revision": packet["current_revision"],
                "plan_sha256": packet["plan_sha256"],
                "change_ticket": packet["change_ticket"],
                "window_start_utc": packet["window_start_utc"],
                "window_end_utc": packet["window_end_utc"],
                "issued_at_utc": timestamp(issued),
                "expires_at_utc": timestamp(expires),
            }
            body["signature_b64"] = b64(secrets[purpose].sign(
                signed._canonical(body)
            ))
            return body

        def save_attest(a=None, b=None):
            paths["audit_attestation"].write_bytes(jbytes(
                attestation("audit_report") if a is None else a
            ))
            paths["approval_attestation"].write_bytes(jbytes(
                attestation("change_approval") if b is None else b
            ))

        save_attest()
        with patch.object(socket, "socket", side_effect=AssertionError("NETWORK FORBIDDEN")):
            code, output = run_cli(paths, pin)
            assert code == 0, output
            assert output["verified_signature_count"] == 2
            assert output["signature_alg"] == "Ed25519"
            assert output["signature_scope"] == "PINNED_POLICY_KEYS_ONLY"
            assert output["trust_policy_pin"] == "MATCHED_UNVERIFIED_CUSTODY"
            assert output["approval_authority"] == "NOT_EXTERNALLY_VERIFIED"
            assert output["audit_freshness"] == "SIGNATURE_TIME_ONLY"
            assert output["authorization"] == "PENDING_INDEPENDENT_EXTERNAL_REVIEW"
            assert output["migration_apply"] == "BLOCKED"
            assert output["deployment_readiness"] == "NOT_VERIFIED"

            # No pin o pin diferente => no confiar en claves aportadas.
            blocked(paths, "")
            blocked(paths, "0" * 64)
            # Modificaciones sin firma Ed25519 válida.
            for target in ("audit_attestation", "approval_attestation"):
                original = paths[target].read_bytes()
                obj = json.loads(original)
                for key, value in (
                    ("change_ticket", "CHG_forged_01"),
                    ("artifact_sha256", "f" * 64),
                    ("head_revision", "dbi_0025_gpkg_layer_options"),
                    ("environment", "production"),
                    ("signer_ref", "forged_ci01"),
                    ("signature_b64", b64(b"x" * 64)),
                    ("signature_b64", "***invalid***"),
                ):
                    item = {**obj, key: value}
                    paths[target].write_bytes(jbytes(item))
                    blocked(paths, pin)
                paths[target].write_bytes(original)

            # Incluso con firma criptográfica correcta, no se tolera expiración,
            # fecha futura, ni una firma fuera de la ventana fijada.
            for purpose, name in (
                ("audit_report", "audit_attestation"),
                ("change_approval", "approval_attestation"),
            ):
                original = paths[name].read_bytes()
                for issued, expires in (
                    (now - timedelta(days=2), now - timedelta(days=1)),
                    (now + timedelta(minutes=5), now + timedelta(minutes=8)),
                    (now - timedelta(days=2), now + timedelta(minutes=5)),
                    (now - timedelta(minutes=1), now + timedelta(days=2)),
                ):
                    paths[name].write_bytes(jbytes(attestation(
                        purpose, issued=issued, expires=expires,
                    )))
                    blocked(paths, pin)
                paths[name].write_bytes(original)

            # Clave errónea y rol no independizado, aun con política repineada.
            original_policy = paths["trust_policy"].read_bytes()
            for replacement in (
                {**policy, "environment": "production"},
                {**policy, "keys": [policy["keys"][0], policy["keys"][0]]},
                {**policy, "keys": [policy["keys"][0], {
                    **policy["keys"][1],
                    "public_key_b64": policy["keys"][0]["public_key_b64"],
                }]},
                {**policy, "keys": [policy["keys"][0], {
                    **policy["keys"][1],
                    "principal_ref": "audit_ci01",
                }]},
                {**policy, "keys": [policy["keys"][0], {
                    **policy["keys"][1],
                    "public_key_b64": b64(
                        Ed25519PrivateKey.generate().public_key().public_bytes(
                            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
                        )
                    ),
                }]},
            ):
                paths["trust_policy"].write_bytes(jbytes(replacement))
                changed_pin = sha256(paths["trust_policy"].read_bytes()).hexdigest()
                blocked(paths, changed_pin)
            paths["trust_policy"].write_bytes(original_policy)

            paths["trust_policy"].chmod(0o666)
            blocked(paths, pin)
            paths["trust_policy"].chmod(0o600)

            # Si E4 falla (digest de restauración cambiado), la firma no basta.
            paths["restore_report"].write_bytes(b"tampered restore")
            blocked(paths, pin)
            paths["restore_report"].write_bytes(evidence["restore_report"])

            original = paths["audit_attestation"].read_bytes()
            renamed = root / "attestation_original"
            paths["audit_attestation"].rename(renamed)
            paths["audit_attestation"].symlink_to(renamed)
            blocked(paths, pin)
            paths["audit_attestation"].unlink()
            renamed.rename(paths["audit_attestation"])

            # No existe modo apply ni opción de firmar con clave privada.
            from contextlib import redirect_stderr
            with redirect_stderr(StringIO()):
                try:
                    signed.main(["--apply"])
                except SystemExit as e:
                    assert e.code == 2
                else:
                    raise AssertionError("--apply no debe existir")
            assert run_cli(paths, pin)[0] == 0

    print("E5: firmas Ed25519 independientes y pin externo; sin red ni apply OK.")


if __name__ == "__main__":
    run()
