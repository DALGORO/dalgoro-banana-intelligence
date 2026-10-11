"""Expediente OFFLINE de revisión previa a migraciones DBI staging.

La validación de referencias NO acredita que los respaldos, permisos o
aprobaciones existan. Ninguna operación conecta a PostgreSQL ni ejecuta SQL.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Sequence

from sqlalchemy.engine import make_url

from app.db.dbi_config import DBIDatabaseConfig
from app.dbi.migration_cli import _migration_graph
from app.dbi.migration_plan import generate_offline_plan
from app.dbi.staging_migration_verify import REQUIRED_GIS_REVISION

SCHEMA = "dbi-staging-change-review.v1"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{5,63}\Z")
MAX_PACKET_BYTES = 8192
EVIDENCE_FIELDS = (
    "readonly_verify_report_sha256",
    "backup_manifest_sha256",
    "restore_test_report_sha256",
    "rollback_runbook_sha256",
    "independent_approval_sha256",
)
PACKET_FIELDS = frozenset({
    "schema", "environment", "database", "current_revision",
    "head_revision", "plan_sha256", "change_ticket",
    "operator_ref", "approver_ref", "window_start_utc",
    "window_end_utc", *EVIDENCE_FIELDS,
})


class PacketInvalid(ValueError):
    """Rechazo sin revelar contenido del expediente o de su ruta."""


def _plan() -> tuple[set[str], Any]:
    """Plan Alembic exacto, pero con URL SINTÉTICA y sin motores/sockets."""
    known, head = _migration_graph()
    if REQUIRED_GIS_REVISION not in known:
        raise PacketInvalid("migration_head_missing")
    config = DBIDatabaseConfig(
        environment="staging",
        url=make_url(
            "postgresql+psycopg://dbi_staging_migrator@"
            "127.0.0.1:5432/dbi_staging"
        ),
    )
    plan = generate_offline_plan(config, running_in_ci=False)
    if plan.head_revision != head:
        raise PacketInvalid("migration_head_mismatch")
    return known, plan


def _read_packet(path: Path) -> dict:
    """Entrada acotada, JSON sin claves duplicadas; jamás imprimirla."""
    if path.is_symlink() or not path.is_file():
        raise PacketInvalid("packet_unavailable")
    if not 1 <= path.stat().st_size <= MAX_PACKET_BYTES:
        raise PacketInvalid("packet_size_invalid")

    def unique_pairs(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise PacketInvalid("packet_duplicate_field")
            result[name] = value
        return result

    data = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=unique_pairs)
    if type(data) is not dict or set(data) != PACKET_FIELDS:
        raise PacketInvalid("packet_schema_invalid")
    return data


def _utc_window(text: object) -> datetime:
    if type(text) is not str or re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", text,
    ) is None:
        raise PacketInvalid("change_window_invalid")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise PacketInvalid("change_window_invalid") from None


def review_packet(
    packet: dict,
    known: set[str],
    plan: Any,
    *,
    now: datetime | None = None,
) -> dict:
    """Solo coherencia de formato/huella; jamás autentica evidencia externa."""
    if type(packet) is not dict or set(packet) != PACKET_FIELDS:
        raise PacketInvalid("packet_schema_invalid")

    def equals(name: str, required: str):
        if type(packet[name]) is not str or packet[name] != required:
            raise PacketInvalid("packet_scope_invalid")

    equals("schema", SCHEMA)
    equals("environment", "staging")
    equals("database", "dbi_staging")
    equals("head_revision", plan.head_revision)
    equals("plan_sha256", plan.fingerprint)
    previous = packet["current_revision"]
    if type(previous) is not str or previous not in known or previous == plan.head_revision:
        raise PacketInvalid("packet_revision_invalid")

    for field in ("change_ticket", "operator_ref", "approver_ref"):
        value = packet[field]
        if type(value) is not str or REF.fullmatch(value) is None:
            raise PacketInvalid("packet_reference_invalid")
    if packet["operator_ref"] == packet["approver_ref"]:
        raise PacketInvalid("independent_approval_required")

    digests = [packet[field] for field in EVIDENCE_FIELDS]
    if any(type(v) is not str or HEX64.fullmatch(v) is None for v in digests):
        raise PacketInvalid("packet_evidence_digest_invalid")
    if len(set(digests)) != len(digests):
        raise PacketInvalid("packet_evidence_digest_reused")

    start = _utc_window(packet["window_start_utc"])
    end = _utc_window(packet["window_end_utc"])
    checked_at = datetime.now(timezone.utc) if now is None else now
    if (
        checked_at.tzinfo is None
        or start <= checked_at
        or start > checked_at + timedelta(days=30)
        or end <= start
        or end - start > timedelta(hours=2)
    ):
        raise PacketInvalid("change_window_invalid")

    canonical = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "operation": "review-staging-change-packet",
        "environment": "staging",
        "database": "dbi_staging",
        "head_revision": plan.head_revision,
        "plan_sha256": plan.fingerprint,
        "packet_sha256": sha256(canonical.encode("utf-8")).hexdigest(),
        "packet_structure": "VALIDATED",
        "external_evidence": "REFERENCED_NOT_AUTHENTICATED",
        "authorization": "PENDING_INDEPENDENT_EXTERNAL_REVIEW",
        "migration_apply": "BLOCKED",
        "deployment_readiness": "NOT_VERIFIED",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dbi-staging-change-review",
        description="Plan y revisión documental OFFLINE; nunca aplica migraciones.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", action="store_true")
    group.add_argument("--review-packet", type=Path)
    args = parser.parse_args(argv)
    try:
        known, plan = _plan()
        if args.plan:
            report = {
                "operation": "plan-staging-offline",
                "environment": "staging",
                "database": "dbi_staging",
                "head_revision": plan.head_revision,
                "plan_sha256": plan.fingerprint,
                "external_evidence": "NOT_CHECKED",
                "migration_apply": "BLOCKED",
                "deployment_readiness": "NOT_VERIFIED",
            }
        else:
            report = review_packet(_read_packet(args.review_packet), known, plan)
    except PacketInvalid:
        report = {
            "operation": "review-staging-change-packet",
            "result": "BLOCKED",
            "migration_apply": "BLOCKED",
            "deployment_readiness": "NOT_VERIFIED",
        }
        print(json.dumps(report, sort_keys=True))
        return 2
    except Exception:
        # No se imprimen URL, rutas, traceback, nombres ni contenido del expediente.
        report = {
            "operation": "review-staging-change-packet",
            "result": "UNAVAILABLE",
            "migration_apply": "BLOCKED",
            "deployment_readiness": "NOT_VERIFIED",
        }
        print(json.dumps(report, sort_keys=True))
        return 3
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
