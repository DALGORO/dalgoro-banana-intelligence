"""INSPECT: lectura fail-closed por Campaign y dos firmas, sin red ni datos reales."""
from __future__ import annotations

import sys
from dataclasses import fields
from datetime import datetime, timezone
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
from app.dbi.inspection.dual_approval import DBIInspectionApprovalState  # noqa: E402
from app.dbi.inspection.published_read_service import (  # noqa: E402
    DBIApprovedInspectionSummary,
    DBIInspectionPublishedReadService,
    DBIInspectionPublishedUnavailable,
)
from app.dbi.inspection.repository import sha256_text  # noqa: E402
from app.dbi.inspection.contracts import DBIFieldObservationPayload  # noqa: E402
from app.dbi.inspection.campaign_approval_service import (  # noqa: E402
    DBIInspectionCampaignApprovalService,
)

FARM = UUID("10000000-0000-4000-8000-000000000241")
PLOT = UUID("20000000-0000-4000-8000-000000000241")
CAMPAIGN = UUID("30000000-0000-4000-8000-000000000241")
OBS = UUID("40000000-0000-4000-8000-000000000241")
VERSION = UUID("50000000-0000-4000-8000-000000000241")
NEW_VERSION = UUID("50000000-0000-4000-8000-000000000242")
NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)

def access(perms, *, tenant="tenant-241", plot=PLOT):
    return DBIAccessContext(
        principal_ref="client-241", tenant_ref=tenant,
        organization_refs=frozenset({"org-241"}),
        farm_scopes=frozenset({DBIFarmScope("org-241", FARM)}),
        plot_scopes=frozenset({DBIPlotScope("org-241", FARM, plot)}),
        permissions=frozenset(perms),
    )

CLIENT = access({DBIPermission.READ})
REQ = dict(
    organization_ref="org-241", farm_id=FARM, plot_id=PLOT,
    campaign_id=CAMPAIGN, observation_id=OBS,
)

def value(item):
    return SimpleNamespace(scalar_one_or_none=lambda: item)

def field(state="observed", number=1):
    return SimpleNamespace(state=state, value=number)

def sample_payload():
    return SimpleNamespace(
        tenant_ref="tenant-241", organization_ref="org-241",
        farm_id=FARM, plot_id=PLOT, evidence_kind="observed",
        observed_at=NOW, up_id=None, sampling_point_id=None,
        operator_ref="private-operator",
        core=SimpleNamespace(
            foure=field("observed", 2), yls=field("not_measured", None),
            functional_leaves=field("observed", 8),
            general_photo="PRIVATE_PHOTO", note="PRIVATE_NOTE",
        ),
    )

def approved_state():
    return DBIInspectionApprovalState(
        tenant_ref="tenant-241", organization_ref="org-241",
        farm_id=FARM, plot_id=PLOT, campaign_id=CAMPAIGN,
        observation_id=OBS, observation_version_id=VERSION,
        technical_by="tech-241", technical_at=NOW,
        administrative_by="admin-241", administrative_at=NOW,
    )

def session_fixture(*, campaign=True, link=True, latest_version=VERSION,
                    observed=True, digest_ok=True):
    row_campaign = SimpleNamespace(id=CAMPAIGN) if campaign else None
    row_link = SimpleNamespace(
        id=UUID("60000000-0000-4000-8000-000000000241"),
        tenant_ref="tenant-241", organization_ref="org-241",
        farm_id=FARM, plot_id=PLOT, campaign_id=CAMPAIGN,
        observation_id=OBS, observation_version_id=VERSION,
    ) if link else None
    payload_json = '{"synthetic":"test"}'
    row_latest = SimpleNamespace(
        id=latest_version, observation_id=OBS,
        evidence_kind="observed" if observed else "derived",
        payload_json=payload_json,
        payload_sha256=sha256_text(payload_json) if digest_ok else "0" * 64,
        observed_at=NOW, up_id=None, sampling_point_id=None,
    ) if latest_version else None
    session = MagicMock(spec=Session)
    session.execute.side_effect = [value(row_campaign), value(row_link), value(row_latest)]
    return DBIInspectionPublishedReadService(session), session

def denied(fn, error=DBIInspectionPublishedUnavailable):
    try:
        fn()
    except error:
        return
    raise AssertionError("Se esperaba rechazo fail-closed.")

def get(service, user=CLIENT):
    return service.get_approved(user, **REQ)

