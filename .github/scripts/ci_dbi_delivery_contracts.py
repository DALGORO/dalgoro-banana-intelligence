"""Pruebas offline de contratos y fronteras de entrega durable DBI."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.delivery.contracts import (  # noqa: E402
    MAX_DELIVERY_PAYLOAD_BYTES,
    DeliveryMessageStatus,
    DeliveryStream,
    PreparedDeliveryPayload,
    prepare_delivery_payload,
)
from app.schemas.dbi_analysis_jobs import (  # noqa: E402
    AnalysisJobCommand,
    AnalysisJobInputs,
    AnalysisJobResult,
)

NOW = datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc)


def _command() -> AnalysisJobCommand:
    return AnalysisJobCommand(
        request_id="request-001",
        correlation_id="correlation-001",
        job_id=str(uuid4()),
        tenant_id="tenant-001",
        farm_id=str(uuid4()),
        lot_id=str(uuid4()),
        inputs=AnalysisJobInputs(
            orthophoto_asset_id=str(uuid4()),
            boundary_asset_id=str(uuid4()),
            exclusions_asset_id=None,
        ),
        model_version_id="model-v1",
        pipeline_config_version="pipeline-v1",
        requested_by="principal-001",
    )


def validate_command_payload() -> None:
    command = _command()
    payload = prepare_delivery_payload(command)
    assert payload.stream is DeliveryStream.ANALYSIS_COMMAND
    assert payload.schema_version == "analysis-job-command.v1"
    assert payload.payload_sha256 == hashlib.sha256(
        payload.payload_json.encode("utf-8")
    ).hexdigest()
    decoded = json.loads(payload.payload_json)
    assert decoded["job_id"] == command.job_id
    assert payload.payload_json == json.dumps(
        decoded,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def validate_result_payload() -> None:
    command = _command()
    result = AnalysisJobResult(
        correlation_id=command.correlation_id,
        job_id=command.job_id,
        attempt_id=str(uuid4()),
        status="succeeded",
        pipeline_build="worker-build-001",
        started_at=NOW,
        finished_at=NOW,
    )
    payload = prepare_delivery_payload(result)
    assert payload.stream is DeliveryStream.ANALYSIS_RESULT
    assert payload.schema_version == "analysis-job-result.v1"


def validate_tampering_fails_closed() -> None:
    payload = prepare_delivery_payload(_command())
    try:
        PreparedDeliveryPayload(
            stream=payload.stream,
            schema_version=payload.schema_version,
            payload_json=payload.payload_json,
            payload_sha256="0" * 64,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Un SHA divergente debía rechazarse.")

    decoded = json.loads(payload.payload_json)
    noncanonical = json.dumps(decoded, ensure_ascii=False, indent=2)
    try:
        PreparedDeliveryPayload(
            stream=payload.stream,
            schema_version=payload.schema_version,
            payload_json=noncanonical,
            payload_sha256=hashlib.sha256(noncanonical.encode("utf-8")).hexdigest(),
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("JSON no canónico debía rechazarse.")

    oversized = json.dumps(
        {
            "schema_version": "analysis-job-command.v1",
            "padding": "x" * MAX_DELIVERY_PAYLOAD_BYTES,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        PreparedDeliveryPayload(
            stream=DeliveryStream.ANALYSIS_COMMAND,
            schema_version="analysis-job-command.v1",
            payload_json=oversized,
            payload_sha256=hashlib.sha256(oversized.encode("utf-8")).hexdigest(),
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Un payload mayor a 1 MiB debía rechazarse.")


def validate_enum_contract() -> None:
    assert {value.value for value in DeliveryStream} == {
        "analysis_command",
        "analysis_result",
    }
    assert {value.value for value in DeliveryMessageStatus} == {
        "pending",
        "leased",
        "delivered",
        "dead_letter",
    }


def validate_static_boundaries() -> None:
    delivery_dir = BACKEND / "app" / "dbi" / "delivery"
    contracts = (delivery_dir / "contracts.py").read_text(encoding="utf-8").lower()
    repository = (delivery_dir / "repository.py").read_text(encoding="utf-8").lower()
    service = (delivery_dir / "service.py").read_text(encoding="utf-8").lower()

    for forbidden in (
        "sqlalchemy",
        "fastapi",
        "requests",
        "boto3",
        "redis",
        "celery",
    ):
        assert forbidden not in contracts
    for source in (repository, service):
        for forbidden in (
            ".commit(",
            ".rollback(",
            "requests.",
            "boto3",
            "redis",
            "celery",
        ):
            assert forbidden not in source
    assert "skip_locked=true" in repository
    assert "command_sha256" in service
    assert "analysisjobattempt" in service


def main() -> None:
    validate_command_payload()
    validate_result_payload()
    validate_tampering_fails_closed()
    validate_enum_contract()
    validate_static_boundaries()
    print("DBI-QUEUE-001 offline aprobado: contratos canónicos y fronteras puras.")


if __name__ == "__main__":
    main()
