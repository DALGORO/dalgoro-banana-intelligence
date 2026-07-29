"""Valida repositorios y unidad de trabajo DBI completamente offline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.dialects import postgresql

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.dbi.repositories import (  # noqa: E402
    AnalysisArtifactRepository,
    AnalysisInputAssetRepository,
    AnalysisJobAttemptRepository,
    AnalysisJobRepository,
    CampaignRepository,
    FarmRepository,
    PlotRepository,
)
from app.dbi.unit_of_work import (  # noqa: E402
    DBIUnitOfWork,
    dbi_unit_of_work_scope,
)


class ExpectedOperationError(RuntimeError):
    """Error controlado para validar rollback."""


class FakeResult:
    """Resultado escalar mínimo para consultas de repositorio."""

    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class FakeSession:
    """Doble de sesión que registra consultas y frontera transaccional."""

    def __init__(self, result: object | None = None) -> None:
        self.result = result
        self.statements: list[Any] = []
        self.added: list[object] = []
        self.events: list[str] = []

    def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.result)

    def add(self, entity: object) -> None:
        self.added.append(entity)

    def flush(self) -> None:
        self.events.append("flush")

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.events.append("close")


def _compiled(statement: Any) -> tuple[str, set[object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled).lower(), set(compiled.params.values())


def validate_scoped_reads() -> None:
    """Comprueba que cada lectura conserva su ámbito obligatorio."""

    sentinel = object()
    session = FakeSession(result=sentinel)
    organization_ref = "org-scope"
    tenant_ref = "tenant-scope"
    entity_id = uuid4()

    calls = (
        (
            FarmRepository(session).get_by_id,
            {"organization_ref": organization_ref, "farm_id": entity_id},
            {"dbi_farms"},
            {organization_ref, entity_id},
        ),
        (
            FarmRepository(session).get_by_code,
            {"organization_ref": organization_ref, "code": "F-001"},
            {"dbi_farms"},
            {organization_ref, "F-001"},
        ),
        (
            PlotRepository(session).get_by_id,
            {"organization_ref": organization_ref, "plot_id": entity_id},
            {"dbi_plots", "dbi_farms"},
            {organization_ref, entity_id},
        ),
        (
            CampaignRepository(session).get_by_id,
            {
                "organization_ref": organization_ref,
                "campaign_id": entity_id,
            },
            {"dbi_campaigns", "dbi_farms"},
            {organization_ref, entity_id},
        ),
        (
            AnalysisJobRepository(session).get_by_id,
            {"tenant_ref": tenant_ref, "job_id": entity_id},
            {"dbi_analysis_jobs"},
            {tenant_ref, entity_id},
        ),
        (
            AnalysisJobAttemptRepository(session).get_by_id,
            {"tenant_ref": tenant_ref, "attempt_id": entity_id},
            {"dbi_analysis_job_attempts", "dbi_analysis_jobs"},
            {tenant_ref, entity_id},
        ),
        (
            AnalysisInputAssetRepository(session).get_by_id,
            {"tenant_ref": tenant_ref, "asset_id": entity_id},
            {"dbi_analysis_input_assets"},
            {tenant_ref, entity_id},
        ),
        (
            AnalysisArtifactRepository(session).get_by_id,
            {"tenant_ref": tenant_ref, "artifact_id": entity_id},
            {"dbi_analysis_artifacts", "dbi_analysis_jobs"},
            {tenant_ref, entity_id},
        ),
    )

    for method, arguments, expected_tables, expected_values in calls:
        assert method(**arguments) is sentinel
        sql, values = _compiled(session.statements[-1])
        assert expected_tables.issubset(set(sql.split()))
        assert expected_values.issubset(values)


def validate_idempotent_job_lookup() -> None:
    """Comprueba la clave lógica tenant + request_id."""

    session = FakeSession()
    AnalysisJobRepository(session).get_by_request_id(
        tenant_ref="tenant-scope",
        request_id="request-001",
    )
    sql, values = _compiled(session.statements[-1])
    assert "dbi_analysis_jobs.tenant_ref" in sql
    assert "dbi_analysis_jobs.request_id" in sql
    assert {"tenant-scope", "request-001"}.issubset(values)


def validate_add_without_transaction_side_effects() -> None:
    """Comprueba que añadir no confirma, revierte o cierra."""

    repositories = (
        FarmRepository,
        PlotRepository,
        CampaignRepository,
        AnalysisJobRepository,
        AnalysisJobAttemptRepository,
        AnalysisInputAssetRepository,
        AnalysisArtifactRepository,
    )
    session = FakeSession()

    for repository_type in repositories:
        entity = object()
        assert repository_type(session).add(entity) is entity

    assert len(session.added) == len(repositories)
    assert session.events == []


def _repository_sessions(unit_of_work: DBIUnitOfWork) -> set[object]:
    return {
        unit_of_work.farms._session,
        unit_of_work.plots._session,
        unit_of_work.campaigns._session,
        unit_of_work.analysis_jobs._session,
        unit_of_work.analysis_job_attempts._session,
        unit_of_work.analysis_input_assets._session,
        unit_of_work.analysis_artifacts._session,
    }


def validate_successful_unit_of_work() -> None:
    """Comprueba sesión única, flush explícito, commit y cierre."""

    session = FakeSession()
    with dbi_unit_of_work_scope(lambda: session) as unit_of_work:
        assert _repository_sessions(unit_of_work) == {session}
        unit_of_work.flush()

    assert session.events == ["flush", "commit", "close"]


def validate_failed_unit_of_work() -> None:
    """Comprueba rollback, cierre y propagación ante error."""

    session = FakeSession()

    try:
        with dbi_unit_of_work_scope(lambda: session) as unit_of_work:
            assert _repository_sessions(unit_of_work) == {session}
            raise ExpectedOperationError("operación rechazada")
    except ExpectedOperationError as error:
        assert str(error) == "operación rechazada"
    else:
        raise AssertionError("El error de la unidad de trabajo no se propagó.")

    assert session.events == ["rollback", "close"]


def validate_source_boundaries() -> None:
    """Bloquea recursos, transacciones duplicadas e infraestructura."""

    repositories_source = (
        BACKEND_ROOT / "app" / "dbi" / "repositories.py"
    ).read_text(encoding="utf-8").lower()
    unit_of_work_source = (
        BACKEND_ROOT / "app" / "dbi" / "unit_of_work.py"
    ).read_text(encoding="utf-8").lower()

    for forbidden in (
        "create_engine",
        "sessionmaker",
        "app.db.session",
        "app.core.config",
        ".connect(",
        ".commit(",
        ".rollback(",
        ".close(",
        ".delete(",
        "celery",
        "redis",
        "rabbit",
        "boto",
        "google.cloud.storage",
        "pipeline_orchestrator",
        "run_full_pipeline",
        "fastapi",
    ):
        assert forbidden not in repositories_source

    assert "dbi_session_scope" in unit_of_work_source
    for forbidden in (
        "create_engine",
        "sessionmaker(",
        "app.db.session",
        "app.core.config",
        ".connect(",
        ".commit(",
        ".rollback(",
        ".close(",
        "fastapi",
    ):
        assert forbidden not in unit_of_work_source


def main() -> None:
    """Ejecuta todas las barreras del acceso DBI offline."""

    validate_scoped_reads()
    validate_idempotent_job_lookup()
    validate_add_without_transaction_side_effects()
    validate_successful_unit_of_work()
    validate_failed_unit_of_work()
    validate_source_boundaries()
    print("Repositorios y unidad de trabajo DBI: validación offline aprobada.")


if __name__ == "__main__":
    main()
