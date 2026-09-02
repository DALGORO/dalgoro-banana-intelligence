"""Frontera HTTP transaccional para trabajos geoespaciales DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.jobs.api_schemas import AnalysisJobTransitionResponse
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
    AnalysisProfileUnavailable,
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

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


def get_dbi_analysis_profile_policy(request: Request) -> AnalysisProfilePolicy:
    """Obtiene una política confiable configurada exclusivamente por el servidor."""

    policy = getattr(request.app.state, "dbi_analysis_profile_policy", None)
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
) -> AnalysisJobCreateResponse:
    """Crea un trabajo accepted sin binarios, cola, intento ni ejecución."""

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
        raise _not_found() from error
    except (
        AnalysisJobPersistenceConflict,
        InvalidAnalysisJobTransition,
        IntegrityError,
    ) as error:
        session.rollback()
        raise _conflict() from error
    except AnalysisProfileUnavailable as error:
        session.rollback()
        raise _profile_unavailable() from error

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
) -> AnalysisJobTransitionResponse:
    """Solicita cancelación solo cuando la máquina de estados la admite."""

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
        raise _not_found() from error
    except (
        AnalysisJobPersistenceConflict,
        InvalidAnalysisJobTransition,
        IntegrityError,
    ) as error:
        session.rollback()
        raise _conflict() from error

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
) -> AnalysisJobTransitionResponse:
    """Reencola lógicamente un failed sin crear intento ni publicar mensajes."""

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
        raise _not_found() from error
    except (
        AnalysisJobPersistenceConflict,
        InvalidAnalysisJobTransition,
        IntegrityError,
    ) as error:
        session.rollback()
        raise _conflict() from error

    return AnalysisJobTransitionResponse(
        job_id=evidence.snapshot.job_id,
        status=evidence.snapshot.status,
        accepted_at=evidence.snapshot.accepted_at,
        updated_at=evidence.snapshot.updated_at,
        changed=evidence.changed,
    )
