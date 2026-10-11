"""E4: prueba sin red de integridad local del paquete y del informe staging."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))
sys.path.insert(0, str(ROOT / ".github" / "scripts"))

from app.dbi import staging_migration_gate_simulation as gate  # noqa: E402
from ci_dbi_staging_migration_change_review import data  # noqa: E402


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def args(paths):
    return [
        "--simulate", "--packet", str(paths["packet"]),
        "--audit", str(paths["audit"]),
        "--backup-manifest", str(paths["backup_manifest"]),
        "--restore-report", str(paths["restore_report"]),
        "--rollback-runbook", str(paths["rollback_runbook"]),
        "--approval-document", str(paths["approval_document"]),
    ]


def call(paths):
    output = StringIO()
    with redirect_stdout(output):
        code = gate.main(args(paths))
    text = output.getvalue()
    assert text.count("\n") == 1
    for secret in ("SENSITIVE_PASSWORD", "private-bucket", "localhost",
                   "operator_ci01", "approver_ci01", "CHG_ci_001"):
        assert secret not in text
    return code, json.loads(text)


def blocked(paths):
    code, result = call(paths)
    assert code == 2 and result["result"] == "BLOCKED", result
    assert result["migration_apply"] == "BLOCKED"


def run():
    _, plan = gate.change_review._plan()
    packet = data(plan)
    audit = {
        "operation": "verify-staging-readonly",
        "environment": "staging",
        "database": "dbi_staging",
        "role": gate.AUDITOR_ROLE,
        "code_head_revision": plan.head_revision,
        "database_revision": packet["current_revision"],
        "is_at_head": False,
        "postgis_available": True,
        "dbi_schema_available": True,
        "migration_apply": "BLOCKED",
        "deployment_readiness": "NOT_VERIFIED",
    }
    with TemporaryDirectory(prefix="dbi-e4-offline-") as folder:
        root = Path(folder)
        paths = {field: root / (field + ".json") for field in (
            "packet", "audit", "backup_manifest", "restore_report",
            "rollback_runbook", "approval_document",
        )}
        evidence = {
            "backup_manifest": b"private-bucket backup manifest reference (unverified)",
            "restore_report": b"staging restore claim (unverified)",
            "rollback_runbook": b"rollback document (unverified)",
            "approval_document": b"operator_ci01 approver_ci01 (unverified)",
        }

        def write_all():
            paths["audit"].write_bytes(encode(audit))
            packet["readonly_verify_report_sha256"] = sha256(
                paths["audit"].read_bytes()
            ).hexdigest()
            for field, attr in gate.EVIDENCE_ARGUMENTS:
                paths[attr].write_bytes(evidence[attr])
                packet[field] = sha256(evidence[attr]).hexdigest()
            paths["packet"].write_bytes(encode(packet))

        write_all()
        with patch.object(socket, "socket", side_effect=AssertionError("NETWORK FORBIDDEN")):
            status, report = call(paths)
            assert status == 0 and report["matched_file_count"] == 6
            assert report["local_file_integrity"] == "MATCHED_UNTRUSTED_INPUTS"
            assert report["migration_apply"] == "BLOCKED"
            assert report["authorization"] == "PENDING_INDEPENDENT_EXTERNAL_REVIEW"
            assert report["evidence_authenticity"] == "NOT_VERIFIED"
            assert report["backup_restorability"] == "NOT_VERIFIED"
            assert report["approval_authenticity"] == "NOT_VERIFIED"
            assert report["audit_freshness"] == "NOT_VERIFIED"
            assert report["advisory_lock"] == "NOT_ACQUIRED"
            assert report["postflight"] == "NOT_EXECUTED"
            assert report["deployment_readiness"] == "NOT_VERIFIED"

            # Cambios de estado, rol y revisión se rechazan incluso si el hash
            # del reporte fue actualizado para coincidir con el expediente.
            for changes in (
                {"environment": "production"},
                {"database": "dbi_production"},
                {"role": "dbi_staging_migrator"},
                {"code_head_revision": "dbi_0025_gpkg_layer_options"},
                {"database_revision": "dbi_0024_gis_approval"},
                {"is_at_head": True},
                {"postgis_available": False},
                {"dbi_schema_available": False},
                {"migration_apply": "READY"},
                {"deployment_readiness": "READY"},
                {"extra_secret": "SENSITIVE_PASSWORD"},
            ):
                baseline = dict(audit)
                audit.update(changes)
                write_all()
                blocked(paths)
                audit.clear()
                audit.update(baseline)
                write_all()
            for attr in evidence:
                baseline = evidence[attr]
                paths[attr].write_bytes(baseline + b" tampered")
                blocked(paths)
                paths[attr].write_bytes(baseline)

            # Auditar E2 puede ser falsificado: sin firmas no hay autorización.
            fake = dict(audit)
            fake["database_revision"] = packet["current_revision"]
            paths["audit"].write_bytes(encode(fake) + b"\n")
            blocked(paths)  # El hash previo deja de coincidir
            write_all()

            # E3 sigue validando HEAD, ventana y separación de responsables.
            base_packet = dict(packet)
            for update in (
                {"environment": "production"},
                {"head_revision": "dbi_0025_gpkg_layer_options"},
                {"approver_ref": packet["operator_ref"]},
                {"current_revision": plan.head_revision},
                {"window_start_utc": "2000-01-01T00:00:00Z"},
            ):
                packet.update(update)
                paths["packet"].write_bytes(encode(packet))
                blocked(paths)
                packet.clear()
                packet.update(base_packet)
                paths["packet"].write_bytes(encode(packet))
            future = datetime.now(timezone.utc) + timedelta(days=32)
            packet["window_start_utc"] = future.strftime("%Y-%m-%dT%H:%M:%SZ")
            paths["packet"].write_bytes(encode(packet))
            blocked(paths)
            packet.clear()
            packet.update(base_packet)
            paths["packet"].write_bytes(encode(packet))

            # Archivos temporales maliciosos: no seguir symlinks, FIFOs,
            # dos paths al mismo inodo ni leer documentos gigantes.
            temp = root / "backup_orig"
            paths["backup_manifest"].rename(temp)
            paths["backup_manifest"].symlink_to(temp)
            blocked(paths)
            paths["backup_manifest"].unlink()
            temp.rename(paths["backup_manifest"])

            paths["restore_report"].write_bytes(b"x" * (gate.EVIDENCE_LIMIT + 1))
            blocked(paths)
            paths["restore_report"].write_bytes(evidence["restore_report"])

            # JSON ambiguo, secreto extra y archivos duplicados bloqueados.
            paths["audit"].write_bytes(
                b'{"operation":"x","operation":"y"}'
            )
            blocked(paths)
            write_all()
            paths["packet"].write_bytes(b'{"schema":"x","schema":"y"}')
            blocked(paths)
            write_all()

            original = paths["approval_document"]
            saved = root / "approval_original"
            original.rename(saved)
            original.hardlink_to(paths["restore_report"])
            blocked(paths)
            original.unlink()
            saved.rename(original)

            with redirect_stderr(StringIO()):
                try:
                    gate.main(["--simulate", "--apply"])
                except SystemExit as error:
                    assert error.code == 2
                else:
                    raise AssertionError("El CLI no puede ofrecer --apply")
            assert call(paths)[0] == 0

    print("E4: cruce E2/E3 offline y SHA reales, sin red, firmas ni apply OK.")


if __name__ == "__main__":
    run()
