"""Contrato offline del vínculo técnico INSPECT→Campaign; sin PostGIS/producción."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIAccessDenied, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.inspection.campaign_link_service import (  # noqa: E402
    DBIInspectionCampaignLinkService, DBIInspectionCampaignLinkUnavailable,
)
from app.dbi.inspection.repository import DBIInspectionConflict  # noqa: E402
from app.dbi.models.inspection_campaign import (  # noqa: E402
    DBIInspectionCampaignLinkRecord,
)

FARM = UUID("10000000-0000-4000-8000-000000000281")
PLOT = UUID("20000000-0000-4000-8000-000000000281")
CAMPAIGN = UUID("30000000-0000-4000-8000-000000000281")
OBS = UUID("40000000-0000-4000-8000-000000000281")
VERSION = UUID("50000000-0000-4000-8000-000000000281")
OLDER = UUID("50000000-0000-4000-8000-000000000280")


def access(perms: set[DBIPermission], *, tenant: str = "tenant-281",
           plot: UUID = PLOT) -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="tech-281",
        tenant_ref=tenant,
        organization_refs=frozenset({"org-281"}),
        farm_scopes=frozenset({DBIFarmScope("org-281", FARM)}),
        plot_scopes=frozenset({DBIPlotScope("org-281", FARM, plot)}),
        permissions=frozenset(perms),
    )


def call(service, context, **changes):
    args = dict(
        organization_ref="org-281", farm_id=FARM, plot_id=PLOT,
        campaign_id=CAMPAIGN, observation_id=OBS,
        observation_version_id=VERSION,
    )
    args.update(changes)
    return service.propose_link(context, **args)


def forbidden(fn, error):
    try:
        fn()
    except error:
        return
    raise AssertionError("Se esperaba denegación de vínculo INSPECT.")


def fixture(campaign=True, observation=True, version=VERSION,
            kind="observed", linked=None):
    session = Session()
    campaign_row = SimpleNamespace(id=CAMPAIGN) if campaign else None
    observation_row = SimpleNamespace(id=OBS) if observation else None
    version_row = (
        SimpleNamespace(id=version, evidence_kind=kind)
        if version is not None else None
    )
    returns = (campaign_row, observation_row, version_row, linked)
    results = [SimpleNamespace(scalar_one_or_none=lambda value=v: value)
               for v in returns]
    session_execute = MagicMock(side_effect=results)
    session_add = MagicMock()
    session_flush = MagicMock()
    p1 = patch.object(session, "execute", session_execute)
    p2 = patch.object(session, "add", session_add)
    p3 = patch.object(session, "flush", session_flush)
    p1.start()
    p2.start()
    p3.start()
    return session, (p1, p2, p3), session_execute, session_add, session_flush


def validate() -> None:
    context = access({DBIPermission.READ, DBIPermission.WRITE})
    session, patches, ex, added, flushed = fixture()
    try:
        service = DBIInspectionCampaignLinkService(session)
        forbidden(lambda: call(service, access({DBIPermission.READ})), DBIAccessDenied)
        forbidden(lambda: call(
            service, access({DBIPermission.WRITE}, tenant="other-tenant")
        ), DBIAccessDenied)
        forbidden(lambda: call(
            service, access({DBIPermission.WRITE}, plot=OLDER)
        ), DBIAccessDenied)
        assert ex.call_count == 0
        link, created = call(service, context)
        assert created is True
        assert isinstance(link, DBIInspectionCampaignLinkRecord)
        assert (link.tenant_ref, link.organization_ref, link.farm_id, link.plot_id) == (
            "tenant-281", "org-281", FARM, PLOT
        )
        assert link.campaign_id == CAMPAIGN
        assert link.observation_id == OBS
        assert link.observation_version_id == VERSION
        assert link.linked_by_ref == "tech-281"
        assert added.call_count == 1 and flushed.call_count == 1
        sql = [str(item.args[0]) for item in ex.call_args_list]
        assert "dbi_campaigns.tenant_ref" in sql[0]
        assert "dbi_campaigns.organization_ref" in sql[0]
        assert "dbi_campaigns.analysis_type" in sql[0]
        assert "dbi_field_observations.tenant_ref" in sql[1]
        assert "dbi_field_observations.organization_ref" in sql[1]
        assert "FOR UPDATE" in str(
            ex.call_args_list[1].args[0].compile(
                dialect=__import__("sqlalchemy").dialects.postgresql.dialect()
            )
        )
        assert "dbi_field_observation_versions.version DESC" in sql[2]
    finally:
        for p in reversed(patches): p.stop()
        session.close()

    for config, error in (
        (dict(campaign=False), DBIInspectionCampaignLinkUnavailable),
        (dict(observation=False), DBIInspectionCampaignLinkUnavailable),
        (dict(version=OLDER), DBIInspectionConflict),
        (dict(version=None), DBIInspectionConflict),
        (dict(kind="derived"), DBIInspectionConflict),
        (dict(linked=SimpleNamespace(
            tenant_ref="tenant-281", organization_ref="org-281",
            farm_id=FARM, plot_id=PLOT,
            campaign_id=OLDER, observation_id=OBS,
            observation_version_id=VERSION,
        )), DBIInspectionConflict),
    ):
        session, patches, _ex, added, flushed = fixture(**config)
        try:
            forbidden(lambda: call(DBIInspectionCampaignLinkService(session), context), error)
            assert added.call_count == 0 and flushed.call_count == 0
        finally:
            for p in reversed(patches): p.stop()
            session.close()

    linked = SimpleNamespace(
        tenant_ref="tenant-281", organization_ref="org-281",
        farm_id=FARM, plot_id=PLOT,
        campaign_id=CAMPAIGN, observation_id=OBS,
        observation_version_id=VERSION,
    )
    session, patches, _ex, added, flushed = fixture(linked=linked)
    try:
        row, created = call(DBIInspectionCampaignLinkService(session), context)
        assert row is linked and created is False
        assert added.call_count == 0 and flushed.call_count == 0
    finally:
        for p in reversed(patches): p.stop()
        session.close()


if __name__ == "__main__":
    validate()
    print("OK: asociación exacta por Campaign y versión, scope WRITE, idempotencia.")
