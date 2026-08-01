"""Valida contratos y plan puro de registro de activos DBI."""

from __future__ import annotations

import ast
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.dbi.asset_registration import (  # noqa: E402
    DBIAssetRegistrationAction,
    DBIAssetRegistrationConflict,
    DBIAssetRegistrationIntent,
    DBIAssetRegistrationSnapshot,
    build_asset_registration_plan,
)
from app.dbi.asset_schemas import AnalysisInputAssetRegister  # noqa: E402

ASSET_ID = UUID("11111111-1111-4111-8111-111111111111")
FARM_ID = UUID("22222222-2222-4222-8222-222222222222")
PLOT_ID = UUID("33333333-3333-4333-8333-333333333333")
SHA256 = "a" * 64


def _intent() -> DBIAssetRegistrationIntent:
    return DBIAssetRegistrationIntent(
        asset_id=ASSET_ID,
        tenant_ref="tenant-a",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        asset_kind="orthophoto",
        content_type="image/tiff",
        size_bytes=4096,
        sha256=SHA256,
        crs="EPSG:32717",
        created_by_ref="principal-a",
    )


def _snapshot(plan, *, status: str = "registered") -> DBIAssetRegistrationSnapshot:
    return DBIAssetRegistrationSnapshot(
        asset_id=plan.asset_id,
        tenant_ref=plan.tenant_ref,
        farm_id=plan.farm_id,
        plot_id=plan.plot_id,
        asset_kind=plan.asset_kind,
        status=status,
        object_key=plan.metadata.address.object_key,
        content_type=plan.metadata.content_type,
        size_bytes=plan.metadata.size_bytes,
        sha256=plan.metadata.sha256,
        crs=plan.crs,
        created_by_ref=plan.created_by_ref,
    )


def _assert_conflict(factory) -> None:
    try:
        factory()
    except DBIAssetRegistrationConflict:
        return
    raise AssertionError("El plan debía rechazar la declaración divergente.")


def validate_schema() -> None:
    payload = AnalysisInputAssetRegister(
        asset_id=ASSET_ID,
        plot_id=PLOT_ID,
        asset_kind="orthophoto",
        content_type="image/tiff",
        size_bytes=4096,
        sha256=SHA256,
        crs="EPSG:32717",
    )
    assert payload.asset_id == ASSET_ID
    assert payload.model_config.get("extra") == "forbid"

    forbidden_fields = {
        "tenant_ref",
        "created_by_ref",
        "status",
        "object_key",
        "verified_at",
        "created_at",
        "updated_at",
    }
    assert forbidden_fields.isdisjoint(payload.model_fields)

    invalid_payloads = (
        {"object_key": "forged"},
        {"status": "verified"},
        {"content_type": "Image/Tiff"},
        {"content_type": "image/tiff; charset=binary"},
        {"sha256": "A" * 64},
        {"size_bytes": 0},
        {"crs": " EPSG:32717"},
    )
    base = payload.model_dump()
    for changes in invalid_payloads:
        try:
            AnalysisInputAssetRegister(**(base | changes))
        except ValidationError:
            pass
        else:
            raise AssertionError(f"El contrato debía rechazar: {changes}")


def validate_new_registration() -> None:
    plan = build_asset_registration_plan(intent=_intent(), existing=None)
    assert plan.action is DBIAssetRegistrationAction.CREATE
    assert plan.created is True
    assert plan.status == "registered"
    assert plan.metadata.address.object_id == ASSET_ID
    assert plan.metadata.address.tenant_ref == "tenant-a"
    assert plan.metadata.address.purpose.value == "analysis-inputs"
    assert "tenant-a" not in plan.metadata.address.object_key
    assert str(ASSET_ID) in plan.metadata.address.object_key


def validate_exact_idempotency() -> None:
    created = build_asset_registration_plan(intent=_intent(), existing=None)
    for status in ("registered", "verified", "quarantined", "retired"):
        reused = build_asset_registration_plan(
            intent=_intent(),
            existing=_snapshot(created, status=status),
        )
        assert reused.action is DBIAssetRegistrationAction.REUSE
        assert reused.created is False
        assert reused.status == status
        assert reused.metadata == created.metadata


def validate_divergent_duplicates() -> None:
    created = build_asset_registration_plan(intent=_intent(), existing=None)
    snapshot = _snapshot(created)
    variants = (
        replace(snapshot, tenant_ref="tenant-b"),
        replace(snapshot, farm_id=UUID("44444444-4444-4444-8444-444444444444")),
        replace(snapshot, plot_id=None),
        replace(snapshot, asset_kind="boundary"),
        replace(snapshot, object_key="tenants/forged/analysis-inputs/forged"),
        replace(snapshot, content_type="application/zip"),
        replace(snapshot, size_bytes=4097),
        replace(snapshot, sha256="b" * 64),
        replace(snapshot, crs="EPSG:4326"),
        replace(snapshot, created_by_ref="principal-b"),
        replace(snapshot, status="unknown"),
    )
    for existing in variants:
        _assert_conflict(
            lambda existing=existing: build_asset_registration_plan(
                intent=_intent(),
                existing=existing,
            )
        )


def validate_intent_boundaries() -> None:
    base = _intent()
    invalid = (
        replace(base, tenant_ref="all"),
        replace(base, asset_kind="raster"),
        replace(base, content_type="application/pdf"),
        replace(base, size_bytes=True),
        replace(base, sha256="A" * 64),
        replace(base, crs=" EPSG:32717"),
        replace(base, created_by_ref=""),
    )
    for intent in invalid:
        _assert_conflict(
            lambda intent=intent: build_asset_registration_plan(
                intent=intent,
                existing=None,
            )
        )


def validate_static_boundaries() -> None:
    paths = (
        BACKEND_ROOT / "app" / "dbi" / "asset_schemas.py",
        BACKEND_ROOT / "app" / "dbi" / "asset_registration.py",
    )
    forbidden_imports = {
        "boto3",
        "botocore",
        "fastapi",
        "sqlalchemy",
        "requests",
        "httpx",
    }
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.partition(".")[0])
        assert forbidden_imports.isdisjoint(roots)

    source = (BACKEND_ROOT / "app" / "dbi" / "asset_registration.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "commit(",
        "rollback(",
        "SessionLocal",
        "DATABASE_URL",
        "issue_temporary_access",
        "AnalysisArtifact",
    ):
        assert forbidden not in source


if __name__ == "__main__":
    validate_schema()
    validate_new_registration()
    validate_exact_idempotency()
    validate_divergent_duplicates()
    validate_intent_boundaries()
    validate_static_boundaries()
    print("Registro idempotente de activos DBI validado offline.")
