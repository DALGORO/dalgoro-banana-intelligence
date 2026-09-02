"""Frontera HTTP transaccional para trabajos geoespaciales DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter_ns
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.jobs.api_schemas import AnalysisJobTransitionResponse
from app.dbi.jobs.metrics import DBIAnalysisJobMetrics
from app.dbi.jobs.persistence_contracts import (
    AnalysisJobPersistenceConflict,
    AnalysisJobResourceUnavailable,
)
from app.dbi.jobs.repository import DBIAnalysisJobRepository
from app.dbi.jobs.service import DBIAnalysisJobService
from app.dbi.jobs.service_contracts import (
    AnalysisJobCreateRequest,
    AnalysisJobCreateResponse,
    AnalysisProfilePolicy,
    AnalysisProfileResolutionContext,
    AnalysisProfileUnavailable,
    ApprovedAnalysisProfile,
)
from app.dbi.jobs.state_machine import InvalidAnalysisJobTransition

router = APIRouter(prefix="/dbi", tags=["dbi-analysis-jobs"])

DBI_ANALYSIS_JOB_NOT_FOUND_DETAIL = "Trabajo DBI no disponible."
DBI_ANALYSIS_JOB_CONFLICT_DETAIL = (
    "La operación del trabajo entra en conflicto con su estado actual."
)
DBI_ANALYSIS_PROFILE_UNAVAILABLE_DETAIL = (
    "No existe un perfil de análisis DBI aprobado disponible."
)
DBI_ANALYSIS_JOB_METRICS_UNAVAILABLE_DETAIL = (
    "La instrumentación agregada de trabajos DBI no está disponible."
)

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
_DEFAULT_ANALYSIS_JOB_METRICS = DBIAnalysisJobMetrics()


class _UnavailableAnalysisProfilePolicy:
    """Política cerrada usada mientras DBI-ML-001 no inyecte una aprobada."""

    def resolve(
        self,
        *,
        context: AnalysisProfileResolutionContext,
    ) -> ApprovedAnalysisProfile:
        del context
        raise AnalysisProfileUnavailable(
            "No existe una política de perfil aprobada configurada."
        )


_UNAVAILABLE_ANALYSIS_PROFILE_POLICY = _UnavailableAnalysisProfilePolicy()


def get_dbi_analysis_profile_policy(request: Request) -> AnalysisProfilePolicy:
    """Obtiene la política confiable del servidor o una política fail-closed."""

    policy = getattr(request.app.state, "dbi_analysis_profile_policy", None)
    if policy is None:
        return _UNAVAILABLE_ANALYSIS_PROFILE_POLICY
    if not isinstance(policy, AnalysisProfilePolicy):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DBI_ANALYSIS_PROFILE_UNAVAILABLE_DETAIL,
        )
    return policy


ProfilePolicyDependency = Annotated[
    AnalysisProfilePolicy,
    Depends(get_dbi_analysis_profile_policy),
]


def get_dbi_analysis_job_metrics(request: Request) -> DBIAnalysisJobMetrics:
    """Obtiene métricas agregadas sin etiquetas ni identificadores sensibles."""

    metrics = getattr(request.app.state, "dbi_analysis_job_metrics", None)
    if metrics is None:
        return _DEFAULT_ANALYSIS_JOB_METRICS
    if not isinstance(metrics, DBIAnalysisJobMetrics):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DBI_ANALYSIS_JOB_METRICS_UNAVAILABLE_DETAIL,
        )
    return metrics


MetricsDependency = Annotated[
    DBIAnalysisJobMetrics,
    Depends(get_dbi_analysis_job_metrics),
]


def get_dbi_analysis_job_service(
    session: SessionDependency,
) -> DBIAnalysisJobService:
    return DBIAnalysisJobService(DBIAnalysisJobRepository(session))


AnalysisJobServiceDependency = Annotated[
    DBIAnalysisJobService,
    Depends(get_dbi_analysis_job_service),
]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DBI_ANALYSIS_JOB_NOT_FOUND_DETAIL,
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=DBI_ANALYSIS_JOB_CONFLICT_DETAIL,
    )


def _profile_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=DBI_ANALYSIS_PROFILE_UNAVAILABLE_DETAIL,
    )


def _observe_duration(metrics: DBIAnalysisJobMetrics, started_at: int) -> None:
    elapsed = max(1, (perf_counter_ns() - started_at + 999) // 1_000)
    metrics.add(service_duration_microseconds=elapsed)


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/jobs",
    response_model=AnalysisJobCreateResponse,
)
def create_analysis_job(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    payload: AnalysisJobCreateRequest,
    response: Response,
    session: SessionDependency,
    context: AccessDependency,
    profile_policy: ProfilePolicyDependency,
    service: AnalysisJobServiceDependency,
    metrics: MetricsDependency,
) -> AnalysisJobCreateResponse:
    """Crea un trabajo accepted sin binarios, cola, intento ni ejecución."""

    metrics.add(create_attempts=1)
    started_at = perf_counter_ns()
    try:
        evidence = service.create(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            request=payload,
            profile_policy=profile_policy,
            accepted_at=datetime.now(timezone.utc),
        )
        session.commit()
    except (DBIAccessDenied, AnalysisJobResourceUnavailable) as error:
        session.rollback()
        metrics.add(unavailable_resources=1, rollbacks=1)
        raise _not_found() from error
    except (
        AnalysisJobPersistenceConflict,
        InvalidAnalysisJobTransition,
        IntegrityError,
    ) as error:
        session.rollback()
        metrics.add(create_conflicts=1, rollbacks=1)
        raise _conflict() from error
    except AnalysisProfileUnavailable as error:
        session.rollback()
        metrics.add(unavailable_profiles=1, rollbacks=1)
        raise _profile_unavailable() from error
    finally:
        _observe_duration(metrics, started_at)

    if evidence.created:
        metrics.add(jobs_created=1)
    else:
        metrics.add(exact_reuses=1)
    response.status_code = (
        status.HTTP_201_CREATED
        if evidence.created
        else status.HTTP_200_OK
    )
    return AnalysisJobCreateResponse(
        job_id=evidence.snapshot.job_id,
        status=evidence.snapshot.status,
        accepted_at=evidence.snapshot.accepted_at,
        created=evidence.created,
    )


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/cancel",
    response_model=AnalysisJobTransitionResponse,
)
def cancel_analysis_job(
    organization_ref: str,
    farm_id: UUID,
    job_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
    service: AnalysisJobServiceDependency,
    metrics: MetricsDependency,
) -> AnalysisJobTransitionResponse:
    """Solicita cancelación solo cuando la máquina de estados la admite."""

    metrics.add(cancel_attempts=1)
    started_at = perf_counter_ns()
    try:
        evidence = service.cancel(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            job_id=job_id,
            changed_at=datetime.now(timezone.utc),
        )
        session.commit()
    except (DBIAccessDenied, AnalysisJobResourceUnavailable) as error:
        session.rollback()
        metrics.add(unavailable_resources=1, rollbacks=1)
        raise _not_found() from error
    except (
        AnalysisJobPersistenceConflict,
        InvalidAnalysisJobTransition,
        IntegrityError,
    ) as error:
        session.rollback()
        metrics.add(create_conflicts=1, rollbacks=1)
        raise _conflict() from error
    finally:
        _observe_duration(metrics, started_at)

    metrics.add(
        **({"cancel_changes": 1} if evidence.changed else {"cancel_noops": 1})
    )
    return AnalysisJobTransitionResponse(
        job_id=evidence.snapshot.job_id,
        status=evidence.snapshot.status,
        accepted_at=evidence.snapshot.accepted_at,
        updated_at=evidence.snapshot.updated_at,
        changed=evidence.changed,
    )


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/retry",
    response_model=AnalysisJobTransitionResponse,
)
def retry_analysis_job(
    organization_ref: str,
    farm_id: UUID,
    job_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
    service: AnalysisJobServiceDependency,
    metrics: MetricsDependency,
) -> AnalysisJobTransitionResponse:
    """Reencola lógicamente un failed sin crear intento ni publicar mensajes."""

    metrics.add(retry_attempts=1)
    started_at = perf_counter_ns()
    try:
        evidence = service.retry(
            context,
            organization_ref=organization_ref,
            farm_id=farm_id,
            job_id=job_id,
            changed_at=datetime.now(timezone.utc),
        )
        session.commit()
    except (DBIAccessDenied, AnalysisJobResourceUnavailable) as error:
        session.rollback()
        metrics.add(unavailable_resources=1, rollbacks=1)
        raise _not_found() from error
    except (
        AnalysisJobPersistenceConflict,
        InvalidAnalysisJobTransition,
        IntegrityError,
    ) as error:
        session.rollback()
        metrics.add(create_conflicts=1, rollbacks=1)
        raise _conflict() from error
    finally:
        _observe_duration(metrics, started_at)

    metrics.add(
        **({"retry_changes": 1} if evidence.changed else {"retry_noops": 1})
    )
    return AnalysisJobTransitionResponse(
        job_id=evidence.snapshot.job_id,
        status=evidence.snapshot.status,
        accepted_at=evidence.snapshot.accepted_at,
        updated_at=evidence.snapshot.updated_at,
        changed=evidence.changed,
    )
