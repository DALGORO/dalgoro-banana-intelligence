"""Pruebas de firmas para vínculo Campaign–INSPECT existente, sin DB ni API.

Mock de sesión para probar orden de locks, permiso, correcciones, firmas y
resistencia a usar campañas sin trazabilidad verificada. Integración PostgreSQL
de operaciones se añade antes de activar API/producción.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIAccessDenied, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.inspection.campaign_approval_service import (  # noqa: E402
    DBIInspectionCampaignApprovalService,
)
from app.dbi.inspection.dual_approval import DBIInspectionApprovalConflict  # noqa: E402
from app.dbi.models.inspection_campaign import (  # noqa: E402
    DBIInspectionApprovalEventRecord, DBIInspectionCampaignLinkRecord,
)

FARM = UUID("10000000-0000-4000-8000-000000000165")
PLOT = UUID("20000000-0000-4000-8000-000000000165")
CAMPAIGN = UUID("30000000-0000-4000-8000-000000000165")
OTHER_CAMPAIGN = UUID("30000000-0000-4000-8000-000000000166")
OBS = UUID("40000000-0000-4000-8000-000000000165")
VERSION = UUID("50000000-0000-4000-8000-000000000165")
NEW_VERSION = UUID("50000000-0000-4000-8000-000000000166")
LINK = UUID("60000000-0000-4000-8000-000000000165")
NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def principal(who, permissions, *, tenant="tenant-approval", plot=PLOT):
    return DBIAccessContext(
        principal_ref=who,
        tenant_ref=tenant,
        organization_refs=frozenset({"org-approval"}),
        farm_scopes=frozenset({DBIFarmScope("org-approval", FARM)}),
        plot_scopes=frozenset({DBIPlotScope("org-approval", FARM, plot)}),
        permissions=frozenset(permissions),
    )


TECH = principal("tech-one", {DBIPermission.READ, DBIPermission.WRITE})
ADMIN = principal("admin-two", {
    DBIPermission.READ, DBIPermission.MANAGE, DBIPermission.APPROVE_AGRONOMIC,
})
CLIENT = principal("client-three", {DBIPermission.READ})


def params(**other):
    return dict(organization_ref="org-approval", farm_id=FARM, plot_id=PLOT, **other)


def result(*, scalar=None, one=None, many=None):
    answer = MagicMock()
    answer.scalar_one_or_none.return_value = scalar
    answer.one_or_none.return_value = one
    answer.scalars.return_value.all.return_value = [] if many is None else many
    return answer


def fixture(*, versions=None, events=None, existing=None):
    link = DBIInspectionCampaignLinkRecord(
        id=LINK, tenant_ref="tenant-approval", organization_ref="org-approval",
        farm_id=FARM, plot_id=PLOT, campaign_id=CAMPAIGN,
        campaign_analysis_type="multispectral", observation_id=OBS,
        observation_version_id=VERSION, linked_by_ref="tech-one",
    )
    observation = MagicMock()
    observation.id = OBS
    latest = MagicMock()
    latest.id = VERSION if versions is None else versions
    latest.evidence_kind = "observed"
    campaign = MagicMock()
    campaign.id = CAMPAIGN
    campaign.analysis_type = "multispectral"
    campaign.captured_at = NOW
    technical = DBIInspectionApprovalEventRecord(
        link_id=LINK, event_kind="technical_validated",
        actor_ref="tech-one", decided_at=NOW,
    )
    admin = DBIInspectionApprovalEventRecord(
        link_id=LINK, event_kind="administrative_authorized",
        actor_ref="admin-two", decided_at=NOW,
    )
    included = [] if events is None else [
        technical if e == "tech" else admin for e in events
    ]
    session = MagicMock(spec=Session)
    def bind(*values):
        session.execute.side_effect = list(values)
    service = DBIInspectionCampaignApprovalService(session)
    return service, session, link, observation, latest, campaign, included, bind


def denied(callback, exception):
    try:
        callback()
    except exception:
        return
    raise AssertionError(f"Se esperaba denegación {exception.__name__}.")


def bind_for_signatures(bind, link, observation, latest, events):
    bind(
        result(one=(OBS, VERSION)),
        result(scalar=observation),
        result(scalar=latest),
        result(scalar=link),
        result(many=events),
    )


def verify_signatures():
    service, session, link, observation, latest, campaign, events, bind = fixture()
    denied(
        lambda: service.validate_technical(
            CLIENT, **params(link_id=LINK)
        ), DBIAccessDenied,
    )
    session.execute.assert_not_called()
    bind_for_signatures(bind, link, observation, latest, [])
    validated = service.validate_technical(TECH, **params(link_id=LINK))
    assert validated.stage == "technical_validated"
    inserted = session.add.call_args.args[0]
    assert inserted.event_kind == "technical_validated"
    assert inserted.actor_ref == "tech-one"
    session.flush.assert_called_once()

    # La segunda firma exige técnico previo.
    session.reset_mock()
    bind_for_signatures(bind, link, observation, latest, [])
    denied(
        lambda: service.authorize_administrative(
            ADMIN, **params(link_id=LINK)
        ), DBIInspectionApprovalConflict,
    )
    session.add.assert_not_called()

    # Si no existe cadena espectral científica verificable: denegar firma.
    session.reset_mock()
    technical = DBIInspectionApprovalEventRecord(
        link_id=LINK, event_kind="technical_validated",
        actor_ref="tech-one", decided_at=NOW,
    )
    bind_for_signatures(bind, link, observation, latest, [technical])
    with patch.object(service, "_verified_scientific_chain", return_value=False):
        denied(
            lambda: service.authorize_administrative(
                ADMIN, **params(link_id=LINK)
            ), DBIInspectionApprovalConflict,
        )
    session.add.assert_not_called()

    # Dos firmas registradas en filas distintas, sin UPDATE de INSPECT.
    session.reset_mock()
    bind_for_signatures(bind, link, observation, latest, [technical])
    with patch.object(service, "_verified_scientific_chain", return_value=True):
        approved = service.authorize_administrative(
            ADMIN, **params(link_id=LINK)
        )
    assert approved.stage == "dual_approved"
    assert approved.technical_by == "tech-one"
    assert approved.administrative_by == "admin-two"
    recorded = session.add.call_args.args[0]
    assert recorded.event_kind == "administrative_authorized"
    assert recorded.actor_ref == "admin-two"
    assert recorded.link_id == LINK
    session.flush.assert_called_once()

    # Mismo actor con ambos permisos nunca firma dos veces.
    same = principal("tech-one", {
        DBIPermission.WRITE, DBIPermission.APPROVE_AGRONOMIC, DBIPermission.MANAGE,
    })
    session.reset_mock()
    bind_for_signatures(bind, link, observation, latest, [technical])
    with patch.object(service, "_verified_scientific_chain", return_value=True):
        denied(
            lambda: service.authorize_administrative(
                same, **params(link_id=LINK)
            ), DBIInspectionApprovalConflict,
        )
    session.add.assert_not_called()

    # Un SOLO clic admin+técnico crea ambos eventos auditables en
    # una transacción y con el MISMO UUID de principal (no finge dos personas).
    session.reset_mock()
    bind_for_signatures(bind, link, observation, latest, [])
    with patch.object(service, "_verified_scientific_chain", return_value=True):
        one_action = service.authorize_administrative(
            same, **params(link_id=LINK), _staff_dual_role_verified=True,
        )
    assert one_action.stage == "self_approved"
    assert one_action.administrative_by == one_action.technical_by == "tech-one"
    assert session.add.call_count == 2
    events_one_action = [call.args[0] for call in session.add.call_args_list]
    assert [e.event_kind for e in events_one_action] == [
        "technical_validated", "administrative_authorized",
    ]
    assert all(e.actor_ref == "tech-one" for e in events_one_action)
    assert events_one_action[0].decided_at == events_one_action[1].decided_at
    session.flush.assert_called_once()

    # Si ese actor validó antes como técnico, sólo se registra el acto admin.
    session.reset_mock()
    bind_for_signatures(bind, link, observation, latest, [technical])
    with patch.object(service, "_verified_scientific_chain", return_value=True):
        self_after_technical = service.authorize_administrative(
            same, **params(link_id=LINK), _staff_dual_role_verified=True,
        )
    assert self_after_technical.stage == "self_approved"
    session.add.assert_called_once()
    assert session.add.call_args.args[0].event_kind == "administrative_authorized"

    # Sin la procedencia MULTI no se registran eventos en modo unipersonal.
    session.reset_mock()
    bind_for_signatures(bind, link, observation, latest, [])
    with patch.object(service, "_verified_scientific_chain", return_value=False):
        denied(
            lambda: service.authorize_administrative(
                same, **params(link_id=LINK), _staff_dual_role_verified=True,
            ), DBIInspectionApprovalConflict,
        )
    session.add.assert_not_called()

    # El administrador necesita AMBOS privilegios scoped.
    for permissions in ({DBIPermission.MANAGE}, {DBIPermission.APPROVE_AGRONOMIC}):
        session.reset_mock()
        denied(
            lambda permissions=permissions: service.authorize_administrative(
                principal("admin-two", permissions), **params(link_id=LINK)
            ), DBIAccessDenied,
        )
        session.execute.assert_not_called()

    # Una corrección vuelve obsoleta la versión del vínculo original.
    session.reset_mock()
    latest.id = NEW_VERSION
    bind(
        result(one=(OBS, VERSION)), result(scalar=observation),
        result(scalar=latest),
    )
    denied(
        lambda: service.authorize_administrative(
            ADMIN, **params(link_id=LINK)
        ), DBIInspectionApprovalConflict,
    )


def verify_server_only_provenance():
    service, session, link, *_ = fixture()
    extraction = UUID("70000000-0000-4000-8000-000000000165")
    session.execute.return_value = result(many=[extraction])
    with patch(
        "app.dbi.inspection.campaign_approval_service."
        "DBIMultispectralExtractionRepository"
    ) as repo:
        repo.return_value.campaign_provenance_by_extraction_scoped.return_value = {
            extraction: (CAMPAIGN, NOW),
        }
        assert service._verified_scientific_chain(link)
        assert repo.return_value.campaign_provenance_by_extraction_scoped.call_args.kwargs[
            "tenant_ref"
        ] == "tenant-approval"
        repo.return_value.campaign_provenance_by_extraction_scoped.return_value = {
            extraction: (OTHER_CAMPAIGN, NOW),
        }
        assert not service._verified_scientific_chain(link)
    session.execute.return_value = result(many=[])
    assert not service._verified_scientific_chain(link)


if __name__ == "__main__":
    verify_signatures()
    verify_server_only_provenance()
    print("OK: INSPECT con dos actores o autoaprobación institucional, sin API.")
