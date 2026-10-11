"""Contrato del expediente staging: huellas y referencias, JAMÁS permiso de apply."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.dbi import staging_migration_change_review as gate  # noqa: E402
from app.dbi import migration_cli  # noqa: E402


def data(plan):
    start = datetime.now(timezone.utc) + timedelta(days=2)
    start = start.replace(microsecond=0)
    stop = start + timedelta(minutes=45)
    return {
        "schema": gate.SCHEMA,
        "environment": "staging",
        "database": "dbi_staging",
        "current_revision": "dbi_0025_gpkg_layer_options",
        "head_revision": plan.head_revision,
        "plan_sha256": plan.fingerprint,
        "change_ticket": "CHG_ci_001",
        "operator_ref": "operator_ci01",
        "approver_ref": "approver_ci01",
        "window_start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_end_utc": stop.strftime("%Y-%m-%dT%H:%M:%SZ"),
        **{field: format(i + 1, "064x") for i, field in enumerate(gate.EVIDENCE_FIELDS)},
    }


def output(argv):
    sink = StringIO()
    with redirect_stdout(sink):
        result = gate.main(argv)
    text = sink.getvalue()
    assert text.count("\n") == 1
    for secret in ("operator_ci01", "approver_ci01", "CHG_ci_001",
                   "postgresql+psycopg://", "s3-secret", "/tmp/"):
        assert secret not in text, secret
    return result, json.loads(text)


def rejected(packet, known, plan):
    try:
        gate.review_packet(packet, known, plan)
    except gate.PacketInvalid:
        return
    raise AssertionError("El expediente de migración debía bloquearse")


def run():
    with patch.object(socket, "socket", side_effect=AssertionError("NO SOCKET")):
        known, plan = gate._plan()
        code, meta = output(["--plan"])
        assert code == 0
        assert meta["head_revision"] == plan.head_revision
        assert meta["plan_sha256"] == plan.fingerprint
        assert meta["migration_apply"] == "BLOCKED"
        assert meta["deployment_readiness"] == "NOT_VERIFIED"

        packet = data(plan)
        result = gate.review_packet(packet, known, plan)
        assert result["packet_structure"] == "VALIDATED"
        assert result["authorization"] == "PENDING_INDEPENDENT_EXTERNAL_REVIEW"
        assert result["external_evidence"] == "REFERENCED_NOT_AUTHENTICATED"
        assert result["migration_apply"] == "BLOCKED"
        assert len(result["packet_sha256"]) == 64
        assert result["packet_sha256"] != plan.fingerprint

        with TemporaryDirectory(prefix="ci-dbi-review-") as folder:
            path = Path(folder) / "evidence.json"
            path.write_text(json.dumps(packet), encoding="utf-8")
            code, report = output(["--review-packet", str(path)])
            assert code == 0 and report["packet_sha256"] == result["packet_sha256"]
            assert report["migration_apply"] == "BLOCKED"

            path.write_text('{"schema": "x", "schema": "y"}', encoding="utf-8")
            code, report = output(["--review-packet", str(path)])
            assert code == 2 and report["result"] == "BLOCKED"
            path.write_text("x" * (gate.MAX_PACKET_BYTES + 1), encoding="utf-8")
            code, report = output(["--review-packet", str(path)])
            assert code == 2 and report["result"] == "BLOCKED"
            path.unlink()
            path.symlink_to(Path(folder) / "missing.json")
            code, report = output(["--review-packet", str(path)])
            assert code == 2 and report["result"] == "BLOCKED"
            path.unlink()
            code, report = output(["--review-packet", str(path)])
            assert code == 2 and report["result"] == "BLOCKED"

        invalid_cases = (
            {"environment": "production"},
            {"environment": "test"},
            {"database": "dbi_production"},
            {"head_revision": "dbi_0024_gis_approval"},
            {"plan_sha256": "f" * 64},
            {"current_revision": plan.head_revision},
            {"current_revision": "made_up_revision"},
            {"current_revision": None},
            {"approver_ref": packet["operator_ref"]},
            {"operator_ref": "short"},
            {"change_ticket": "secret://invalid"},
            {"backup_manifest_sha256": "g" * 64},
            {"restore_test_report_sha256": packet["backup_manifest_sha256"]},
            {"window_start_utc": "2000-01-01T00:00:00Z"},
            {"window_start_utc": "tomorrow"},
            {"window_start_utc": "2027-02-30T00:00:00Z"},
            {"window_end_utc": "2000-01-01T00:00:00Z"},
            {"window_end_utc": (
                datetime.now(timezone.utc) + timedelta(days=2, hours=4)
            ).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")},
            {"independent_approval_sha256": 123},
            {"schema": "not-review"},
        )
        for mutations in invalid_cases:
            rejected({**packet, **mutations}, known, plan)
        rejected({**packet, "EXTRA_SECRET": "s3-secret"}, known, plan)

        # Una ventana excesiva o a más de 30 días no cumple revisión.
        late = datetime.now(timezone.utc) + timedelta(days=31)
        rejected({**packet, "window_start_utc": late.strftime("%Y-%m-%dT%H:%M:%SZ")}, known, plan)
        overlong = (datetime.strptime(
            packet["window_start_utc"], "%Y-%m-%dT%H:%M:%SZ",
        ) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rejected({**packet, "window_end_utc": overlong}, known, plan)

        # El controlador existente no puede convertirse en un apply staging.
        source = (ROOT / "apps/platform-web/backend/app/dbi/migration_cli.py").read_text()
        assert 'if not running_in_ci:' in source
        assert 'require_authorized_github_actions_runtime()' in source
        assert 'host not in DBI_LOCAL_APPLY_HOSTS' in source
        with patch.object(migration_cli, "create_engine",
                          side_effect=AssertionError("no connection")):
            from contextlib import redirect_stderr
            import os
            with patch.dict(os.environ, {
                "DBI_ENVIRONMENT": "staging",
                "DBI_DATABASE_URL": (
                    "postgresql+psycopg://dbi_staging_migrator@"
                    "staging-db.example.invalid/dbi_staging"
                ),
            }, clear=True), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                assert migration_cli.main(["apply", "--confirm", "APPLY dbi_staging"]) == 2

    print("DBI staging packet: offline plan SHA, evidencias estructurales, separación y apply bloqueado OK.")


if __name__ == "__main__":
    run()
