"""Hito 11: GET MULTI con READ, aislamiento y comprobación de provenance."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_multi_http.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-multi-http")

from fastapi import HTTPException
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))
sys.path.insert(0, str(ROOT / ".github/scripts"))

from app.api.v1 import dbi_multispectral, get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.multispectral.contracts import multispectral_extraction_id  # noqa: E402
from app.dbi.multispectral.repository import canonical_json, sha256_text  # noqa: E402
from ci_dbi_multi_persistence import _candidate  # noqa: E402

TENANT = "tenant-multi-ci"
ORG = "organization-multi-ci"
FARM = UUID("10000000-0000-4000-8000-000000000080")
PLOT = UUID("20000000-0000-4000-8000-000000000080")


def context(*, tenant=TENANT, organization=ORG, read=True, plot=PLOT):
    return DBIAccessContext(
        principal_ref="principal-multi-ci",
        tenant_ref=tenant,
        organization_refs=frozenset({organization}),
        farm_scopes=frozenset({DBIFarmScope(organization, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(organization, FARM, plot)}),
        permissions=frozenset({DBIPermission.READ}) if read else frozenset(),
    )


def row_from(candidate):
    payload_json = canonical_json(candidate.model_dump(mode="json"))
    fields = {
        "id": multispectral_extraction_id(candidate),
        "created_at": datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc),
        "payload_json": payload_json,
        "payload_sha256": sha256_text(payload_json),
    }
    for name in (
        "tenant_ref", "organization_ref", "farm_id", "plot_id",
        "observation_version_id", "source_raster_product_id", "sampling_point_id",
        "up_id", "schema_version", "support_mode", "support_profile_version",
        "support_limitation", "stack_fingerprint", "selected_count", "evidence_kind",
    ):
        fields[name] = getattr(candidate, name)
    return SimpleNamespace(**fields)


class Repo:
    def __init__(self, row):
        self.row = row
        self.queries = []

    def get_scoped(self, **kwargs):
        self.queries.append(kwargs)
        return self.row if all(getattr(self.row, {
            "extraction_id": "id"
        }.get(key, key)) == value for key, value in kwargs.items()) else None


def denied(status_code, operation):
    try:
        operation()
    except HTTPException as exc:
        assert exc.status_code == status_code
        assert "object_key" not in str(exc.detail)
        assert "sha256" not in str(exc.detail)
    else:
        raise AssertionError("Debe rechazar acceso sin exponer evidencia.")


def main():
    candidate = _candidate()
    row = row_from(candidate)
    repo = Repo(row)
    session = Session()
    def call(*, org=ORG, farm=FARM, plot=PLOT, extraction=None, ctx=None):
        return dbi_multispectral.get_multispectral_extraction(
            org, farm, plot, row.id if extraction is None else extraction,
            session, context() if ctx is None else ctx,
        )

    with patch.object(dbi_multispectral, "DBIMultispectralExtractionRepository", return_value=repo):
        data = call()
        assert data.extraction_id == row.id
        assert data.payload == candidate
        assert data.payload.evidence_kind == "derived"
        assert data.payload.support_mode == "window"
        assert len(data.payload.summaries) == 10
        assert data.created_at == row.created_at
        assert repo.queries == [{
            "extraction_id": row.id,
            "tenant_ref": TENANT,
            "organization_ref": ORG,
            "farm_id": FARM,
            "plot_id": PLOT,
        }]
        assert "object_key" not in data.model_dump_json()
        assert "S3_SECRET" not in data.model_dump_json()
        assert call() == data

        denied(404, lambda: call(ctx=context(read=False)))
        denied(404, lambda: call(org="organization-foreign"))
        denied(404, lambda: call(plot=uuid4()))
        denied(404, lambda: call(farm=uuid4()))
        denied(404, lambda: call(ctx=context(tenant="tenant-crossed")))
        denied(404, lambda: call(ctx=context(organization="org-crossed")))
        denied(404, lambda: call(extraction=uuid4()))
        repo.row = None
        denied(404, lambda: call())
        repo.row = row

        # Datos derivados almacenados no se exponen con provenance adulterado.
        mutations = {
            "payload_sha256": "f" * 64,
            "payload_json": row.payload_json + " ",
            "tenant_ref": "tenant-foreign",
            "organization_ref": "organization-foreign",
            "farm_id": uuid4(),
            "plot_id": uuid4(),
            "observation_version_id": uuid4(),
            "source_raster_product_id": uuid4(),
            "stack_fingerprint": "f" * 64,
            "evidence_kind": "inferred",
            "support_mode": "copa_up",
            "selected_count": row.selected_count + 1,
            "id": uuid4(),
            "created_at": None,
        }
        for attr, value in mutations.items():
            original = getattr(row, attr)
            setattr(row, attr, value)
            # La query podría rechazar primero los campos del ámbito.
            expected = 404 if attr in {
                "id", "tenant_ref", "organization_ref", "farm_id", "plot_id"
            } else 409
            denied(expected, lambda: call())
            setattr(row, attr, original)

        original = row.payload_json
        row.payload_json = '{"schema_version":"untrusted"}'
        denied(409, lambda: call())
        row.payload_json = original

    routes = [
        route for route in get_api_router().routes
        if getattr(route, "path", "").endswith(
            "/plots/{plot_id}/multispectral-extractions/{extraction_id}"
        )
    ]
    assert len(routes) == 1
    assert routes[0].methods == {"GET"}
    assert routes[0].response_model is dbi_multispectral.DBIMultispectralExtractionRead
    session.close()
    print("Hito 11 MULTI READ: scope, provenance, sin privados ni escritura OK.")


if __name__ == "__main__":
    main()
