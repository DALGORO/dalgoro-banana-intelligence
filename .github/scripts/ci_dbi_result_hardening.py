"""Hardening adicional de manifests y aislamiento tenant para DBI-RESULT-001."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / ".github" / "scripts"))

from app.dbi.delivery.contracts import DeliveryStream  # noqa: E402
from app.dbi.models.delivery import DBIDeliveryMessage  # noqa: E402
from app.dbi.results.contracts import DBIResultIngestionConflict  # noqa: E402
from app.dbi.results.repository import DBIResultRepository  # noqa: E402
from app.dbi.results.service import DBIAnalysisResultIngestionService  # noqa: E402
from app.schemas.dbi_analysis_jobs import AnalysisJobResult  # noqa: E402
from ci_dbi_result_integration import (  # noqa: E402
    ATTEMPT_SUCCESS,
    DATABASE,
    HOST,
    JOB_SUCCESS,
    RESULT_ROLE,
    TENANT,
    _factory,
    _object_store,
)


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("El hardening Result sólo corre en GitHub Actions.")
    if os.environ.get("DBI_RESULT_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta habilitar DBI_RESULT_RUN_INTEGRATION.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("El hardening Result exige DBI_ENVIRONMENT=test.")
    url = os.environ.get("DBI_DATABASE_URL", "")
    if RESULT_ROLE not in url or HOST not in url or DATABASE not in url:
        raise RuntimeError("DBI_DATABASE_URL no apunta al rol Result autorizado.")


def _successful_result(factory) -> AnalysisJobResult:
    session = factory()
    try:
        payload_json = session.scalar(
            select(DBIDeliveryMessage.payload_json).where(
                DBIDeliveryMessage.stream == DeliveryStream.ANALYSIS_RESULT.value,
                DBIDeliveryMessage.attempt_id == ATTEMPT_SUCCESS,
            )
        )
        assert payload_json is not None
        result = AnalysisJobResult.model_validate_json(payload_json)
        assert result.status == "succeeded" and len(result.artifacts) == 9
        return result
    finally:
        session.close()


def validate_persisted_manifest_divergence(factory) -> None:
    result = _successful_result(factory)
    original = result.artifacts[0]
    divergent = original.model_copy(
        update={
            "content_type": (
                "application/octet-stream"
                if original.content_type != "application/octet-stream"
                else "application/json"
            )
        }
    )
    session = factory()
    try:
        try:
            DBIResultRepository(session).persist_artifact(
                divergent,
                job_id=JOB_SUCCESS,
                attempt_id=ATTEMPT_SUCCESS,
            )
        except DBIResultIngestionConflict:
            session.rollback()
        else:
            raise AssertionError(
                "un manifest persistido con metadata divergente debía rechazarse."
            )
    finally:
        session.close()


def validate_cross_tenant_object_key(factory, store) -> None:
    result = _successful_result(factory)
    original = result.artifacts[0]
    assert TENANT in original.object_key
    foreign_key = original.object_key.replace(TENANT, "tenant-foreign", 1)
    assert foreign_key != original.object_key
    foreign = original.model_copy(update={"object_key": foreign_key})

    session = factory()
    try:
        service = DBIAnalysisResultIngestionService(session, store)
        try:
            service._verify_artifact(
                foreign,
                tenant_ref=TENANT,
                job_id=JOB_SUCCESS,
            )
        except DBIResultIngestionConflict:
            session.rollback()
        else:
            raise AssertionError(
                "un object_key de otro namespace tenant debía rechazarse."
            )
    finally:
        session.close()


def main() -> None:
    _require_scope()
    engine, factory = _factory(RESULT_ROLE)
    store = _object_store()
    try:
        validate_persisted_manifest_divergence(factory)
        validate_cross_tenant_object_key(factory, store)
    finally:
        engine.dispose()
    print(
        "DBI-RESULT-001 hardening aprobado: manifest divergente y namespace tenant aislado."
    )


if __name__ == "__main__":
    main()
