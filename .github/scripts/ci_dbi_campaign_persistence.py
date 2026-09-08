"""Prueba real del dominio Campaign contra el PostGIS efímero de CI."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_config import load_dbi_database_config  # noqa: E402
from app.dbi.campaigns.contracts import (  # noqa: E402
    DBICampaignConflict,
    DBICampaignCreate,
    DBICampaignStatus,
    DBICampaignUnavailable,
)
from app.dbi.campaigns.reader import DBICampaignReader  # noqa: E402
from app.dbi.campaigns.service import DBICampaignService  # noqa: E402
from app.dbi.models import Farm, Plot  # noqa: E402

FARM_ID = UUID("10000000-0000-4000-8000-000000000019")
PLOT_ID = UUID("20000000-0000-4000-8000-000000000019")
CAMPAIGN_ID = UUID("30000000-0000-4000-8000-000000000019")
TENANT_REF = "tenant_campaign_ci"
ORGANIZATION_REF = "organization_campaign_ci"
CAPTURED_AT = datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc)


def _require_ephemeral_ci() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Campaign persistence solo puede ejecutarse en GitHub Actions.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("Campaign persistence exige DBI_ENVIRONMENT=test.")

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
            "Campaign persistence no apunta al fixture PostgreSQL efímero autorizado."
        )


def _seed_scope(session: Session) -> None:
    session.add(
        Farm(
            id=FARM_ID,
            organization_ref=ORGANIZATION_REF,
            code="campaign-ci-farm",
            name="Campaign CI Farm",
            status="active",
        )
    )
    session.add(
        Plot(
            id=PLOT_ID,
            farm_id=FARM_ID,
            code="campaign-ci-plot",
            name="Campaign CI Plot",
            status="active",
        )
    )
    session.commit()


def _create_request(*, captured_at: datetime = CAPTURED_AT) -> DBICampaignCreate:
    return DBICampaignCreate(
        campaign_id=CAMPAIGN_ID,
        analysis_type="density",
        captured_at=captured_at,
    )


def validate_real_persistence() -> None:
    config = load_dbi_database_config()
    engine = create_engine(config.url)
    try:
        with Session(engine) as session:
            _seed_scope(session)

            service = DBICampaignService(session)
            snapshot, created = service.create_campaign(
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                request=_create_request(),
            )
            session.commit()

            assert created is True
            assert snapshot.campaign_id == CAMPAIGN_ID
            assert snapshot.status is DBICampaignStatus.DRAFT
            assert snapshot.analysis_type.value == "density"
            assert snapshot.farm_id == FARM_ID
            assert snapshot.plot_id == PLOT_ID
            assert snapshot.source_job_id is None

        with Session(engine) as session:
            reader = DBICampaignReader(session)
            persisted = reader.read_campaign(
                campaign_id=CAMPAIGN_ID,
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            )
            assert persisted.campaign_id == CAMPAIGN_ID
            assert persisted.captured_at == CAPTURED_AT

            replay, created = DBICampaignService(session).create_campaign(
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                request=_create_request(),
            )
            session.commit()
            assert created is False
            assert replay.campaign_id == CAMPAIGN_ID

        with Session(engine) as session:
            try:
                DBICampaignService(session).create_campaign(
                    tenant_ref=TENANT_REF,
                    organization_ref=ORGANIZATION_REF,
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                    request=_create_request(
                        captured_at=CAPTURED_AT + timedelta(minutes=1)
                    ),
                )
            except DBICampaignConflict:
                session.rollback()
            else:
                raise AssertionError("Replay divergente no fue rechazado.")

        with Session(engine) as session:
            try:
                DBICampaignReader(session).read_campaign(
                    campaign_id=CAMPAIGN_ID,
                    tenant_ref="tenant_incorrecto",
                    organization_ref=ORGANIZATION_REF,
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                )
            except DBICampaignUnavailable:
                pass
            else:
                raise AssertionError("Lectura fuera de tenant no fue ocultada.")

            processing = DBICampaignService(session).transition_campaign(
                campaign_id=CAMPAIGN_ID,
                tenant_ref=TENANT_REF,
                organization_ref=ORGANIZATION_REF,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                target_status=DBICampaignStatus.PROCESSING,
            )
            session.commit()
            assert processing.status is DBICampaignStatus.PROCESSING

        with Session(engine) as session:
            try:
                DBICampaignService(session).transition_campaign(
                    campaign_id=CAMPAIGN_ID,
                    tenant_ref=TENANT_REF,
                    organization_ref=ORGANIZATION_REF,
                    farm_id=FARM_ID,
                    plot_id=PLOT_ID,
                    target_status=DBICampaignStatus.PUBLISHED,
                )
            except DBICampaignConflict:
                session.rollback()
            else:
                raise AssertionError("Salto PROCESSING -> PUBLISHED no fue rechazado.")
    finally:
        engine.dispose()


def main() -> None:
    _require_ephemeral_ci()
    validate_real_persistence()
    print("Campaign DBI: persistencia, lectura e idempotencia real aprobadas.")


if __name__ == "__main__":
    main()
