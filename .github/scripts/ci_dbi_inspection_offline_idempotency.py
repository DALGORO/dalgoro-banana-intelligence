"""Valida identidad idempotente de creación INSPECT para reintentos offline."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_inspection_offline.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-inspection-offline-secret")

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.inspection import service as inspection_service  # noqa: E402
from app.dbi.inspection.api_schemas import (  # noqa: E402
    DBIFieldObservationBody,
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

TENANT = "tenant-inspect-offline"
ORGANIZATION = "organization-inspect-offline"
FARM = UUID("10000000-0000-4000-8000-000000000279")
PLOT = UUID("20000000-0000-4000-8000-000000000279")
OBSERVATION = UUID("60000000-0000-4000-8000-000000000279")
VERSION = UUID("70000000-0000-4000-8000-000000000279")
NOW = datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc)


def _text(value: str) -> DBIObservedText:
    return DBIObservedText(state="observed", value=value)


def _request(*, foure: int = 3) -> DBIFieldObservationCreateRequest:
    return DBIFieldObservationCreateRequest(
        observation=DBIFieldObservationBody(
            observed_at=NOW,
            core=DBICoreObservation(
                foure=DBIFoureObservation(state="observed", value=foure),
                yls=DBILeafCountObservation(state="observed", value=5),
                functional_leaves=DBILeafCountObservation(state="observed", value=8),
                mother_condition=_text("vigorous"),
                successor_condition=_text("present"),
                bunch_present=DBIObservedBool(state="observed", value=True),
                visible_affection=_text("none_visible"),
                severity=_text("none"),
                observer_confidence=_text("high"),
                general_photo=DBIPhotoEvidence(
                    state="not_measured",
                    reason="offline_photo_pending",
                ),
                lesion_photo=DBIPhotoEvidence(
                    state="not_applicable",
                    reason="no_visible_lesion",
                ),
                note="Captura offline con identidad estable.",
            ),
        )
    )


def _context() -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="operator-inspect-offline",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORGANIZATION}),
        farm_scopes=frozenset({DBIFarmScope(ORGANIZATION, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORGANIZATION, FARM, PLOT)}),
        permissions=frozenset({DBIPermission.READ, DBIPermission.WRITE}),
    )


class _Repository:
    def __init__(self) -> None:
        self.latest: DBIFieldObservationVersion | None = None
        self.create_calls = 0

    def get_latest(self, **kwargs):
        if kwargs.get("observation_id") != OBSERVATION:
            return None
        return self.latest

    def create_observation(
        self,
        request,
        *,
        recorded_by_ref,
        observation_id=None,
        version_id=None,
    ):
        self.create_calls += 1
        assert recorded_by_ref == "operator-inspect-offline"
        assert observation_id == OBSERVATION
        assert version_id == VERSION
        self.latest = DBIFieldObservationVersion(
            observation_id=observation_id,
            version_id=version_id,
            version=1,
            created_at=NOW,
            payload=request.payload,
        )
        return self.latest


class _AssetRepository:
    def get_scoped(self, **kwargs):
        raise AssertionError("Una captura sin fotos observadas no debe consultar Asset.")


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
            return_value=_AssetRepository(),
        ),
    ):
        return DBIFieldObservationService(object())


def validate_retry_reuses_same_truth() -> None:
    repository = _Repository()
    service = _service(repository)
    first = service.create(
        _context(),
        organization_ref=ORGANIZATION,
        farm_id=FARM,
        plot_id=PLOT,
        request=_request(),
        observation_id=OBSERVATION,
        version_id=VERSION,
    )
    second = service.create(
        _context(),
        organization_ref=ORGANIZATION,
        farm_id=FARM,
        plot_id=PLOT,
        request=_request(),
        observation_id=OBSERVATION,
        version_id=VERSION,
    )
    assert repository.create_calls == 1
    assert second == first


def validate_divergent_retry_is_conflict() -> None:
    repository = _Repository()
    service = _service(repository)
    service.create(
        _context(),
        organization_ref=ORGANIZATION,
        farm_id=FARM,
        plot_id=PLOT,
        request=_request(foure=3),
        observation_id=OBSERVATION,
        version_id=VERSION,
    )
    try:
        service.create(
            _context(),
            organization_ref=ORGANIZATION,
            farm_id=FARM,
            plot_id=PLOT,
            request=_request(foure=4),
            observation_id=OBSERVATION,
            version_id=VERSION,
        )
    except DBIInspectionConflict:
        pass
    else:
        raise AssertionError("Un reintento divergente debía quedar en conflicto.")
    assert repository.create_calls == 1


def validate_identity_pair_is_atomic() -> None:
    for observation_id, version_id in ((OBSERVATION, None), (None, VERSION)):
        repository = _Repository()
        service = _service(repository)
        try:
            service.create(
                _context(),
                organization_ref=ORGANIZATION,
                farm_id=FARM,
                plot_id=PLOT,
                request=_request(),
                observation_id=observation_id,
                version_id=version_id,
            )
        except DBIInspectionConflict:
            pass
        else:
            raise AssertionError("La identidad offline incompleta debía rechazarse.")
        assert repository.create_calls == 0


def validate_http_transports_ids_only_as_headers() -> None:
    source = (BACKEND / "app" / "api" / "v1" / "dbi_inspection.py").read_text(
        encoding="utf-8"
    )
    assert 'Header(alias="X-DBI-Observation-Id")' in source
    assert 'Header(alias="X-DBI-Version-Id")' in source
    assert "observation_id=observation_id" in source
    assert "version_id=version_id" in source

    request_fields = set(DBIFieldObservationCreateRequest.model_fields)
    assert request_fields == {"observation"}
    for forbidden in ("tenant_ref", "operator_ref", "recorded_by_ref"):
        assert forbidden not in request_fields


def main() -> None:
    validate_retry_reuses_same_truth()
    validate_divergent_retry_is_conflict()
    validate_identity_pair_is_atomic()
    validate_http_transports_ids_only_as_headers()
    print(
        "DBI-INSPECT-001 offline aprobado: identidad estable, reintento idempotente y divergencia en conflicto."
    )


if __name__ == "__main__":
    main()
