"""Prueba real del catálogo técnico Campaign contra PostgreSQL/PostGIS efímero."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import load_dbi_database_config  # noqa: E402
from app.dbi.campaigns.artifacts import (  # noqa: E402
    DBICampaignArtifactReader,
    DBICampaignArtifactRegistration,
    DBICampaignArtifactService,
    DBICampaignArtifactTechnicalStatus,
    DBICampaignArtifactType,
)
from app.dbi.campaigns.contracts import (  # noqa: E402
    DBICampaignConflict,
    DBICampaignCreate,
    DBICampaignUnavailable,
)
from app.dbi.campaigns.service import DBICampaignService  # noqa: E402
from app.dbi.models import (  # noqa: E402
    AnalysisArtifact,
    AnalysisInputAsset,
    AnalysisJob,
    AnalysisJobAttempt,
    Farm,
    Plot,
)

FARM_ID = UUID("10000000-0000-4000-8000-000000000020")
PLOT_ID = UUID("20000000-0000-4000-8000-000000000020")
CAMPAIGN_ID = UUID("30000000-0000-4000-8000-000000000020")
ORTHO_ID = UUID("40000000-0000-4000-8000-000000000020")
BOUNDARY_V1_ID = UUID("41000000-0000-4000-8000-000000000020")
BOUNDARY_V2_ID = UUID("42000000-0000-4000-8000-000000000020")
JOB_ID = UUID("50000000-0000-4000-8000-000000000020")
ATTEMPT_ID = UUID("51000000-0000-4000-8000-000000000020")
REPORT_ID = UUID("60000000-0000-4000-8000-000000000020")
PIPELINE_STATE_ID = UUID("61000000-0000-4000-8000-000000000020")
PRIORITY_ID = UUID("62000000-0000-4000-8000-000000000020")
REVISION_ID = UUID("70000000-0000-4000-8000-000000000020")
TENANT_REF = "tenant_campaign_artifact_ci"
ORGANIZATION_REF = "organization_campaign_artifact_ci"
NOW = datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc)

ORTHO_SHA = "1" * 64
BOUNDARY_V1_SHA = "2" * 64
BOUNDARY_V2_SHA = "3" * 64
REPORT_SHA = "4" * 64
PIPELINE_SHA = "5" * 64
PRIORITY_SHA = "6" * 64


def _require_ephemeral_ci() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Campaign artifact persistence solo puede ejecutarse en GitHub Actions.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("Campaign artifact persistence exige DBI_ENVIRONMENT=test.")
    config = load_dbi_database_config()
    identity = (
        config.database_name,
        config.url.username,
        config.url.host,
        config.url.port,
    )
    expected = ("dbi_test", "dbi_test_migrator", "127.0.0.1", 5432)
    if identity != expected:
        raise RuntimeError("Campaign artifact persistence no apunta al fixture efímero autorizado.")


def _seed(session: Session) -> None:
    session.add(
        Farm(
            id=FARM_ID,
            organization_ref=ORGANIZATION_REF,
            code="campaign-artifact-ci-farm",
            name="Campaign Artifact CI Farm",
            status="active",
        )
    )
    session.add(
        Plot(
            id=PLOT_ID,
            farm_id=FARM_ID,
            code="campaign-artifact-ci-plot",
            name="Campaign Artifact CI Plot",
            status="active",
        )
    )
    session.flush()

    DBICampaignService(session).create_campaign(
        tenant_ref=TENANT_REF,
        organization_ref=ORGANIZATION_REF,
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        request=DBICampaignCreate(
            campaign_id=CAMPAIGN_ID,
            analysis_type="density",
            captured_at=NOW,
        ),
    )
    session.flush()

    for asset_id, kind, sha, object_key in (
        (ORTHO_ID, "orthophoto", ORTHO_SHA, "ci/campaign-artifact/orthophoto.tif"),
        (BOUNDARY_V1_ID, "boundary", BOUNDARY_V1_SHA, "ci/campaign-artifact/boundary-v1.gpkg"),
        (BOUNDARY_V2_ID, "boundary", BOUNDARY_V2_SHA, "ci/campaign-artifact/boundary-v2.gpkg"),
    ):
        session.add(
            AnalysisInputAsset(
                id=asset_id,
                tenant_ref=TENANT_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                asset_kind=kind,
                status="verified",
                object_key=object_key,
                content_type=(
                    "image/tiff" if kind == "orthophoto" else "application/geopackage+sqlite3"
                ),
                size_bytes=1024,
                sha256=sha,
                crs="EPSG:32717",
                created_by_ref="campaign-artifact-ci",
                verified_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    session.add(
        AnalysisJob(
            id=JOB_ID,
            tenant_ref=TENANT_REF,
            request_id="campaign-artifact-ci-request",
            correlation_id="campaign-artifact-ci-correlation",
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            campaign_id=CAMPAIGN_ID,
            orthophoto_asset_ref=str(ORTHO_ID),
            boundary_asset_ref=str(BOUNDARY_V1_ID),
            exclusions_asset_ref=None,
            model_version_ref="model-ci",
            pipeline_config_version="pipeline-ci",
            requested_by_ref="campaign-artifact-ci",
            command_sha256="a" * 64,
            status="succeeded",
            accepted_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.add(
        AnalysisJobAttempt(
            id=ATTEMPT_ID,
            job_id=JOB_ID,
            attempt_number=1,
            status="succeeded",
            worker_ref="worker-ci",
            pipeline_build_ref="pipeline-ci",
            result_sha256="b" * 64,
            queued_at=NOW,
            started_at=NOW,
            finished_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()

    for artifact_id, role, sha, stage, object_key, content_type in (
        (
            REPORT_ID,
            "technical_report",
            REPORT_SHA,
            "generate_technical_report",
            "ci/campaign-artifact/report.pdf",
            "application/pdf",
        ),
        (
            PIPELINE_STATE_ID,
            "pipeline_state",
            PIPELINE_SHA,
            "generate_technical_report",
            "ci/campaign-artifact/pipeline-state.json",
            "application/json",
        ),
        (
            PRIORITY_ID,
            "planting_priority",
            PRIORITY_SHA,
            "prioritize_planting_opportunities",
            "ci/campaign-artifact/priority.gpkg",
            "application/geopackage+sqlite3",
        ),
    ):
        session.add(
            AnalysisArtifact(
                id=artifact_id,
                job_id=JOB_ID,
                attempt_id=ATTEMPT_ID,
                manifest_schema_version="artifact-manifest.v1",
                role=role,
                object_key=object_key,
                content_type=content_type,
                size_bytes=2048,
                sha256=sha,
                produced_by_stage=stage,
                crs=None if content_type == "application/pdf" else "EPSG:32717",
                created_at=NOW,
            )
        )
    session.commit()


def _register(
    session: Session,
    *,
    artifact_type: str,
    source_kind: str,
    source_ref: UUID,
    sha256: str,
    version: int,
    source_revision_id: UUID | None = None,
):
    return DBICampaignArtifactService(session).register_artifact(
        campaign_id=CAMPAIGN_ID,
        tenant_ref=TENANT_REF,
        organization_ref=ORGANIZATION_REF,
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        request=DBICampaignArtifactRegistration(
            artifact_type=artifact_type,
            source_kind=source_kind,
            source_ref=source_ref,
            sha256=sha256,
            version=version,
            source_revision_id=source_revision_id,
        ),
    )


def validate_real_catalog() -> None:
    config = load_dbi_database_config()
    engine = create_engine(config.url)
    try:
        with Session(engine) as session:
            _seed(session)

            ortho, created = _register(
                session,
                artifact_type="orthophoto_source",
                source_kind="input_asset",
                source_ref=ORTHO_ID,
                sha256=ORTHO_SHA,
                version=1,
            )
            session.commit()
            assert created is True
            assert ortho.artifact_type is DBICampaignArtifactType.ORTHOPHOTO_SOURCE
            assert ortho.technical_status is DBICampaignArtifactTechnicalStatus.CURRENT
            assert ortho.published is False
            assert ortho.source_revision_id is None

        with Session(engine) as session:
            replay, created = _register(
                session,
                artifact_type="orthophoto_source",
                source_kind="input_asset",
                source_ref=ORTHO_ID,
                sha256=ORTHO_SHA,
                version=1,
            )
            session.commit()
            assert created is False
            assert replay.campaign_artifact_id == ortho.campaign_artifact_id

        with Session(engine) as session:
            try:
                _register(
                    session,
                    artifact_type="orthophoto_source",
                    source_kind="input_asset",
                    source_ref=ORTHO_ID,
                    sha256="f" * 64,
                    version=1,
                )
            except DBICampaignConflict:
                session.rollback()
            else:
                raise AssertionError("Replay divergente del catálogo no fue rechazado.")

        with Session(engine) as session:
            boundary_v1, created = _register(
                session,
                artifact_type="boundary",
                source_kind="input_asset",
                source_ref=BOUNDARY_V1_ID,
                sha256=BOUNDARY_V1_SHA,
                version=1,
                source_revision_id=REVISION_ID,
            )
            session.commit()
            assert created is True
            assert boundary_v1.source_revision_id == REVISION_ID

        with Session(engine) as session:
            try:
                _register(
                    session,
                    artifact_type="boundary",
                    source_kind="input_asset",
                    source_ref=BOUNDARY_V2_ID,
                    sha256=BOUNDARY_V2_SHA,
                    version=3,
                )
            except DBICampaignConflict:
                session.rollback()
            else:
                raise AssertionError("El catálogo aceptó un salto de versión 1 -> 3.")

        with Session(engine) as session:
            boundary_v2, created = _register(
                session,
                artifact_type="boundary",
                source_kind="input_asset",
                source_ref=BOUNDARY_V2_ID,
                sha256=BOUNDARY_V2_SHA,
                version=2,
            )
            session.commit()
            assert created is True
            assert boundary_v2.technical_status is DBICampaignArtifactTechnicalStatus.CURRENT

        with Session(engine) as session:
            catalog = DBICampaignArtifactReader(session).list_artifacts(
                campaign_id=CAMPAIGN_ID,
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            )
            boundaries = [item for item in catalog if item.artifact_type is DBICampaignArtifactType.BOUNDARY]
            assert [item.version for item in boundaries] == [1, 2]
            assert boundaries[0].technical_status is DBICampaignArtifactTechnicalStatus.SUPERSEDED
            assert boundaries[1].technical_status is DBICampaignArtifactTechnicalStatus.CURRENT
            assert all(item.published is False for item in catalog)

            report, created = _register(
                session,
                artifact_type="technical_report",
                source_kind="analysis_artifact",
                source_ref=REPORT_ID,
                sha256=REPORT_SHA,
                version=1,
            )
            session.commit()
            assert created is True
            assert report.source_ref == REPORT_ID

        with Session(engine) as session:
            try:
                _register(
                    session,
                    artifact_type="technical_report",
                    source_kind="analysis_artifact",
                    source_ref=PIPELINE_STATE_ID,
                    sha256=PIPELINE_SHA,
                    version=2,
                )
            except DBICampaignUnavailable:
                session.rollback()
            else:
                raise AssertionError("pipeline_state fue catalogado como producto técnico.")

        with Session(engine) as session:
            try:
                _register(
                    session,
                    artifact_type="planting_candidates",
                    source_kind="analysis_artifact",
                    source_ref=PRIORITY_ID,
                    sha256=PRIORITY_SHA,
                    version=1,
                )
            except DBICampaignConflict:
                session.rollback()
            else:
                raise AssertionError("CANDIDATE fue confundido con operational_priority.")

        with Session(engine) as session:
            try:
                _register(
                    session,
                    artifact_type="sampling_plan",
                    source_kind="domain_record",
                    source_ref=REVISION_ID,
                    sha256="7" * 64,
                    version=1,
                )
            except DBICampaignUnavailable:
                session.rollback()
            else:
                raise AssertionError("domain_record futuro fue aceptado antes de su integración.")

        with Session(engine) as session:
            try:
                DBICampaignArtifactReader(session).list_artifacts(
                    campaign_id=CAMPAIGN_ID,
                    tenant_ref="tenant_incorrecto",
                    organization_ref=ORGANIZATION_REF,
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                )
            except DBICampaignUnavailable:
                pass
            else:
                raise AssertionError("El catálogo filtró información fuera de tenant.")
    finally:
        engine.dispose()


def main() -> None:
    _require_ephemeral_ci()
    validate_real_catalog()
    print("Campaign artifact catalog: persistencia, versiones, scope y aislamiento aprobados.")


if __name__ == "__main__":
    main()
