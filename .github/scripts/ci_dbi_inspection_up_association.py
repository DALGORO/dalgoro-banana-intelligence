"""Valida asociación posterior a UP sin reescribir verdad-terreno INSPECT."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_inspection_up_association.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-inspection-up-association-secret")

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.api.v1 import get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.inspection import service as inspection_service  # noqa: E402
from app.dbi.inspection.api_schemas import (  # noqa: E402
    DBIFieldObservationUPAssociationRequest,
)
from app.dbi.inspection.contracts import (  # noqa: E402
    DBICoreObservation,
    DBIFieldObservationPayload,
    DBIFieldObservationVersion,
    DBIFoureObservation,
    DBIGPSFix,
    DBILeafCountObservation,
    DBIObservedBool,
    DBIObservedText,
    DBIPhotoEvidence,
)
from app.dbi.inspection.repository import DBIInspectionConflict  # noqa: E402
from app.dbi.inspection.service import (  # noqa: E402
    DBIFieldObservationService,
    DBI_UP_ASSOCIATION_REASON_PREFIX,
)

TENANT = "tenant-inspect-up"
ORG = "organization-inspect-up"
FARM = UUID("10000000-0000-4000-8000-000000000279")
PLOT = UUID("20000000-0000-4000-8000-000000000279")
OBSERVATION = UUID("60000000-0000-4000-8000-000000000279")
VERSION_1 = UUID("70000000-0000-4000-8000-000000000279")
VERSION_2 = UUID("70000000-0000-4000-8000-000000000280")
UP_ID = UUID("40000000-0000-4000-8000-000000000279")
NOW = datetime(2026, 9, 6, 3, 30, tzinfo=timezone.utc)


def _text(value: str) -> DBIObservedText:
    return DBIObservedText(state="observed", value=value)


def _payload() -> DBIFieldObservationPayload:
    return DBIFieldObservationPayload(
        tenant_ref=TENANT,
        organization_ref=ORG,
        farm_id=FARM,
        plot_id=PLOT,
        operator_ref="field-observer-original",
        observed_at=NOW,
        gps_fix=DBIGPSFix(
            longitude=-79.9252958,
            latitude=-3.2716995,
            accuracy_m=4.5,
            captured_at=NOW,
        ),
        sampling_point_id=UUID("50000000-0000-4000-8000-000000000279"),
        up_id=None,
        core=DBICoreObservation(
            foure=DBIFoureObservation(state="observed", value=3),
            yls=DBILeafCountObservation(state="observed", value=5),
            functional_leaves=DBILeafCountObservation(state="observed", value=8),
            mother_condition=_text("vigorous"),
            successor_condition=_text("present"),
            bunch_present=DBIObservedBool(state="observed", value=True),
            visible_affection=_text("none_visible"),
            severity=_text("none"),
            observer_confidence=_text("high"),
            general_photo=DBIPhotoEvidence(
                state="not_measured", reason="pending_private_upload"
            ),
            lesion_photo=DBIPhotoEvidence(
                state="not_measured", reason="pending_private_upload"
            ),
            note="Observación original; UP aún no confirmada.",
        ),
        structural=None,
        diagnostic=None,
        evidence_kind="observed",
    )


def _context(*, principal_ref: str, write: bool = True) -> DBIAccessContext:
    permissions = {DBIPermission.READ}
    if write:
        permissions.add(DBIPermission.WRITE)
    return DBIAccessContext(
        principal_ref=principal_ref,
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset({DBIFarmScope(ORG, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORG, FARM, PLOT)}),
        permissions=frozenset(permissions),
    )


class _Repository:
    def __init__(self) -> None:
        self.latest = DBIFieldObservationVersion(
            observation_id=OBSERVATION,
            version_id=VERSION_1,
            version=1,
            created_at=NOW,
            payload=_payload(),
        )
        self.corrections: list[tuple[object, str]] = []

    def get_latest(self, **kwargs):
        assert kwargs == {
            "observation_id": OBSERVATION,
            "tenant_ref": TENANT,
            "farm_id": FARM,
            "plot_id": PLOT,
        }
        return self.latest

    def correct_observation(self, request, *, recorded_by_ref):
        self.corrections.append((request, recorded_by_ref))
        self.latest = DBIFieldObservationVersion(
            observation_id=OBSERVATION,
            version_id=VERSION_2,
            version=2,
            supersedes_version_id=VERSION_1,
            correction_reason=request.correction_reason,
            created_at=NOW,
            payload=request.payload,
        )
        return self.latest


def _service(repository: _Repository) -> DBIFieldObservationService:
    with (
        patch.object(
            inspection_service,
            "DBIFieldObservationRepository",
            return_value=repository,
        ),
        patch.object(
            inspection_service,
            "DBIAssetRepository",
            return_value=object(),
        ),
    ):
        return DBIFieldObservationService(object())


def validate_request_is_explicit_and_scope_free() -> None:
    fields = set(DBIFieldObservationUPAssociationRequest.model_fields)
    assert fields == {
        "base_version_id",
        "up_id",
        "confirmation",
        "association_reason",
    }
    for forbidden in (
        "tenant_ref",
        "organization_ref",
        "farm_id",
        "plot_id",
        "operator_ref",
        "gps_fix",
        "sampling_point_id",
        "core",
    ):
        assert forbidden not in fields

    try:
        DBIFieldObservationUPAssociationRequest(
            base_version_id=VERSION_1,
            up_id=UP_ID,
            confirmation="ambiguous",
            association_reason="No debe aceptarse una asociación ambigua.",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Una asociación UP ambigua debía ser rechazada por contrato.")


def validate_association_only_changes_up_and_versions() -> None:
    repository = _Repository()
    service = _service(repository)
    original = repository.latest
    request = DBIFieldObservationUPAssociationRequest(
        base_version_id=VERSION_1,
        up_id=UP_ID,
        confirmation="unequivocal",
        association_reason="UP confirmada tras revisión RGB y control humano.",
    )
    associated = service.associate_up(
        _context(principal_ref="up-reviewer"),
        organization_ref=ORG,
        farm_id=FARM,
        plot_id=PLOT,
        observation_id=OBSERVATION,
        request=request,
    )

    assert associated.version == 2
    assert associated.supersedes_version_id == VERSION_1
    assert associated.payload.up_id == UP_ID
    assert associated.payload.operator_ref == original.payload.operator_ref
    assert associated.payload.model_copy(update={"up_id": None}) == original.payload
    correction, actor = repository.corrections[0]
    assert actor == "up-reviewer"
    assert correction.base_version_id == VERSION_1
    assert correction.correction_reason == (
        DBI_UP_ASSOCIATION_REASON_PREFIX + request.association_reason
    )

    same = service.associate_up(
        _context(principal_ref="up-reviewer"),
        organization_ref=ORG,
        farm_id=FARM,
        plot_id=PLOT,
        observation_id=OBSERVATION,
        request=DBIFieldObservationUPAssociationRequest(
            base_version_id=VERSION_2,
            up_id=UP_ID,
            confirmation="unequivocal",
            association_reason="Reintento exacto de la asociación ya vigente.",
        ),
    )
    assert same.version_id == VERSION_2
    assert len(repository.corrections) == 1

    try:
        service.associate_up(
            _context(principal_ref="up-reviewer"),
            organization_ref=ORG,
            farm_id=FARM,
            plot_id=PLOT,
            observation_id=OBSERVATION,
            request=request,
        )
    except DBIInspectionConflict:
        pass
    else:
        raise AssertionError("Una asociación basada en versión obsoleta debía fallar.")


def validate_write_authorization_precedes_association() -> None:
    repository = _Repository()
    service = _service(repository)
    try:
        service.associate_up(
            _context(principal_ref="reader-only", write=False),
            organization_ref=ORG,
            farm_id=FARM,
            plot_id=PLOT,
            observation_id=OBSERVATION,
            request=DBIFieldObservationUPAssociationRequest(
                base_version_id=VERSION_1,
                up_id=UP_ID,
                confirmation="unequivocal",
                association_reason="No debe escribirse sin permiso WRITE.",
            ),
        )
    except DBIAccessDenied:
        pass
    else:
        raise AssertionError("WRITE ausente debía denegar asociación UP.")
    assert repository.corrections == []


def validate_route_registered() -> None:
    routes = {
        (route.path, method)
        for route in get_api_router().routes
        if "field-observations" in route.path
        for method in route.methods
    }
    association = (
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/"
        "field-observations/{observation_id}/up-associations"
    )
    assert (association, "POST") in routes


def main() -> None:
    validate_request_is_explicit_and_scope_free()
    validate_association_only_changes_up_and_versions()
    validate_write_authorization_precedes_association()
    validate_route_registered()
    print(
        "DBI-INSPECT-001 asociación UP aprobada: confirmación inequívoca, cambio estrecho y versión append-only."
    )


if __name__ == "__main__":
    main()
