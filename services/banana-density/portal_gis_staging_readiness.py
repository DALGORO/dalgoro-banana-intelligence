"""Gate informativo OFFLINE de preparación GIS DBI para staging.

No abre sockets ni clientes DB/S3, no procesa originales ni habilita el worker.
Una salida válida NO autoriza despliegue/UAT y jamás revela configuración privada.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from portal_gis_prepare_s3 import preflight

ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = ROOT / "apps" / "platform-web" / "backend" / "dbi_alembic" / "versions"
REQUIRED_GIS_REVISION = "dbi_0026_gpkg_layer_choice"
UNVERIFIED = (
    "staging_database_head_and_role_grants",
    "staging_migration_execution_path_not_authorized",
    "private_s3_provider_iam_and_data_integrity",
    "isolated_worker_runtime_and_scheduler",
    "real_gpkg_uat_and_cross_tenant_access",
)


class OfflineReadinessBlocked(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def migration_head() -> str:
    """Inspección ESTÁTICA del grafo Alembic, sin importar revisiones ni tocar DB."""
    parents: dict[str, str | None] = {}
    for path in VERSIONS_DIR.glob("*.py"):
        metadata = {}
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]
            else:
                continue
            for name in names:
                if name in {"revision", "down_revision"}:
                    metadata[name] = ast.literal_eval(node.value)
        if "revision" not in metadata:
            continue
        rev, parent = metadata["revision"], metadata.get("down_revision")
        if not isinstance(rev, str) or not (
            parent is None or isinstance(parent, str)
        ) or rev in parents:
            raise OfflineReadinessBlocked("migration_graph_invalid")
        parents[rev] = parent
    if not parents or REQUIRED_GIS_REVISION not in parents:
        raise OfflineReadinessBlocked("migration_graph_invalid")
    heads = set(parents) - {parent for parent in parents.values() if parent is not None}
    if len(heads) != 1:
        raise OfflineReadinessBlocked("migration_graph_invalid")
    head = next(iter(heads))
    visited: set[str] = set()
    item: str | None = head
    while item is not None:
        if item in visited or item not in parents:
            raise OfflineReadinessBlocked("migration_graph_invalid")
        visited.add(item)
        item = parents[item]
    if visited != set(parents) or REQUIRED_GIS_REVISION not in visited:
        raise OfflineReadinessBlocked("migration_graph_invalid")
    return head


def inspect_offline(values: Mapping[str, str]) -> dict:
    """Valida exclusivamente configuración, política y grafo local; no conecta."""
    if values.get("DBI_ENVIRONMENT", "").strip().lower() != "staging":
        raise OfflineReadinessBlocked("staging_only")
    if values.get("DBI_GIS_WORKER_ENABLED", "").strip() not in {"", "0"}:
        raise OfflineReadinessBlocked("worker_must_remain_disabled")
    try:
        preflight(values)
    except Exception:
        # La excepción original podría contener datos proporcionados como secretos.
        raise OfflineReadinessBlocked("invalid_or_missing_staging_configuration") from None
    try:
        head = migration_head()
    except (OSError, SyntaxError, ValueError, TypeError):
        raise OfflineReadinessBlocked("migration_graph_invalid") from None
    return {
        "environment": "staging",
        "mode": "offline_no_network",
        "offline_configuration": "validated",
        "migration_code_head": head,
        "required_gis_revision": REQUIRED_GIS_REVISION,
        "deployment_readiness": "NOT_VERIFIED",
        "unverified_gates": list(UNVERIFIED),
    }


def main(argv: Sequence[str] | None = None, values: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight offline, NO acredita servicio DBI staging operativo.",
    )
    parser.add_argument("--offline", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        report = inspect_offline(os.environ if values is None else values)
    except OfflineReadinessBlocked as error:
        print(json.dumps({
            "environment": "staging", "mode": "offline_no_network",
            "offline_configuration": "blocked", "reason": error.reason,
            "deployment_readiness": "NOT_VERIFIED",
        }, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
