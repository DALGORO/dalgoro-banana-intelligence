"""Pruebas PostGIS del vínculo exacto Campaign MULTI–INSPECT.

Solo se ejecuta en CI efímera DESPUÉS del fixture INSPECT y utiliza el servicio de main (#218). No aprueba firmas,
no habilita publicación y no hace cambios fuera de dbi_test.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIAccessDenied, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.inspection.campaign_link_service import (  # noqa: E402
    DBIInspectionCampaignLinkService, DBIInspectionCampaignLinkUnavailable,
)
from app.dbi.models.inspection_campaign import DBIInspectionCampaignLinkRecord  # noqa: E402
from app.dbi.inspection.repository import DBIInspectionConflict  # noqa: E402

HOST = "127.0.0.1"
DB = "dbi_test"
ROLE = "dbi_test_inspection"
TENANT = "tenant-inspect-ci"
ORG = "organization-inspect-ci"
FARM = UUID("10000000-0000-4000-8000-000000000079")
PLOT = UUID("20000000-0000-4000-8000-000000000079")
OBS = UUID("60000000-0000-4000-8000-000000000079")
OLD = UUID("70000000-0000-4000-8000-000000000079")
LATEST = UUID("70000000-0000-4000-8000-000000000080")
MULTI = UUID("80000000-0000-4000-8000-000000000079")
SECOND = UUID("80000000-0000-4000-8000-000000000080")
DENSITY = UUID("80000000-0000-4000-8000-000000000081")


def _scope() -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DBI_ENVIRONMENT") != "test"
        or os.environ.get("DBI_INSPECT_LINK_RUN_INTEGRATION") != "1"
    ):
        raise RuntimeError("Prohibido fuera de CI efímera DBI.")
    url = os.environ.get("DBI_DATABASE_URL", "")
    if ROLE not in url or HOST not in url or DB not in url:
        raise RuntimeError("DBI_DATABASE_URL no pertenece al rol INSPECT de CI.")


def _actor(*, tenant=TENANT, permissions=None, plot=PLOT):
    allowed = permissions if permissions is not None else {DBIPermission.READ, DBIPermission.WRITE}
    return DBIAccessContext(
        principal_ref="technical-inspect-ci",
        tenant_ref=tenant,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset({DBIFarmScope(ORG, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORG, FARM, plot)}),
        permissions=frozenset(allowed),
    )


def _expect_denied(fn, *errors):
    try:
        fn()
    except errors:
        pass
    else:
        raise AssertionError("INSPECT–Campaign debía rechazar esta asociación.")


def _provision() -> None:
    with psycopg.connect(
        host=HOST, dbname=DB, user="postgres", autocommit=True, connect_timeout=10,
    ) as admin:
        with admin.cursor() as cur:
            for name in ("dbi_campaigns", "dbi_inspect_campaign_links"):
                cur.execute(
                    sql.SQL("GRANT SELECT ON dbi.{} TO {}").format(
                        sql.Identifier(name), sql.Identifier(ROLE),
                    )
                )
            cur.execute(
                sql.SQL("GRANT INSERT ON dbi.dbi_inspect_campaign_links TO {}").format(
                    sql.Identifier(ROLE),
                )
            )
            for id, code, kind, status in (
                (MULTI, "CI-MULTI-LINK-79", "multispectral", "FIELD_WORK"),
                (SECOND, "CI-MULTI-LINK-80", "multispectral", "FIELD_WORK"),
                (DENSITY, "CI-DENSITY-LINK-81", "density", "FIELD_WORK"),
            ):
                cur.execute(
                    """INSERT INTO dbi.dbi_campaigns
                       (id, tenant_ref, organization_ref, farm_id, plot_id,
                        code, name, analysis_type, captured_at, starts_at,
                        status, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
                               TIMESTAMPTZ '2026-09-05 15:00:00+00',
                               TIMESTAMPTZ '2026-09-05 15:00:00+00',
                               %s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                       ON CONFLICT (id) DO NOTHING""",
                    (id, TENANT, ORG, FARM, PLOT, code, code, kind, status),
                )


def _validate() -> None:
    engine = create_engine(
        f"postgresql+psycopg://{ROLE}@{HOST}:5432/{DB}",
        poolclass=NullPool, future=True,
    )
    try:
        with Session(engine) as session:
            service = DBIInspectionCampaignLinkService(session)
            def link(*, actor=None, campaign=MULTI, version=LATEST):
                return service.propose_link(
                    actor or _actor(), tenant_ref=TENANT,
                    organization_ref=ORG, farm_id=FARM, plot_id=PLOT,
                    campaign_id=campaign, observation_id=OBS,
                    observation_version_id=version,
                )

            _expect_denied(
                lambda: link(actor=_actor(permissions={DBIPermission.READ})), DBIAccessDenied,
            )
            # WRITE scoped es el permiso de trabajo autorizado por el servicio.
            # El servicio no exige READ adicional al personal que registra vínculo.
            _expect_denied(
                lambda: link(actor=_actor(tenant="tenant-other")), DBIAccessDenied,
            )
            _expect_denied(
                lambda: link(actor=_actor(plot=UUID("20000000-0000-4000-8000-000000000080"))),
                DBIAccessDenied,
            )
            _expect_denied(lambda: link(campaign=DENSITY), DBIInspectionCampaignLinkUnavailable)
            _expect_denied(lambda: link(version=OLD), DBIInspectionConflict)

            first, created = link()
            assert created is True
            assert first.observation_version_id == LATEST
            assert first.campaign_id == MULTI
            replay, created = link()
            assert created is False
            assert replay.id == first.id
            _expect_denied(
                lambda: link(campaign=SECOND), DBIInspectionConflict,
            )
            count = session.scalar(
                select(func.count(DBIInspectionCampaignLinkRecord.id)).where(
                    DBIInspectionCampaignLinkRecord.observation_id == OBS
                )
            )
            assert count == 1
            session.commit()

        with Session(engine) as session:
            stored = session.scalar(
                select(DBIInspectionCampaignLinkRecord).where(
                    DBIInspectionCampaignLinkRecord.observation_version_id == LATEST
                )
            )
            assert stored is not None
            assert stored.tenant_ref == TENANT
            assert stored.organization_ref == ORG
            assert stored.campaign_analysis_type == "multispectral"
            assert stored.linked_by_ref == "technical-inspect-ci"
    finally:
        engine.dispose()


if __name__ == "__main__":
    _scope()
    _provision()
    _validate()
    print("OK: Campaign–INSPECT scoped, vigente e idempotente; sin firmas ni publicación.")
