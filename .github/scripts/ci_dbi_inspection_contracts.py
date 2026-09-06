"""Valida contratos puros de DBI-INSPECT-001 sin base, red ni storage."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.inspection import (  # noqa: E402
    DBICoreObservation,
    DBIDiagnosticObservation,
    DBIFieldObservationCorrection,
    DBIFieldObservationCreate,
    DBIFieldObservationPayload,
    DBIFieldObservationVersion,
    DBIFoureObservation,
    DBIGPSFix,
    DBILeafCountObservation,
    DBIObservedBool,
    DBIObservedFloat,
    DBIObservedText,
    DBIPhotoEvidence,
    DBIStructuralObservation,
)

TENANT = "tenant-inspect-ci"
ORG = "organization-inspect-ci"
FARM = UUID("10000000-0000-4000-8000-000000000079")
PLOT = UUID("20000000-0000-4000-8000-000000000079")
POINT = UUID("30000000-0000-4000-8000-000000000079")
UP = UUID("40000000-0000-4000-8000-000000000079")
PHOTO_GENERAL = UUID("50000000-0000-4000-8000-000000000079")
PHOTO_LESION = UUID("50000000-0000-4000-8000-000000000080")
OBSERVATION = UUID("60000000-0000-4000-8000-000000000079")
VERSION_1 = UUID("70000000-0000-4000-8000-000000000079")
VERSION_2 = UUID("70000000-0000-4000-8000-000000000080")
NOW = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)


def observed_text(value: str) -> DBIObservedText:
    return DBIObservedText(state="observed", value=value)


def not_measured(reason: str) -> DBIObservedText:
    return DBIObservedText(state="not_measured", reason=reason)


def complete_core() -> DBICoreObservation:
    return DBICoreObservation(
        foure=DBIFoureObservation(state="observed", value=3),
        yls=DBILeafCountObservation(state="observed", value=5),
        functional_leaves=DBILeafCountObservation(state="observed", value=8),
        mother_condition=observed_text("vigorous"),
        successor_condition=observed_text("present"),
        bunch_present=DBIObservedBool(state="observed", value=True),
        visible_affection=observed_text("black_sigatoka_suspected"),
        severity=observed_text("moderate"),
        observer_confidence=observed_text("high"),
        general_photo=DBIPhotoEvidence(state="observed", asset_id=PHOTO_GENERAL),
        lesion_photo=DBIPhotoEvidence(state="observed", asset_id=PHOTO_LESION),
        note="Lesiones visibles en hojas intermedias.",
    )


def complete_payload(*, up_id=UP, diagnostic=True) -> DBIFieldObservationPayload:
    return DBIFieldObservationPayload(
        tenant_ref=TENANT,
        organization_ref=ORG,
        farm_id=FARM,
        plot_id=PLOT,
        operator_ref="operator-inspect-ci",
        observed_at=NOW,
        gps_fix=DBIGPSFix(
            longitude=-79.9252919,
            latitude=-3.2716971,
            accuracy_m=4.2,
            captured_at=NOW,
        ),
        sampling_point_id=POINT,
        up_id=up_id,
        core=complete_core(),
        structural=DBIStructuralObservation(
            pseudostem_diameter_cm=DBIObservedFloat(state="observed", value=23.4)
        ),
        diagnostic=(
            DBIDiagnosticObservation(
                trigger_reason="Síntoma radical observado durante revisión dirigida.",
                root_condition=observed_text("reduced_root_mass"),
                necrosis_or_damage=observed_text("localized_necrosis"),
                root_sample_taken=DBIObservedBool(state="observed", value=True),
                nematode_or_lab_result=not_measured("laboratory_result_pending"),
                soil_or_nutrition=not_measured("outside_current_protocol"),
                evidence_photo=DBIPhotoEvidence(
                    state="not_measured", reason="diagnostic_photo_not_required"
                ),
                protocol_ref="root-check-v1",
                laboratory_ref=None,
                method_version="1.0",
            )
            if diagnostic
            else None
        ),
    )


def validate_complete_core_and_versioning() -> None:
    payload = complete_payload()
    create = DBIFieldObservationCreate(payload=payload)
    assert create.payload.core.foure.value == 3
    assert create.payload.up_id == UP
    assert create.payload.evidence_kind == "observed"

    original = DBIFieldObservationVersion(
        observation_id=OBSERVATION,
        version_id=VERSION_1,
        version=1,
        created_at=NOW,
        payload=payload,
    )
    correction = DBIFieldObservationCorrection(
        base_version_id=VERSION_1,
        correction_reason="Corrección de transcripción Fouré confirmada en libreta de campo.",
        payload=payload.model_copy(
            update={
                "core": payload.core.model_copy(
                    update={"foure": DBIFoureObservation(state="observed", value=2)}
                )
            }
        ),
    )
    revised = DBIFieldObservationVersion(
        observation_id=OBSERVATION,
        version_id=VERSION_2,
        version=2,
        supersedes_version_id=VERSION_1,
        correction_reason=correction.correction_reason,
        created_at=NOW,
        payload=correction.payload,
    )
    assert original.payload.core.foure.value == 3
    assert revised.payload.core.foure.value == 2
    assert revised.supersedes_version_id == original.version_id


def validate_partial_first_visit_without_up() -> None:
    partial_core = DBICoreObservation(
        foure=DBIFoureObservation(state="not_measured", reason="leaf_access_limited"),
        yls=DBILeafCountObservation(state="not_measured", reason="leaf_access_limited"),
        functional_leaves=DBILeafCountObservation(state="observed", value=7),
        mother_condition=observed_text("standing"),
        successor_condition=DBIObservedText(
            state="not_applicable", reason="successor_not_present"
        ),
        bunch_present=DBIObservedBool(state="observed", value=False),
        visible_affection=DBIObservedText(
            state="not_measured", reason="rapid_first_visit"
        ),
        severity=DBIObservedText(state="not_applicable", reason="no_affection_scored"),
        observer_confidence=DBIObservedText(
            state="not_applicable", reason="no_affection_scored"
        ),
        general_photo=DBIPhotoEvidence(
            state="not_measured", reason="camera_temporarily_unavailable"
        ),
        lesion_photo=DBIPhotoEvidence(
            state="not_applicable", reason="no_lesion_documented"
        ),
        note="Primera visita; asociación a UP pendiente de procesamiento RGB.",
    )
    payload = complete_payload(up_id=None, diagnostic=False).model_copy(
        update={"core": partial_core, "structural": None}
    )
    assert payload.up_id is None
    assert payload.sampling_point_id == POINT
    assert payload.core.foure.value is None
    assert payload.core.foure.state == "not_measured"
    assert payload.diagnostic is None


def validate_fail_closed() -> None:
    try:
        DBIFoureObservation(state="observed", value=7)
    except ValidationError:
        pass
    else:
        raise AssertionError("Fouré 7 debía ser rechazado.")

    try:
        DBIObservedFloat(state="not_measured", value=10.0, reason="skipped")
    except ValidationError:
        pass
    else:
        raise AssertionError("Un campo no medido no puede conservar valor observado.")

    try:
        DBIPhotoEvidence(state="not_measured")
    except ValidationError:
        pass
    else:
        raise AssertionError("Un dato ausente requiere razón explícita.")

    payload = complete_payload()
    serialized = str(payload.model_dump(mode="json")).lower()
    for forbidden in (
        "signed_url",
        "presigned",
        "http://",
        "https://",
        "local_path",
        "credential",
        "password",
    ):
        assert forbidden not in serialized


def main() -> None:
    validate_complete_core_and_versioning()
    validate_partial_first_visit_without_up()
    validate_fail_closed()
    print(
        "DBI-INSPECT-001 contratos aprobados: CORE parcial/completo, Fouré, UP opcional y versionado."
    )


if __name__ == "__main__":
    main()
