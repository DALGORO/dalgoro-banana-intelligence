"""Valida contratos y consultas DBI autorizadas completamente offline."""

from __future__ import annotations

import inspect
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_authorized_reads.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-authorized-reads-secret")
os.environ.pop("DBI_ENVIRONMENT", None)
os.environ.pop("DBI_DATABASE_URL", None)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException  # noqa: E402

from app.api.v1 import dbi_reads, get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.read_schemas import (  # noqa: E402
    AnalysisArtifactRead,
    AnalysisInputAssetRead,
    AnalysisJobRead,
)


def _context():
    farm_id = uuid4()
    plot_id = uuid4()
    context = DBIAccessContext(
        principal_ref="principal-1",
        tenant_ref="tenant-1",
        organization_refs=frozenset({"organization-1"}),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref="organization-1", farm_id=farm_id)}
        ),
        plot_scopes=frozenset(
            {
                DBIPlotScope(
                    organization_ref="organization-1",
                    farm_id=farm_id,
                    plot_id=plot_id,
                )
            }
        ),
        permissions=frozenset({DBIPermission.READ}),
    )
    return context, farm_id, plot_id


def validate_router_contract() -> None:
    paths: dict[str, set[str]] = {}
    for route in get_api_router().routes:
        if not route.path.startswith("/dbi/"):
            continue
        paths.setdefault(route.path, set()).update(route.methods or set())

    expected = {
        "/dbi/organizations/{organization_ref}/farms",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/campaigns",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/campaigns/{campaign_id}",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/assets",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/assets/{asset_id}",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/artifacts",
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/artifacts/{artifact_id}",
    }
    assert expected.issubset(paths)
    assert all("GET" in paths[path] for path in expected)


def validate_sensitive_fields_are_excluded() -> None:
    forbidden = {
        "tenant_ref",
        "object_key",
        "sha256",
        "command_sha256",
        "orthophoto_asset_ref",
        "boundary_asset_ref",
        "exclusions_asset_ref",
        "requested_by_ref",
        "created_by_ref",
    }
    for schema in (AnalysisJobRead, AnalysisInputAssetRead, AnalysisArtifactRead):
        assert forbidden.isdisjoint(schema.model_fields)
        assert schema.model_config.get("extra") == "forbid"
        assert schema.model_config.get("from_attributes") is True


def validate_non_enumerable_denial() -> None:
    context, farm_id, _ = _context()
    try:
        dbi_reads._require_farm(context, "organization-1", uuid4())
    except HTTPException as error:
        denied = (error.status_code, error.detail)
    else:
        raise AssertionError("Una finca fuera de ámbito debía ser ocultada.")

    class EmptyFarmRepository:
        def __init__(self, session):
            self.session = session

        def get_by_id(self, **kwargs):
            return None

    with patch.object(dbi_reads, "FarmRepository", EmptyFarmRepository):
        try:
            dbi_reads.get_farm(
                "organization-1", farm_id, SimpleNamespace(), context
            )
        except HTTPException as error:
            missing = (error.status_code, error.detail)
        else:
            raise AssertionError("Una finca inexistente debía responder 404.")

    assert denied == missing == (404, "Recurso DBI no encontrado.")


def validate_scope_filtering() -> None:
    context, allowed_farm_id, _ = _context()
    denied_farm_id = uuid4()
    now = datetime.now(timezone.utc)

    def farm(farm_id):
        return SimpleNamespace(
            id=farm_id,
            organization_ref="organization-1",
            code=str(farm_id),
            name="Finca",
            status="active",
            created_at=now,
            updated_at=now,
        )

    class RecordingFarmRepository:
        def __init__(self, session):
            self.session = session

        def list_by_organization(self, *, organization_ref):
            assert organization_ref == "organization-1"
            return [farm(allowed_farm_id), farm(denied_farm_id)]

    with patch.object(dbi_reads, "FarmRepository", RecordingFarmRepository):
        result = dbi_reads.list_farms(
            "organization-1", SimpleNamespace(), context
        )
    assert [item.id for item in result] == [allowed_farm_id]


def validate_plot_scope_for_jobs() -> None:
    context, farm_id, allowed_plot_id = _context()
    denied_plot_id = uuid4()
    now = datetime.now(timezone.utc)

    def job(plot_id):
        return SimpleNamespace(
            id=uuid4(),
            request_id="request-1",
            correlation_id="correlation-1",
            farm_id=farm_id,
            plot_id=plot_id,
            campaign_id=None,
            model_version_ref="model-v1",
            pipeline_config_version="pipeline-v1",
            status="accepted",
            accepted_at=now,
            created_at=now,
            updated_at=now,
        )

    class RecordingJobRepository:
        def __init__(self, session):
            self.session = session

        def list_by_farm(self, *, tenant_ref, farm_id):
            assert tenant_ref == "tenant-1"
            return [job(allowed_plot_id), job(denied_plot_id)]

    with patch.object(dbi_reads, "AnalysisJobRepository", RecordingJobRepository):
        result = dbi_reads.list_jobs(
            "organization-1", farm_id, SimpleNamespace(), context
        )
    assert len(result) == 1
    assert result[0].plot_id == allowed_plot_id


def validate_static_boundaries() -> None:
    router_source = inspect.getsource(dbi_reads)
    repositories_source = inspect.getsource(sys.modules["app.dbi.repositories"])
    for forbidden in (
        "SessionLocal",
        "from app.db.session",
        "app.models.user",
        "app.models.company",
        "object_key=",
        "sha256=",
    ):
        assert forbidden not in router_source
    assert "tenant_ref=context.tenant_ref" in router_source
    assert "Farm.organization_ref == organization_ref" in repositories_source
    assert "AnalysisJob.tenant_ref == tenant_ref" in repositories_source
    assert "AnalysisInputAsset.tenant_ref == tenant_ref" in repositories_source
    assert "DBI_READ_LIST_LIMIT = 100" in repositories_source
    assert repositories_source.count(".limit(DBI_READ_LIST_LIMIT)") == 6


if __name__ == "__main__":
    validate_router_contract()
    validate_sensitive_fields_are_excluded()
    validate_non_enumerable_denial()
    validate_scope_filtering()
    validate_plot_scope_for_jobs()
    validate_static_boundaries()
    print("Consultas DBI autorizadas validadas offline.")
