"""Unidad de trabajo DBI basada en la frontera transaccional autorizada."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.dbi_session import DBISessionFactory, dbi_session_scope
from app.dbi.repositories import (
    AnalysisArtifactRepository,
    AnalysisInputAssetRepository,
    AnalysisJobAttemptRepository,
    AnalysisJobRepository,
    CampaignRepository,
    FarmRepository,
    PlotRepository,
)


@dataclass(frozen=True, slots=True)
class DBIUnitOfWork:
    """Repositorios DBI ligados a una misma sesión y transacción."""

    farms: FarmRepository
    plots: PlotRepository
    campaigns: CampaignRepository
    analysis_jobs: AnalysisJobRepository
    analysis_job_attempts: AnalysisJobAttemptRepository
    analysis_input_assets: AnalysisInputAssetRepository
    analysis_artifacts: AnalysisArtifactRepository
    _session: Session

    @classmethod
    def bind(cls, session: Session) -> DBIUnitOfWork:
        """Construye todos los repositorios sobre una sesión explícita."""

        return cls(
            farms=FarmRepository(session),
            plots=PlotRepository(session),
            campaigns=CampaignRepository(session),
            analysis_jobs=AnalysisJobRepository(session),
            analysis_job_attempts=AnalysisJobAttemptRepository(session),
            analysis_input_assets=AnalysisInputAssetRepository(session),
            analysis_artifacts=AnalysisArtifactRepository(session),
            _session=session,
        )

    def flush(self) -> None:
        """Sincroniza cambios sin confirmar ni cerrar la transacción."""

        self._session.flush()


@contextmanager
def dbi_unit_of_work_scope(
    session_factory: DBISessionFactory,
) -> Iterator[DBIUnitOfWork]:
    """Entrega una unidad de trabajo bajo ``dbi_session_scope``."""

    with dbi_session_scope(session_factory) as session:
        yield DBIUnitOfWork.bind(session)

