"""Valida servicio y frontera HTTP de INSPECT sin DB, red ni storage."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_inspection_http.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-inspection-http-secret")

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.api.v1 import dbi_inspection, get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.inspection import service as inspection_service  # noqa: E402
from app.dbi.inspection.api_schemas import (  # noqa: E402
    DBIFieldObservationBody,
    DBIFieldObservationCorrectionRequest,
    DBIFieldObservationCreateRequest,
)
from app.dbi.inspection.contracts import (  # noqa: E402
    DBICoreObservation,
    DBIFieldObservationVersion,
    DBIFoureObservation,
    DBILeafCountObservation,
    DBIObservedBool,
    DBIObservedText,
    DBIPhotoEvidence,
)
from app.dbi.inspection.repository import DBIInspectionConflict  # noqa: E402
from app.dbi.inspection.service import DBIFieldObservationService  # noqa: E402

TENANT = "tenant-inspect-http"
ORG = "organization-inspect-http"
FARM = UUID("10000000-0000-4000-8000-000000000179")
PLOT = UUID("20000000-0000-4000-8000-000000000179")
OBSERVATION = UUID("60000000-0000-4000-8000-000000000179")
VERSION_1 = UUID("70000000-0000-4000-8000-000000000179")
VERSION_2 = UUID("70000000-0000-4000-8000-000000000180")
NOW = datetime(2026, 9, 5, 18, 0, tzinfo=timezone.utc)


def _text(value: str) -> DBIObservedText:
    return DBIObservedText(state="observed", value=value)


def _core() -> DBICoreObservation:
    return DBICoreObservation(
        foure=DBIFoureObservation(state="observed", value=3),
        yls=DBILeafCountObservation(state="observed", value=5),
        functional_leaves=DBILeafCountObservation(state="observed", value=8),
        mother_condition=_text("standing"),
        successor_condition=_text("present"),
        bunch_present=DBIObservedBool(state="observed", value=True),
        visible_affection=_text("black_sigatoka_suspected"),
        severity=_text("moderate"),
        observer_confidence=_text("high"),
        general_photo=DBIPhotoEvidence(
            state="not_measured", reason="photo_pending_private_asset"
        ),
        lesion_photo=DBIPhotoEvidence(
            state="not_applicable", reason="lesion_photo_not_required"
        ),
        note="Captura rápida de campo.",
    )


def _body() -> DBIFieldObservationBody:
    return DBIFieldObservationBody(observed_at=NOW, core=_core())


def _context(*, write: bool = True, authorized: bool = True) -> DBIAccessContext:
    permissions = {DBIPermission.READ}
    if write:
        permissions.add(DBIPermission.WRITE)
    return DBIAccessContext(
        principal_ref="principal-inspect-http",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG}),
        farm_scopes=(
            frozenset({DBIFarmScope(ORG, FARM)}) if authorized else frozenset()
        ),
        plot_scopes=(
            frozenset({DBIPlotScope(ORG, FARM, PLOT)}) if authorized else frozenset()
        ),
        permissions=frozenset(permissions),
    )


class _Repository:
    def __init__(self) -> None:
        self.created_request = None
        self.corrected_request = None
        self.latest: DBIFieldObservationVersion | None = None

    def create_observation(self, request, *, recorded_by_ref):
        self.created_request = (request, recorded_by_ref)
        self.latest = DBIFieldObservationVersion(
            observation_id=OBSERVATION,
            version_id=VERSION_1,
            version=1,
            created_at=NOW,
            payload=request.payload,
        )
        return self.latest

    def get_latest(self, **kwargs):
        return self.latest

    def list_versions(self, **kwargs):
        return (self.latest,) if self.latest is not None else ()

    def correct_observation(self, request, *, recorded_by_ref):
        self.corrected_request = (request, recorded_by_ref)
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


def validate_request_has_no_scope_authority() -> None:
    body_fields = set(DBIFieldObservationBody.model_fields)
    assert body_fields == {
        "observed_at",
        "gps_fix",
        "sampling_point_id",
        "up_id",
        "core",
        "structural",
        "diagnostic",
    }
    create_fields = set(DBIFieldObservationCreateRequest.model_fields)
    assert create_fields == {"observation"}
    for forbidden in (
        "tenant_ref",
        "organization_ref",
        "farm_id",
        "plot_id",
        "operator_ref",
        "evidence_kind",
        "recorded_by_ref",
        "object_key",
        "url",
    ):
        assert forbidden not in body_fields
        assert forbidden not in create_fields


def validate_service_derives_authority() -> None:
    repository = _Repository()
    with patch.object(
        inspection_service,
        "DBIFieldObservationRepository",
        return_value=repository,
    ):
        service = DBIFieldObservationService(object())
        result = service.create(
            _context(),
            organization_ref=ORG,
            farm_id=FARM,
            plot_id=PLOT,
            request=DBIFieldObservationCreateRequest(observation=_body()),
        )
    request, actor = repository.created_request
    assert result.version_id == VERSION_1
    assert actor == "principal-inspect-http"
    assert request.payload.tenant_ref == TENANT
    assert request.payload.organization_ref == ORG
    assert request.payload.farm_id == FARM
    assert request.payload.plot_id == PLOT
    assert request.payload.operator_ref == "principal-inspect-http"
    assert request.payload.evidence_kind == "observed"


def validate_service_correction_is_latest_and_scoped() -> None:
    repository = _Repository()
    with patch.object(
        inspection_service,
        "DBIFieldObservationRepository",
        return_value=repository,
    ):
        service = DBIFieldObservationService(object())
        first = service.create(
            _context(),
            organization_ref=ORG,
            farm_id=FARM,
            plot_id=PLOT,
            request=DBIFieldObservationCreateRequest(observation=_body()),
        )
        corrected = service.correct(
            _context(),
            organization_ref=ORG,
            farm_id=FARM,
            plot_id=PLOT,
            observation_id=OBSERVATION,
            request=DBIFieldObservationCorrectionRequest(
                base_version_id=first.version_id,
                correction_reason="Corrección verificada en libreta de campo.",
                observation=_body(),
            ),
        )
        assert corrected.version == 2
        assert corrected.supersedes_version_id == VERSION_1
        try:
            service.correct(
                _context(),
                organization_ref=ORG,
                farm_id=FARM,
                plot_id=PLOT,
                observation_id=OBSERVATION,
                request=DBIFieldObservationCorrectionRequest(
                    base_version_id=VERSION_1,
                    correction_reason="Intento obsoleto.",
                    observation=_body(),
                ),
            )
        except DBIInspectionConflict:
            pass
        else:
            raise AssertionError("Una base obsoleta debía ser rechazada.")


def validate_service_authorization_precedes_repository_write() -> None:
    repository = _Repository()
    with patch.object(
        inspection_service,
        "DBIFieldObservationRepository",
        return_value=repository,
    ):
        service = DBIFieldObservationService(object())
        try:
            service.create(
                _context(write=False),
                organization_ref=ORG,
                farm_id=FARM,
                plot_id=PLOT,
                request=DBIFieldObservationCreateRequest(observation=_body()),
            )
        except DBIAccessDenied:
            pass
        else:
            raise AssertionError("WRITE ausente debía denegar INSPECT.")
    assert repository.created_request is None


def validate_routes_registered_and_hide_unauthorized_scope() -> None:
    routes = {
        (route.path, method)
        for route in get_api_router().routes
        if "field-observations" in route.path
        for method in route.methods
    }
    base = (
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/"
        "{plot_id}/field-observations"
    )
    item = base + "/{observation_id}"
    assert (base, "POST") in routes
    assert (item, "GET") in routes
    assert (item + "/versions", "GET") in routes
    assert (item + "/corrections", "POST") in routes

    with patch.object(dbi_inspection, "DBIFieldObservationService") as service:
        try:
            dbi_inspection.create_field_observation(
                ORG,
                FARM,
                PLOT,
                DBIFieldObservationCreateRequest(observation=_body()),
                object(),
                _context(authorized=False),
            )
        except HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError("El lote no autorizado debía ocultarse.")
        service.assert_not_called()


def validate_static_boundaries() -> None:
    sources = "\n".join(
        (
            (BACKEND / "app" / "api" / "v1" / "dbi_inspection.py").read_text(
                encoding="utf-8"
            ),
            (BACKEND / "app" / "dbi" / "inspection" / "api_schemas.py").read_text(
                encoding="utf-8"
            ),
            (BACKEND / "app" / "dbi" / "inspection" / "service.py").read_text(
                encoding="utf-8"
            ),
        )
    ).lower()
    assert "dbiauthorizationpolicy.require_plot" in sources
    assert "context.tenant_ref" in sources
    assert "context.principal_ref" in sources
    for forbidden in (
        "presigned",
        "signed_url",
        "local_path",
        "bucket",
        "boto3",
        "google.cloud.storage",
        "uploadfile",
    ):
        assert forbidden not in sources


def main() -> None:
    validate_request_has_no_scope_authority()
    validate_service_derives_authority()
    validate_service_correction_is_latest_and_scoped()
    validate_service_authorization_precedes_repository_write()
    validate_routes_registered_and_hide_unauthorized_scope()
    validate_static_boundaries()
    print("DBI-INSPECT-001 HTTP aprobado: autoridad servidor, auth previa y versionado seguro.")


if __name__ == "__main__":
    main()
