"""Barreras offline del dominio técnico Campaign/Levantamiento DBI."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.campaigns.contracts import (  # noqa: E402
    DBI_CAMPAIGN_TRANSITIONS,
    DBICampaignAnalysisType,
    DBICampaignConflict,
    DBICampaignCreate,
    DBICampaignStatus,
    require_campaign_transition,
)
from app.dbi.models import Campaign  # noqa: E402

CAMPAIGN_ID = UUID("30000000-0000-4000-8000-000000000019")


def validate_contracts() -> None:
    capture = datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc)
    request = DBICampaignCreate(
        campaign_id=CAMPAIGN_ID,
        analysis_type=DBICampaignAnalysisType.DENSITY,
        captured_at=capture,
    )
    assert request.campaign_id == CAMPAIGN_ID
    assert request.analysis_type is DBICampaignAnalysisType.DENSITY
    assert request.captured_at == capture
    assert DBICampaignAnalysisType.MULTISPECTRAL.value == "multispectral"

    try:
        DBICampaignCreate(
            campaign_id=CAMPAIGN_ID,
            captured_at=datetime(2026, 9, 8, 15, 30),
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("captured_at naive no debe ser aceptado.")


def validate_lifecycle() -> None:
    for current, allowed in DBI_CAMPAIGN_TRANSITIONS.items():
        require_campaign_transition(current, current)
        for target in allowed:
            require_campaign_transition(current, target)

    forbidden = (
        (DBICampaignStatus.DRAFT, DBICampaignStatus.ANALYZED),
        (DBICampaignStatus.PROCESSING, DBICampaignStatus.DRAFT),
        (DBICampaignStatus.FIELD_WORK, DBICampaignStatus.PUBLISHED),
        (DBICampaignStatus.PUBLISHED, DBICampaignStatus.APPROVED),
    )
    for current, target in forbidden:
        try:
            require_campaign_transition(current, target)
        except DBICampaignConflict:
            pass
        else:
            raise AssertionError(f"Transición indebida aceptada: {current} -> {target}")


def validate_model_contract() -> None:
    expected = {
        "tenant_ref",
        "organization_ref",
        "farm_id",
        "plot_id",
        "analysis_type",
        "captured_at",
        "processed_at",
        "reviewed_at",
        "field_started_at",
        "field_completed_at",
        "approved_at",
        "published_at",
        "current_revision_id",
        "source_job_id",
    }
    assert expected.issubset(Campaign.__table__.columns.keys())
    for field_name in (
        "tenant_ref",
        "organization_ref",
        "plot_id",
        "analysis_type",
        "captured_at",
    ):
        assert Campaign.__table__.columns[field_name].nullable


def validate_sources() -> None:
    campaign_root = BACKEND / "app" / "dbi" / "campaigns"
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(campaign_root.glob("*.py"))
    )
    router_source = (
        BACKEND / "app" / "api" / "v1" / "dbi_campaigns.py"
    ).read_text(encoding="utf-8")
    migration_source = (
        BACKEND
        / "dbi_alembic"
        / "versions"
        / "20260908_19_campaign_domain.py"
    ).read_text(encoding="utf-8")
    repository_source = (
        campaign_root / "repository.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "dbi_density_local",
        "dbi_density_candidate_review_local",
        "services.banana-density",
        "web_bridge",
    ):
        assert forbidden not in combined
        assert forbidden not in router_source

    assert "on_conflict_do_nothing(index_elements=[Campaign.id])" in repository_source
    assert "Campaign.tenant_ref == tenant_ref" in repository_source
    assert "Campaign.organization_ref == organization_ref" in repository_source
    assert "Campaign.farm_id == farm_id" in repository_source
    assert "Campaign.plot_id == plot_id" in repository_source

    base_path = "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns"
    assert base_path in router_source
    assert "DBIAuthorizationPolicy.require_plot" in router_source

    assert 'revision: str = "dbi_0019_campaign_domain"' in migration_source
    assert 'down_revision: str | None = "dbi_0018_multi_extractions"' in migration_source
    assert "fk_dbi_campaigns_plot_farm" in migration_source


def main() -> None:
    validate_contracts()
    validate_lifecycle()
    validate_model_contract()
    validate_sources()
    print("Campaign técnico DBI: validación offline aprobada.")


if __name__ == "__main__":
    main()
