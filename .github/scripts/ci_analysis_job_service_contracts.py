"""Valida contratos puros e idempotencia del servicio de trabajos DBI."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.jobs import (  # noqa: E402
    AnalysisJobCreateRequest,
    AnalysisJobCreateResponse,
    AnalysisJobRequestIntent,
    AnalysisJobStatus,
    AnalysisProfilePolicy,
    AnalysisProfileResolutionContext,
    AnalysisProfileUnavailable,
    ApprovedAnalysisProfile,
    analysis_job_request_fingerprint,
    canonical_contract_bytes,
)

FARM_ID = UUID("10000000-0000-0000-0000-000000000001")
PLOT_ID = UUID("20000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("30000000-0000-0000-0000-000000000001")
ORTHOPHOTO_ID = UUID("40000000-0000-0000-0000-000000000001")
ORTHOPHOTO_ALT_ID = UUID(
    "40000000-0000-0000-0000-000000000002"
)
BOUNDARY_ID = UUID("50000000-0000-0000-0000-000000000001")
EXCLUSIONS_ID = UUID("60000000-0000-0000-0000-000000000001")
JOB_ID = UUID("70000000-0000-0000-0000-000000000001")

ACCEPTED_AT = datetime(
    2026,
    8,
    4,
    19,
    0,
    tzinfo=timezone.utc,
)


def _expect_validation_error(
    callback: Callable[[], object],
    message: str,
) -> None:
    """Exige que Pydantic rechace una entrada inválida."""

    try:
        callback()
    except ValidationError:
        return
    raise AssertionError(message)


def _request_payload() -> dict[str, object]:
    """Construye una solicitud HTTP válida y determinista."""

    return {
        "request_id": "request-contract-check",
        "campaign_id": CAMPAIGN_ID,
        "orthophoto_asset_id": ORTHOPHOTO_ID,
        "boundary_asset_id": BOUNDARY_ID,
        "exclusions_asset_id": EXCLUSIONS_ID,
    }


def _intent_payload() -> dict[str, object]:
    """Construye una intención idempotente válida."""

    return {
        "tenant_ref": "tenant-contract-check",
        "request_id": "request-contract-check",
        "farm_id": FARM_ID,
        "plot_id": PLOT_ID,
        "campaign_id": None,
        "orthophoto_asset_id": ORTHOPHOTO_ID,
        "boundary_asset_id": BOUNDARY_ID,
        "exclusions_asset_id": None,
        "requested_by_ref": "principal-contract-check",
    }


def validate_strict_http_contracts() -> None:
    """Comprueba versiones, UUID, campos adicionales e inmutabilidad."""

    request = AnalysisJobCreateRequest.model_validate(
        _request_payload()
    )

    assert request.schema_version == (
        "dbi-analysis-job-request.v1"
    )
    assert request.orthophoto_asset_id == ORTHOPHOTO_ID
    assert request.boundary_asset_id == BOUNDARY_ID

    with_extra = {
        **_request_payload(),
        "unexpected_field": True,
    }
    _expect_validation_error(
        lambda: AnalysisJobCreateRequest.model_validate(
            with_extra
        ),
        "La solicitud HTTP aceptó un campo no declarado.",
    )

    invalid_uuid = {
        **_request_payload(),
        "orthophoto_asset_id": "not-a-uuid",
    }
    _expect_validation_error(
        lambda: AnalysisJobCreateRequest.model_validate(
            invalid_uuid
        ),
        "La solicitud HTTP aceptó un UUID inválido.",
    )

    missing_boundary = _request_payload()
    missing_boundary.pop("boundary_asset_id")

    _expect_validation_error(
        lambda: AnalysisJobCreateRequest.model_validate(
            missing_boundary
        ),
        (
            "La solicitud HTTP aceptó la ausencia "
            "del límite obligatorio."
        ),
    )

    wrong_version = {
        **_request_payload(),
        "schema_version": "dbi-analysis-job-request.v2",
    }
    _expect_validation_error(
        lambda: AnalysisJobCreateRequest.model_validate(
            wrong_version
        ),
        (
            "La solicitud HTTP aceptó una versión "
            "de contrato desconocida."
        ),
    )

    try:
        request.request_id = "mutated-request"  # type: ignore[misc]
    except ValidationError:
        pass
    else:
        raise AssertionError(
            "El contrato HTTP permitió una mutación."
        )


def validate_response_timezone_contract() -> None:
    """Exige fechas conscientes de zona horaria."""

    response = AnalysisJobCreateResponse(
        job_id=JOB_ID,
        status=AnalysisJobStatus.ACCEPTED,
        accepted_at=ACCEPTED_AT,
        created=True,
    )

    assert response.schema_version == (
        "dbi-analysis-job-response.v1"
    )
    assert response.accepted_at.tzinfo is not None
    assert response.status is AnalysisJobStatus.ACCEPTED

    _expect_validation_error(
        lambda: AnalysisJobCreateResponse(
            job_id=JOB_ID,
            status=AnalysisJobStatus.ACCEPTED,
            accepted_at=ACCEPTED_AT.replace(tzinfo=None),
            created=True,
        ),
        "La respuesta aceptó una fecha sin zona horaria.",
    )


def validate_canonical_fingerprint() -> None:
    """Comprueba serialización y fingerprint deterministas."""

    payload = _intent_payload()

    intent = AnalysisJobRequestIntent.model_validate(
        payload
    )
    reordered = AnalysisJobRequestIntent.model_validate(
        dict(reversed(list(payload.items())))
    )

    canonical = canonical_contract_bytes(intent)

    assert canonical == canonical_contract_bytes(reordered)
    assert canonical.startswith(
        b'{"boundary_asset_id":'
    )
    assert b'"campaign_id":null' in canonical
    assert b'"exclusions_asset_id":null' in canonical
    assert b" " not in canonical

    fingerprint = analysis_job_request_fingerprint(intent)
    reordered_fingerprint = (
        analysis_job_request_fingerprint(reordered)
    )

    assert fingerprint == reordered_fingerprint
    assert len(fingerprint) == 64
    assert all(
        character in "0123456789abcdef"
        for character in fingerprint
    )

    divergent_payload = {
        **payload,
        "orthophoto_asset_id": ORTHOPHOTO_ALT_ID,
    }
    divergent = AnalysisJobRequestIntent.model_validate(
        divergent_payload
    )

    assert (
        analysis_job_request_fingerprint(divergent)
        != fingerprint
    )


class _StaticAnalysisProfilePolicy:
    """Política determinista utilizada solamente por la prueba."""

    def __init__(
        self,
        profile: ApprovedAnalysisProfile,
    ) -> None:
        self._profile = profile

    def resolve(
        self,
        *,
        context: AnalysisProfileResolutionContext,
    ) -> ApprovedAnalysisProfile:
        assert context.tenant_ref == "tenant-contract-check"
        assert context.farm_id == FARM_ID
        assert context.plot_id == PLOT_ID
        return self._profile


class _UnavailableAnalysisProfilePolicy:
    """Política que prueba el cierre ante perfil inexistente."""

    def resolve(
        self,
        *,
        context: AnalysisProfileResolutionContext,
    ) -> ApprovedAnalysisProfile:
        del context
        raise AnalysisProfileUnavailable(
            "No existe un perfil aprobado único."
        )


def validate_profile_policy_boundary() -> None:
    """Comprueba que el perfil no altera el fingerprint HTTP."""

    intent = AnalysisJobRequestIntent.model_validate(
        _intent_payload()
    )
    fingerprint_before = (
        analysis_job_request_fingerprint(intent)
    )

    context = AnalysisProfileResolutionContext(
        tenant_ref="tenant-contract-check",
        organization_ref="organization-contract-check",
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        campaign_id=CAMPAIGN_ID,
    )

    profile_a = ApprovedAnalysisProfile(
        model_version_id="model-approved-a",
        pipeline_config_version="pipeline-config-a",
        policy_ref="policy-a",
    )
    profile_b = ApprovedAnalysisProfile(
        model_version_id="model-approved-b",
        pipeline_config_version="pipeline-config-b",
        policy_ref="policy-b",
    )

    policy_a = _StaticAnalysisProfilePolicy(profile_a)
    policy_b = _StaticAnalysisProfilePolicy(profile_b)

    assert isinstance(policy_a, AnalysisProfilePolicy)
    assert isinstance(policy_b, AnalysisProfilePolicy)
    assert not isinstance(object(), AnalysisProfilePolicy)

    assert policy_a.resolve(context=context) == profile_a
    assert policy_b.resolve(context=context) == profile_b
    assert profile_a != profile_b

    fingerprint_after = (
        analysis_job_request_fingerprint(intent)
    )
    assert fingerprint_after == fingerprint_before

    unavailable_policy = (
        _UnavailableAnalysisProfilePolicy()
    )
    assert isinstance(
        unavailable_policy,
        AnalysisProfilePolicy,
    )

    try:
        unavailable_policy.resolve(context=context)
    except AnalysisProfileUnavailable:
        pass
    else:
        raise AssertionError(
            "La política sin perfil no falló de forma cerrada."
        )


def validate_component_isolation() -> None:
    """Impide acoplar los contratos con infraestructura."""

    source = (
        BACKEND
        / "app"
        / "dbi"
        / "jobs"
        / "service_contracts.py"
    ).read_text(encoding="utf-8").lower()

    for required in (
        "class analysisjobcreaterequest",
        "class analysisjobcreateresponse",
        "class analysisjobrequestintent",
        "class approvedanalysisprofile",
        "class analysisprofilepolicy",
        "def canonical_contract_bytes",
        "def analysis_job_request_fingerprint",
    ):
        assert required in source

    for forbidden in (
        "from sqlalchemy",
        "import sqlalchemy",
        "from fastapi",
        "import fastapi",
        "create_engine",
        "sessionmaker",
        "database_url",
        ".execute(",
        ".commit(",
        ".rollback(",
        "from redis",
        "import redis",
        "from celery",
        "import celery",
        "subprocess",
        "boto3",
        "requests.",
        "httpx.",
    ):
        assert forbidden not in source


def main() -> None:
    """Ejecuta todas las barreras puras del bloque 3."""

    validate_strict_http_contracts()
    validate_response_timezone_contract()
    validate_canonical_fingerprint()
    validate_profile_policy_boundary()
    validate_component_isolation()

    print(
        "Contratos e idempotencia pura del servicio "
        "de trabajos DBI aprobados offline."
    )


if __name__ == "__main__":
    main()
