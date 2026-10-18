"""CI offline: scope real de Campaign MULTI y 13 metadatos, sin servidor ni DB."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID
import sys

from fastapi import HTTPException
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/platform-web/backend"))

from app.api.v1.dbi_scientific_intake import preflight_scientific_intake_scope  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.campaigns.contracts import (  # noqa: E402
    DBICampaignAnalysisType, DBICampaignSnapshot, DBICampaignStatus,
)
from app.dbi.scientific_intake_scope import (  # noqa: E402
    ScientificDraftScopeRequest, ScientificScopeUnavailable,
    check_scientific_campaign_scope,
)

FARM = UUID("91000000-0000-4000-8000-000000000001")
PLOT = UUID("91000000-0000-4000-8000-000000000002")
CAMPAIGN = UUID("91000000-0000-4000-8000-000000000003")
TENANT = "tenant-ci"
ORG = "org-ci"
DATE = datetime(2026, 10, 17, 15, 30, tzinfo=timezone.utc)
INDEXES = ("ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green")


def make_draft() -> dict:
    files = [{
        "folder": "geospatial", "role": "rgb", "index": None,
        "relative_path": "GEO/ortho_RGB.tif", "size_bytes": 123456,
        "sha256": None, "file_content_verified": False,
    }]
    for idx in INDEXES:
        for role, suffix in (("scientific_cog", ".cog.tif"), ("qml_style", ".qml")):
            files.append({
                "folder": "multispectral", "role": role, "index": idx,
                "relative_path": f"MULTI/{idx}{suffix}", "size_bytes": 512,
                "sha256": None, "file_content_verified": False,
            })
    return {
        "schema_version": "dbi-h14-scientific-reception-draft.v1",
        "state": "local_metadata_only_not_uploaded",
        "scope": {
            "tenant_ref": TENANT, "organization_ref": ORG,
            "farm_id": str(FARM), "plot_id": str(PLOT),
            "campaign_id": str(CAMPAIGN),
        },
        "folders": {"geospatial": "GEO", "multispectral": "MULTI"},
        "files": files, "blockers": [], "structural_ready": True,
        "scientific_validated": False, "server_received": False,
        "institutional_approved": False, "published": False,
    }


def snapshot(**overrides) -> DBICampaignSnapshot:
    data = {
        "campaign_id": CAMPAIGN, "tenant_ref": TENANT, "organization_ref": ORG,
        "farm_id": FARM, "plot_id": PLOT, "analysis_type": "multispectral",
        "captured_at": DATE, "status": "TECHNICAL_REVIEW",
        "processed_at": None, "created_at": DATE, "updated_at": DATE,
        "reviewed_at": None, "field_started_at": None,
        "field_completed_at": None, "approved_at": None, "published_at": None,
        "current_revision_id": None, "source_job_id": None,
    }
    data.update(overrides)
    return DBICampaignSnapshot.model_validate(data)


def context(permission: DBIPermission) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="operator-ci", tenant_ref=TENANT,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset({DBIFarmScope(ORG, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORG, FARM, PLOT)}),
        permissions=frozenset({permission}),
    )


def rejection(payload: dict, name: str) -> None:
    try:
        ScientificDraftScopeRequest.model_validate(payload)
    except ValidationError:
        return
    raise AssertionError(f"Debía rechazar borrador inválido: {name}")


def validate_schema() -> None:
    draft = make_draft()
    req = ScientificDraftScopeRequest.model_validate(draft)
    assert len(req.files) == 13
    assert len({(x.role, x.index) for x in req.files}) == 13
    for case, transform in [
        ("unpublished falso", lambda d: d.update(published=True)),
        ("verified falso", lambda d: d["files"][2].update(file_content_verified=True)),
        ("hash inventado", lambda d: d["files"][1].update(sha256="a" * 64)),
        ("falta QML", lambda d: d["files"].pop()),
        ("index duplicado", lambda d: d["files"][2].update(index="ndre")),
        ("ruta escape", lambda d: d["files"][1].update(relative_path="MULTI/../GEO/ortho_RGB.tif")),
        ("ruta de otra carpeta", lambda d: d["files"][1].update(relative_path="OTHER/ndvi.cog.tif")),
        ("carpeta con barra", lambda d: d["folders"].update(multispectral="../MULTI")),
        ("root idéntico", lambda d: d["folders"].update(multispectral="GEO")),
        ("tamaño cero", lambda d: d["files"][1].update(size_bytes=0)),
        ("rango mayor a política", lambda d: d["files"][1].update(size_bytes=1_000_000_000_001)),
        ("fake ready", lambda d: d.update(structural_ready=False)),
        ("índice sin rol", lambda d: d["files"][1].update(index=None)),
        ("ruta con backslash", lambda d: d["files"][1].update(relative_path=r"MULTI\\ndvi.cog.tif")),
        ("campo extra", lambda d: d.update(secret="unexpected")),
    ]:
        altered = deepcopy(draft)
        transform(altered)
        rejection(altered, case)
    assert req.files[0].sha256 is None


def validate_scoped_campaign() -> None:
    request = ScientificDraftScopeRequest.model_validate(make_draft())
    for status in ("DRAFT", "PROCESSING", "ANALYZED", "TECHNICAL_REVIEW"):
        res = check_scientific_campaign_scope(
            request=request, campaign=snapshot(status=status),
            tenant_ref=TENANT, organization_ref=ORG, farm_id=FARM, plot_id=PLOT,
        )
        assert res.campaign_link_verified
        assert res.disposition == "campaign_scope_verified_only_no_upload"
        assert res.campaign_id == CAMPAIGN
        assert res.campaign_status == DBICampaignStatus(status)
        assert not any((
            res.file_content_verified, res.hashes_verified, res.scientific_validated,
            res.server_received, res.institutional_approved, res.published,
        ))
    for scenario, changes in [
        ("otra org", {"organization_ref": "another"}),
        ("otra finca", {"farm_id": UUID("91000000-0000-4000-8000-000000000009")}),
        ("campaña de densidad", {"analysis_type": DBICampaignAnalysisType.DENSITY}),
        ("aprobada", {"status": DBICampaignStatus.APPROVED}),
        ("publicada", {"status": DBICampaignStatus.PUBLISHED}),
        ("campo activo", {"status": DBICampaignStatus.FIELD_WORK}),
        ("marca aprobación", {"approved_at": DATE}),
        ("marca publicación", {"published_at": DATE}),
    ]:
        try:
            check_scientific_campaign_scope(
                request=request, campaign=snapshot(**changes),
                tenant_ref=TENANT, organization_ref=ORG, farm_id=FARM, plot_id=PLOT,
            )
        except ScientificScopeUnavailable:
            pass
        else:
            raise AssertionError(f"Campaña no autorizada aceptada: {scenario}")
    forged = make_draft()
    forged["scope"]["campaign_id"] = "91000000-0000-4000-8000-000000000099"
    request = ScientificDraftScopeRequest.model_validate(forged)
    try:
        check_scientific_campaign_scope(
            request=request, campaign=snapshot(),
            tenant_ref=TENANT, organization_ref=ORG, farm_id=FARM, plot_id=PLOT,
        )
    except ScientificScopeUnavailable:
        pass
    else:
        raise AssertionError("UUID de Campaign divergente aceptado.")


def validate_http_guards() -> None:
    payload = ScientificDraftScopeRequest.model_validate(make_draft())
    calls: list[dict] = []

    class Reader:
        def __init__(self, session):
            assert session is fake_session

        def read_campaign(self, **kwargs):
            calls.append(kwargs)
            return snapshot()

    fake_session = object()
    with patch("app.api.v1.dbi_scientific_intake.DBICampaignReader", Reader):
        response = preflight_scientific_intake_scope(
            ORG, FARM, PLOT, CAMPAIGN, payload, fake_session,
            context(DBIPermission.MANAGE),
        )
        assert response.campaign_link_verified
        assert calls == [{
            "campaign_id": CAMPAIGN, "tenant_ref": TENANT,
            "organization_ref": ORG, "farm_id": FARM, "plot_id": PLOT,
        }]
        calls.clear()
        try:
            preflight_scientific_intake_scope(
                ORG, FARM, PLOT, CAMPAIGN, payload, fake_session,
                context(DBIPermission.READ),
            )
        except HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError("READ consiguió preflight MANAGE.")
        assert not calls, "No debe consultar Campaign antes de verificar MANAGE."

    endpoint = ROOT / "apps/platform-web/backend/app/api/v1/dbi_scientific_intake.py"
    router = ROOT / "apps/platform-web/backend/app/api/v1/__init__.py"
    assert "permission=DBIPermission.MANAGE" in endpoint.read_text(encoding="utf-8")
    assert "session.commit(" not in endpoint.read_text(encoding="utf-8")
    assert "dbi_scientific_intake_router" in router.read_text(encoding="utf-8")


if __name__ == "__main__":
    validate_schema()
    validate_scoped_campaign()
    validate_http_guards()
    print("H14 OK: Campaign MULTI y 13 roles MANAGE scoped, sin bytes, grants ni publicación.")
