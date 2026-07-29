"""Adaptador puro del comando v1 que recibirá el worker geoespacial."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

ANALYSIS_JOB_COMMAND_SCHEMA_VERSION = "analysis-job-command.v1"
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "request_id",
        "correlation_id",
        "job_id",
        "tenant_id",
        "farm_id",
        "lot_id",
        "inputs",
        "model_version_id",
        "pipeline_config_version",
        "requested_by",
    }
)
INPUT_FIELDS = frozenset(
    {
        "orthophoto_asset_id",
        "boundary_asset_id",
        "exclusions_asset_id",
    }
)


class WorkerCommandValidationError(ValueError):
    """Indica un comando incompatible o inseguro para el worker."""


@dataclass(frozen=True)
class WorkerAssetInputs:
    """Referencias de entrada que deberá resolver infraestructura futura."""

    orthophoto_asset_id: str
    boundary_asset_id: str
    exclusions_asset_id: str | None


@dataclass(frozen=True)
class WorkerAnalysisJobCommand:
    """Comando validado sin rutas, credenciales ni efectos externos."""

    schema_version: str
    request_id: str
    correlation_id: str
    job_id: str
    tenant_id: str
    farm_id: str
    lot_id: str
    inputs: WorkerAssetInputs
    model_version_id: str
    pipeline_config_version: str
    requested_by: str


def _require_exact_fields(
    payload: Mapping[str, object],
    expected: frozenset[str],
    *,
    location: str,
) -> None:
    """Exige campos exactos para bloquear divergencia silenciosa."""

    actual = set(payload)
    if actual != expected:
        missing = sorted(expected.difference(actual))
        unexpected = sorted(actual.difference(expected))
        raise WorkerCommandValidationError(
            f"Campos inválidos en {location}; "
            f"faltantes={missing}, inesperados={unexpected}."
        )


def _require_reference(value: object, *, field: str) -> str:
    """Valida una referencia interna opaca."""

    if not isinstance(value, str) or not REFERENCE_PATTERN.fullmatch(value):
        raise WorkerCommandValidationError(
            f"{field} debe ser una referencia interna opaca."
        )
    return value


def parse_analysis_job_command(
    payload: Mapping[str, object],
) -> WorkerAnalysisJobCommand:
    """Valida y normaliza el comando sin ejecutar el pipeline."""

    if not isinstance(payload, Mapping):
        raise WorkerCommandValidationError(
            "El comando debe ser un objeto."
        )
    _require_exact_fields(payload, ROOT_FIELDS, location="comando")

    if payload["schema_version"] != ANALYSIS_JOB_COMMAND_SCHEMA_VERSION:
        raise WorkerCommandValidationError(
            "schema_version no es compatible con este worker."
        )

    raw_inputs = payload["inputs"]
    if not isinstance(raw_inputs, Mapping):
        raise WorkerCommandValidationError(
            "inputs debe ser un objeto."
        )
    _require_exact_fields(raw_inputs, INPUT_FIELDS, location="inputs")

    exclusions = raw_inputs["exclusions_asset_id"]
    if exclusions is not None:
        exclusions = _require_reference(
            exclusions,
            field="inputs.exclusions_asset_id",
        )

    inputs = WorkerAssetInputs(
        orthophoto_asset_id=_require_reference(
            raw_inputs["orthophoto_asset_id"],
            field="inputs.orthophoto_asset_id",
        ),
        boundary_asset_id=_require_reference(
            raw_inputs["boundary_asset_id"],
            field="inputs.boundary_asset_id",
        ),
        exclusions_asset_id=exclusions,
    )

    return WorkerAnalysisJobCommand(
        schema_version=ANALYSIS_JOB_COMMAND_SCHEMA_VERSION,
        request_id=_require_reference(
            payload["request_id"],
            field="request_id",
        ),
        correlation_id=_require_reference(
            payload["correlation_id"],
            field="correlation_id",
        ),
        job_id=_require_reference(payload["job_id"], field="job_id"),
        tenant_id=_require_reference(
            payload["tenant_id"],
            field="tenant_id",
        ),
        farm_id=_require_reference(payload["farm_id"], field="farm_id"),
        lot_id=_require_reference(payload["lot_id"], field="lot_id"),
        inputs=inputs,
        model_version_id=_require_reference(
            payload["model_version_id"],
            field="model_version_id",
        ),
        pipeline_config_version=_require_reference(
            payload["pipeline_config_version"],
            field="pipeline_config_version",
        ),
        requested_by=_require_reference(
            payload["requested_by"],
            field="requested_by",
        ),
    )
