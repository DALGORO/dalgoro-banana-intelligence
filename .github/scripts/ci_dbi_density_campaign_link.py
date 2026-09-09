"""Prueba real del vínculo Density job -> Campaign sin ejecutar ciencia."""

from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import load_dbi_database_config  # noqa: E402
from app.dbi.campaigns.contracts import DBICampaignConflict, DBICampaignStatus  # noqa: E402
from app.dbi.campaigns.reader import DBICampaignReader  # noqa: E402
from app.dbi.campaigns.service import DBICampaignService  # noqa: E402
from app.dbi.density_campaign import (  # noqa: E402
    CAPTURED_AT_SOURCE_ASSET_CREATED_FALLBACK,
    link_density_job_to_campaign,
    mark_density_campaign_analyzed,
)
from app.dbi.models import Farm, Plot  # noqa: E402

FARM_ID = UUID("10000000-0000-4000-8000-000000000020")
PLOT_ID = UUID("20000000-0000-4000-8000-000000000020")
JOB_ID = UUID("40000000-0000-4000-8000-000000000020")
OTHER_JOB_ID = UUID("40000000-0000-4000-8000-000000000021")
ORTHOPHOTO_ASSET_ID = UUID("50000000-0000-4000-8000-000000000020")
TENANT_REF = "tenant_density_campaign_ci"
ORGANIZATION_REF = "organization_density_campaign_ci"
CAPTURED_AT_FALLBACK = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
PROCESSED_AT = datetime(2026, 9, 8, 16, 30, tzinfo=timezone.utc)
EXPECTED_STAGES = (
    "validate_environment",
    "validate_raster",
    "validate_boundary",
    "clip_raster",
    "generate_tiles",
    "run_yolo",
    "georeference_detections",
    "export_raw_gis",
    "deduplicate_detections",
    "calculate_statistics",
    "analyze_spatial_pattern",
    "generate_hex_density",
    "detect_planting_opportunities",
    "prioritize_planting_opportunities",
    "generate_kde_density",
    "generate_cartographic_package",
    "generate_technical_report",
)


def _require_ephemeral_ci() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Density/Campaign persistence solo puede ejecutarse en GitHub Actions.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("Density/Campaign persistence exige DBI_ENVIRONMENT=test.")

    config = load_dbi_database_config()
    identity = (
        config.database_name,
        config.url.username,
        config.url.host,
        config.url.port,
    )
    expected = ("dbi_test", "dbi_test_migrator", "127.0.0.1", 5432)
    if identity != expected:
        raise RuntimeError(
            "Density/Campaign persistence no apunta al fixture PostgreSQL efímero autorizado."
        )


def _seed_scope(session: Session) -> None:
    session.add(
        Farm(
            id=FARM_ID,
            organization_ref=ORGANIZATION_REF,
            code="density-campaign-ci-farm",
            name="Density Campaign CI Farm",
            status="active",
        )
    )
    session.add(
        Plot(
            id=PLOT_ID,
            farm_id=FARM_ID,
            code="density-campaign-ci-plot",
            name="Density Campaign CI Plot",
            status="active",
        )
    )
    session.commit()


def _read_campaign(session: Session, campaign_id: UUID):
    return DBICampaignReader(session).read_campaign(
        campaign_id=campaign_id,
        tenant_ref=TENANT_REF,
        organization_ref=ORGANIZATION_REF,
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
    )


def validate_density_source_contract() -> None:
    source_path = BACKEND / "app" / "api" / "v1" / "dbi_density_local.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    stage_value = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "STAGES"
            for target in node.targets
        ):
            stage_value = ast.literal_eval(node.value)
            break
    if stage_value is None:
        raise AssertionError("No se encontró STAGES en dbi_density_local.py.")
    assert tuple(key for key, _title in stage_value) == EXPECTED_STAGES

    required = (
        "link_density_job_to_campaign(",
        "update_job(job_id, **campaign_metadata)",
        "mark_density_campaign_analyzed(session_factory, final_job)",
        '"run-full-analysis"',
    )
    for fragment in required:
        assert fragment in source

    bridge_source = (ROOT / "services" / "banana-density" / "web_bridge.py").read_text(
        encoding="utf-8"
    )
    assert "density_campaign" not in bridge_source
    assert "DBICampaign" not in bridge_source


def validate_real_link() -> None:
    config = load_dbi_database_config()
    engine = create_engine(config.url)
    factory = sessionmaker(bind=engine)
    try:
        with Session(engine) as session:
            _seed_scope(session)
            metadata = link_density_job_to_campaign(
                session,
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                source_job_id=JOB_ID,
                orthophoto_asset_id=ORTHOPHOTO_ASSET_ID,
                orthophoto_sha256="a" * 64,
                orthophoto_asset_created_at=CAPTURED_AT_FALLBACK,
                target_density=1650.0,
            )
            session.commit()

            campaign_id = UUID(str(metadata["campaign_id"]))
            assert metadata["target_density"] == 1650.0
            assert metadata["orthophoto_asset_id"] == str(ORTHOPHOTO_ASSET_ID)
            assert metadata["orthophoto_sha256"] == "a" * 64
            assert metadata["campaign_captured_at_source"] == (
                CAPTURED_AT_SOURCE_ASSET_CREATED_FALLBACK
            )
            linked = _read_campaign(session, campaign_id)
            assert linked.status is DBICampaignStatus.PROCESSING
            assert linked.source_job_id == JOB_ID
            assert linked.processed_at is None

            replay = DBICampaignService(session).link_source_job(
                campaign_id=campaign_id,
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                source_job_id=JOB_ID,
            )
            assert replay.source_job_id == JOB_ID
            session.commit()

            try:
                DBICampaignService(session).link_source_job(
                    campaign_id=campaign_id,
                    tenant_ref=TENANT_REF,
                    organization_ref=ORGANIZATION_REF,
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                    source_job_id=OTHER_JOB_ID,
                )
            except DBICampaignConflict:
                session.rollback()
            else:
                raise AssertionError("Campaign aceptó un source_job_id divergente.")

        job = {
            **metadata,
            "farm_id": str(FARM_ID),
            "plot_id": str(PLOT_ID),
        }
        assert mark_density_campaign_analyzed(
            factory,
            job,
            occurred_at=PROCESSED_AT,
        ) is True

        with Session(engine) as session:
            analyzed = _read_campaign(session, campaign_id)
            assert analyzed.status is DBICampaignStatus.ANALYZED
            assert analyzed.processed_at == PROCESSED_AT

        assert mark_density_campaign_analyzed(
            factory,
            job,
            occurred_at=PROCESSED_AT + timedelta(minutes=5),
        ) is True
        with Session(engine) as session:
            replayed = _read_campaign(session, campaign_id)
            assert replayed.processed_at == PROCESSED_AT

        assert mark_density_campaign_analyzed(factory, {}) is False
    finally:
        engine.dispose()


def main() -> None:
    _require_ephemeral_ci()
    validate_density_source_contract()
    validate_real_link()
    print("Density -> Campaign: vínculo, lifecycle y aislamiento científico aprobados.")


if __name__ == "__main__":
    main()