def validate() -> None:
    # READ es obligatorio, incluso antes de consultar la base de datos.
    service, session = session_fixture()
    denied(lambda: get(service, access({DBIPermission.WRITE})), DBIAccessDenied)
    # El tenant procede de la identidad autenticada; la consulta SQL se
    # filtra por él. El mock de DB simula ausencia en ese tenant, no denegación
    # RBAC por el mero hecho de que el tenant sea diferente del fixture.
    foreign_service, _foreign_session = session_fixture(campaign=False)
    denied(lambda: get(foreign_service, access({DBIPermission.READ}, tenant="another")))
    denied(lambda: get(service, access({DBIPermission.READ}, plot=NEW_VERSION)), DBIAccessDenied)
    session.execute.assert_not_called()

    for options in (
        dict(campaign=False), dict(link=False),
        dict(latest_version=NEW_VERSION), dict(latest_version=None),
        dict(observed=False),
    ):
        service, session = session_fixture(**options)
        denied(lambda: get(service))
        assert session.execute.call_count <= 3

    # Pasa a verificar firmas solo después de asegurar Campaign/versión exacta.
    for state in (
        DBIInspectionApprovalState(
            tenant_ref="tenant-241", organization_ref="org-241",
            farm_id=FARM, plot_id=PLOT, campaign_id=CAMPAIGN,
            observation_id=OBS, observation_version_id=VERSION,
        ),
        DBIInspectionApprovalState(
            tenant_ref="tenant-241", organization_ref="org-241",
            farm_id=FARM, plot_id=PLOT, campaign_id=CAMPAIGN,
            observation_id=OBS, observation_version_id=VERSION,
            technical_by="tech-241", technical_at=NOW,
        ),
    ):
        service, session = session_fixture()
        with patch.object(DBIInspectionCampaignApprovalService, "_state", return_value=state), \
             patch.object(DBIInspectionCampaignApprovalService, "_verified_scientific_chain") as chain:
            denied(lambda: get(service))
            chain.assert_not_called()

    service, session = session_fixture()
    with patch.object(DBIInspectionCampaignApprovalService, "_state", return_value=approved_state()), \
         patch.object(DBIInspectionCampaignApprovalService, "_verified_scientific_chain", return_value=False):
        denied(lambda: get(service))

    # Aprobación unipersonal válida: un solo administrador con ambos cargos
    # produce dos eventos bajo una sola acción; publicación conserva demás filtros.
    self_state = DBIInspectionApprovalState(
        tenant_ref="tenant-241", organization_ref="org-241",
        farm_id=FARM, plot_id=PLOT, campaign_id=CAMPAIGN,
        observation_id=OBS, observation_version_id=VERSION,
        technical_by="owner-241", technical_at=NOW,
        administrative_by="owner-241", administrative_at=NOW,
    )
    service, session = session_fixture()
    with patch.object(
        DBIInspectionCampaignApprovalService, "_state",
        return_value=self_state,
    ), patch.object(
        DBIInspectionCampaignApprovalService, "_verified_scientific_chain",
        return_value=True,
    ), patch.object(
        DBIFieldObservationPayload, "model_validate_json",
        return_value=sample_payload(),
    ):
        assert get(service).version_id == VERSION
    service, session = session_fixture()
    with patch.object(
        DBIInspectionCampaignApprovalService, "_state",
        return_value=self_state,
    ), patch.object(
        DBIInspectionCampaignApprovalService, "_verified_scientific_chain",
        return_value=False,
    ):
        denied(lambda: get(service))

    service, session = session_fixture(digest_ok=False)
    with patch.object(DBIInspectionCampaignApprovalService, "_state", return_value=approved_state()), \
         patch.object(DBIInspectionCampaignApprovalService, "_verified_scientific_chain", return_value=True):
        denied(lambda: get(service))

    service, session = session_fixture()
    with patch.object(DBIInspectionCampaignApprovalService, "_state", return_value=approved_state()), \
         patch.object(DBIInspectionCampaignApprovalService, "_verified_scientific_chain", return_value=True), \
         patch.object(DBIFieldObservationPayload, "model_validate_json", return_value=sample_payload()):
        approved = get(service)
    assert isinstance(approved, DBIApprovedInspectionSummary)
    assert (approved.campaign_id, approved.observation_id, approved.version_id) == (
        CAMPAIGN, OBS, VERSION
    )
    assert (approved.foure_state, approved.foure_value) == ("observed", 2)
    assert (approved.yls_state, approved.yls_value) == ("not_measured", None)
    assert (approved.functional_leaves_state, approved.functional_leaves_value) == ("observed", 8)
    assert not {f.name for f in fields(DBIApprovedInspectionSummary)} & {
        "operator_ref", "general_photo", "lesion_photo", "note",
        "gps_fix", "photo_asset_id", "payload_json", "tenant_ref",
    }

    # Payload verificado incluso después de aprobación: no aceptar otro lote.
    wrong = sample_payload()
    wrong.plot_id = NEW_VERSION
    service, _session = session_fixture()
    with patch.object(DBIInspectionCampaignApprovalService, "_state", return_value=approved_state()), \
         patch.object(DBIInspectionCampaignApprovalService, "_verified_scientific_chain", return_value=True), \
         patch.object(DBIFieldObservationPayload, "model_validate_json", return_value=wrong):
        denied(lambda: get(service))

    # Los filtros de publicación quedan en SQL, no en JSX.
    service, session = session_fixture(campaign=False)
    denied(lambda: get(service))
    sql = str(session.execute.call_args.args[0])
    assert "dbi_campaigns.status" in sql and "dbi_campaigns.tenant_ref" in sql

    service, session = session_fixture(link=False)
    denied(lambda: get(service))
    sql = str(session.execute.call_args.args[0])
    assert "dbi_inspect_campaign_links.campaign_id" in sql
    assert "dbi_inspect_campaign_links.observation_id" in sql
    assert "dbi_inspect_campaign_links.plot_id" in sql

if __name__ == "__main__":
    validate()
    print("OK: INSPECT publicado por doble o única aprobación institucional; DTO mínimo.")
