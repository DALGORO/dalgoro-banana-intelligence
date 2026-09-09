"""Prueba real de adopción idempotente de un job Density histórico en Campaign."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import load_dbi_database_config  # noqa: E402
from app.dbi.campaigns.artifacts import (  # noqa: E402
    DBICampaignArtifactReader,
    DBICampaignArtifactRegistration,
    DBICampaignArtifactService,
    DBICampaignArtifactSourceKind,
    DBICampaignArtifactTechnicalStatus,
    DBICampaignArtifactType,
)
from app.dbi.density_legacy_campaign import (  # noqa: E402
    LEGACY_CAMPAIGN_ORIGIN,
    adopt_historical_density_job_to_campaign,
    legacy_density_campaign_id,
)
from app.dbi.models import AnalysisInputAsset, Campaign, Farm, Plot  # noqa: E402

FARM_ID = UUID("10000000-0000-4000-8000-000000000131")
PLOT_ID = UUID("20000000-0000-4000-8000-000000000131")
ORTHO_ID = UUID("30000000-0000-4000-8000-000000000131")
LEGACY_JOB_ID = UUID("40000000-0000-4000-8000-000000000131")
TENANT_REF = "tenant_density_legacy_campaign_ci"
ORGANIZATION_REF = "organization_density_legacy_campaign_ci"
CAPTURED_AT = datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)
PROCESSED_AT = datetime(2026, 7, 10, 19, 0, tzinfo=timezone.utc)
ORTHO_SHA = "7" * 64


def _require_ephemeral_ci() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Legacy Campaign adoption solo puede ejecutarse en GitHub Actions.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("Legacy Campaign adoption exige DBI_ENVIRONMENT=test.")
    config = load_dbi_database_config()
    identity = (
        config.database_name,
        config.url.username,
        config.url.host,
        config.url.port,
    )
    expected = ("dbi_test", "dbi_test_migrator", "127.0.0.1", 5432)
    if identity != expected:
        raise RuntimeError("Legacy Campaign adoption no apunta al PostGIS efímero autorizado.")


def _seed(session: Session) -> None:
    session.add(
        Farm(
            id=FARM_ID,
            organization_ref=ORGANIZATION_REF,
            code="density-legacy-campaign-ci-farm",
            name="Density Legacy Campaign CI Farm",
            status="active",
        )
    )
    session.add(
        Plot(
            id=PLOT_ID,
            farm_id=FARM_ID,
            code="density-legacy-campaign-ci-plot",
            name="Density Legacy Campaign CI Plot",
            status="active",
        )
    )
    session.add(
        AnalysisInputAsset(
            id=ORTHO_ID,
            tenant_ref=TENANT_REF,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            asset_kind="orthophoto",
            status="verified",
            object_key="ci/density-legacy-campaign/orthophoto.tif",
            content_type="image/tiff",
            size_bytes=4096,
            sha256=ORTHO_SHA,
            crs="EPSG:32717",
            created_by_ref="density-legacy-campaign-ci",
            verified_at=CAPTURED_AT,
            created_at=CAPTURED_AT,
            updated_at=CAPTURED_AT,
        )
    )
    session.commit()


def validate_real_legacy_adoption() -> None:
    config = load_dbi_database_config()
    engine = create_engine(config.url)
    try:
        with Session(engine) as session:
            _seed(session)
            expected_campaign_id = legacy_density_campaign_id(LEGACY_JOB_ID)

            first, first_created = adopt_historical_density_job_to_campaign(
                session,
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                source_job_id=LEGACY_JOB_ID,
                captured_at=CAPTURED_AT,
                processed_at=PROCESSED_AT,
            )
            assert first_created is True
            assert first.campaign_id == expected_campaign_id
            assert first.status.value == "ANALYZED"
            assert first.source_job_id == LEGACY_JOB_ID
            assert first.processed_at == PROCESSED_AT

            artifact, artifact_created = DBICampaignArtifactService(session).register_artifact(
                campaign_id=first.campaign_id,
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                request=DBICampaignArtifactRegistration(
                    artifact_type=DBICampaignArtifactType.ORTHOPHOTO_SOURCE,
                    source_kind=DBICampaignArtifactSourceKind.INPUT_ASSET,
                    source_ref=ORTHO_ID,
                    sha256=ORTHO_SHA,
                    version=1,
                ),
            )
            assert artifact_created is True
            assert artifact.technical_status is DBICampaignArtifactTechnicalStatus.CURRENT
            assert artifact.published is False
            session.commit()

            second, second_created = adopt_historical_density_job_to_campaign(
                session,
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                source_job_id=LEGACY_JOB_ID,
                captured_at=CAPTURED_AT,
                processed_at=PROCESSED_AT,
            )
            assert second_created is False
            assert second.campaign_id == expected_campaign_id
            assert second.status.value == "ANALYZED"

            repeated, repeated_created = DBICampaignArtifactService(session).register_artifact(
                campaign_id=second.campaign_id,
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                request=DBICampaignArtifactRegistration(
                    artifact_type="orthophoto_source",
                    source_kind="input_asset",
                    source_ref=ORTHO_ID,
                    sha256=ORTHO_SHA,
                    version=1,
                ),
            )
            assert repeated_created is False
            assert repeated.campaign_artifact_id == artifact.campaign_artifact_id
            session.commit()

            artifacts = DBICampaignArtifactReader(session).list_artifacts(
                campaign_id=expected_campaign_id,
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            )
            assert len(artifacts) == 1
            assert artifacts[0].artifact_type is DBICampaignArtifactType.ORTHOPHOTO_SOURCE
            assert session.execute(
                select(func.count()).select_from(Campaign).where(
                    Campaign.source_job_id == LEGACY_JOB_ID
                )
            ).scalar_one() == 1

            assert LEGACY_CAMPAIGN_ORIGIN == "legacy_import"
    finally:
        engine.dispose()


def main() -> None:
    _require_ephemeral_ci()
    validate_real_legacy_adoption()
    print("Density legacy Campaign adoption: persistencia e idempotencia aprobadas.")


if __name__ == "__main__":
    main()
