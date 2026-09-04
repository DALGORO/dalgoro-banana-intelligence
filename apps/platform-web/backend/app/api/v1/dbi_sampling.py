"""API autorizada de planificación y validación de campo Sampling DBI."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.sampling.api_schemas import (
    DBISamplingObservationRequest,
    DBISamplingPlanCompletionResponse,
    DBISamplingPlanCreateRequest,
    DBISamplingPlanResponse,
    DBISamplingPointMutationResponse,
    DBISamplingPointResponse,
    DBISamplingRejectRequest,
    DBISamplingSubstituteRequest,
)
from app.dbi.sampling.engine import DBISamplingConflict
from app.dbi.sampling.field import DBISamplingFieldService
from app.dbi.sampling.reader import DBISamplingPlanReader, sampling_plan_geojson
from app.dbi.sampling.service import DBISamplingPlanService, DBISamplingUnavailable

router = APIRouter(prefix="/dbi", tags=["dbi-sampling"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]

DBI_SAMPLING_NOT_FOUND_DETAIL = "Sampling DBI no disponible."
DBI_SAMPLING_CONFLICT_DETAIL = "Sampling DBI no supera las verificaciones de integridad."


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DBI_SAMPLING_NOT_FOUND_DETAIL,
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=DBI_SAMPLING_CONFLICT_DETAIL,
    )


def _require_plot(
    context: DBIAccessContext,
    *,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    permission: DBIPermission,
) -> None:
    try:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=permission,
        )
    except DBIAccessDenied as error:
        raise _not_found() from error


def _read_response(
    session: Session,
    context: DBIAccessContext,
    *,
    farm_id: UUID,
    plot_id: UUID,
    plan_id: UUID,
) -> DBISamplingPlanResponse:
    try:
        snapshot = DBISamplingPlanReader(session).read_plan(
            plan_id=plan_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
    except DBISamplingUnavailable as error:
        raise _not_found() from error
    except DBISamplingConflict as error:
        raise _conflict() from error
    return DBISamplingPlanResponse(
        plan_id=snapshot.plan_id,
        schema_version=snapshot.schema_version,
        profile_version=snapshot.profile_version,
        profile=snapshot.profile,
        budget=snapshot.budget,
        boundary_sha256=snapshot.boundary_sha256,
        exclusions_sha256=snapshot.exclusions_sha256,
        boundary=snapshot.boundary,
        exclusions=snapshot.exclusions,
        status=snapshot.status,
        created_at=snapshot.created_at,
        points=tuple(
            DBISamplingPointResponse(
                point_id=point.point_id,
                role=point.role,
                sequence=point.sequence,
                route_order=point.route_order,
                reserve_for_sequence=point.reserve_for_sequence,
                selection_reason=point.selection_reason,
                planned_longitude=point.planned_longitude,
                planned_latitude=point.planned_latitude,
                observed_longitude=point.observed_longitude,
                observed_latitude=point.observed_latitude,
                status=point.status,
                rejection_reason=point.rejection_reason,
                observed_at=point.observed_at,
            )
            for point in snapshot.points
        ),
    )


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/sampling-plans",
    response_model=DBISamplingPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_sampling_plan(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    payload: DBISamplingPlanCreateRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBISamplingPlanResponse:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )
    try:
        evidence = DBISamplingPlanService(session).create_plan(
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            profile=payload.profile,
            created_by_ref=context.principal_ref,
            exclusions=payload.exclusions,
        )
        session.commit()
    except DBISamplingUnavailable as error:
        session.rollback()
        raise _not_found() from error
    except (DBISamplingConflict, IntegrityError) as error:
        session.rollback()
        raise _conflict() from error
    return _read_response(
        session,
        context,
        farm_id=farm_id,
        plot_id=plot_id,
        plan_id=evidence.plan_id,
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/sampling-plans/{plan_id}",
    response_model=DBISamplingPlanResponse,
)
def get_sampling_plan(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    plan_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> DBISamplingPlanResponse:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.READ,
    )
    return _read_response(
        session,
        context,
        farm_id=farm_id,
        plot_id=plot_id,
        plan_id=plan_id,
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/sampling-plans/{plan_id}/geojson",
)
def get_sampling_plan_geojson(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    plan_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> dict:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.READ,
    )
    try:
        snapshot = DBISamplingPlanReader(session).read_plan(
            plan_id=plan_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
    except DBISamplingUnavailable as error:
        raise _not_found() from error
    except DBISamplingConflict as error:
        raise _conflict() from error
    return sampling_plan_geojson(snapshot)


def _commit_mutation(session: Session, operation):
    try:
        evidence = operation()
        session.commit()
        return evidence
    except DBISamplingUnavailable as error:
        session.rollback()
        raise _not_found() from error
    except (DBISamplingConflict, IntegrityError) as error:
        session.rollback()
        raise _conflict() from error


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/sampling-plans/{plan_id}/points/{point_id}/validate",
    response_model=DBISamplingPointMutationResponse,
)
def validate_sampling_point(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    plan_id: UUID,
    point_id: UUID,
    payload: DBISamplingObservationRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBISamplingPointMutationResponse:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )
    evidence = _commit_mutation(
        session,
        lambda: DBISamplingFieldService(session).validate_point(
            plan_id=plan_id,
            point_id=point_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            longitude=payload.longitude,
            latitude=payload.latitude,
            observed_at=payload.observed_at,
        ),
    )
    return DBISamplingPointMutationResponse(**evidence.__dict__)


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/sampling-plans/{plan_id}/points/{point_id}/reject",
    response_model=DBISamplingPointMutationResponse,
)
def reject_sampling_point(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    plan_id: UUID,
    point_id: UUID,
    payload: DBISamplingRejectRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBISamplingPointMutationResponse:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )
    evidence = _commit_mutation(
        session,
        lambda: DBISamplingFieldService(session).reject_point(
            plan_id=plan_id,
            point_id=point_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            rejection_reason=payload.rejection_reason,
            observed_at=payload.observed_at,
        ),
    )
    return DBISamplingPointMutationResponse(**evidence.__dict__)


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/sampling-plans/{plan_id}/points/{point_id}/substitute",
    response_model=DBISamplingPointMutationResponse,
)
def substitute_sampling_point(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    plan_id: UUID,
    point_id: UUID,
    payload: DBISamplingSubstituteRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBISamplingPointMutationResponse:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )
    evidence = _commit_mutation(
        session,
        lambda: DBISamplingFieldService(session).substitute_point(
            plan_id=plan_id,
            primary_point_id=point_id,
            reserve_point_id=payload.reserve_point_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            rejection_reason=payload.rejection_reason,
            longitude=payload.longitude,
            latitude=payload.latitude,
            observed_at=payload.observed_at,
        ),
    )
    return DBISamplingPointMutationResponse(**evidence.__dict__)


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/sampling-plans/{plan_id}/complete",
    response_model=DBISamplingPlanCompletionResponse,
)
def complete_sampling_plan(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    plan_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> DBISamplingPlanCompletionResponse:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )
    evidence = _commit_mutation(
        session,
        lambda: DBISamplingFieldService(session).complete_plan(
            plan_id=plan_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        ),
    )
    return DBISamplingPlanCompletionResponse(
        plan_id=evidence.plan_id,
        status="completed",
        changed=evidence.changed,
    )
