"""Operaciones internas INSPECT (instalación explícitamente habilitada).

El router no se incluye sin DBI_INSPECT_STAFF_HTTP_ENABLED=1 en el SERVIDOR.
Nunca toma identidad, cargos, tenant ni permiso de un cuerpo HTTP. Todas las
operaciones pasan por StaffWorkflow, un directorio institucional SQL en la
misma Session, y un único COMMIT con sus eventos auditables.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.authorization import DBIAccessContext, DBIAccessDenied
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.inspection.campaign_link_service import (
    DBIInspectionCampaignLinkUnavailable,
)
from app.dbi.inspection.dual_approval import DBIInspectionApprovalConflict
from app.dbi.inspection.institutional_staff_directory import (
    DBIInspectionInstitutionalStaffDirectory,
)
from app.dbi.inspection.repository import DBIInspectionConflict
from app.dbi.inspection.staff_workflow import DBIInspectionStaffWorkflow


router = APIRouter(prefix="/dbi", tags=["dbi-inspection-staff"])
SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
T = TypeVar("T")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DBIInspectionLinkRequest(_StrictModel):
    observation_id: UUID
    observation_version_id: UUID


class DBIInspectionLinkResponse(_StrictModel):
    link_id: UUID
    created: bool


class DBIInspectionSignatureRequest(_StrictModel):
    """Cuerpo obligatorio vacío: no admite identidad ni cargo suministrado."""


class DBIInspectionSignatureResponse(_StrictModel):
    stage: Literal["technical_validated", "dual_approved", "self_approved"]


def _workflow(session: Session) -> DBIInspectionStaffWorkflow:
    # Sólo autoridad del backend SQL; prohibido inyectar cargos por HTTP.
    return DBIInspectionStaffWorkflow(
        session,
        staff_directory=DBIInspectionInstitutionalStaffDirectory(session),
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Operación institucional INSPECT no disponible.",
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="INSPECT no cumple los requisitos de vínculo o aprobación.",
    )


def _institutional_write(session: Session, operation: Callable[[], T]) -> T:
    """Un solo COMMIT: el lock de cargos sigue vivo hasta guardar la firma."""
    try:
        result = operation()
        session.commit()
        return result
    except (DBIAccessDenied, DBIInspectionCampaignLinkUnavailable) as error:
        session.rollback()
        raise _not_found() from error
    except (
        DBIInspectionConflict,
        DBIInspectionApprovalConflict,
        IntegrityError,
    ) as error:
        session.rollback()
        raise _conflict() from error
    except Exception:
        session.rollback()
        raise


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/inspection-links",
    response_model=DBIInspectionLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
def propose_inspection_campaign_link(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    campaign_id: UUID,
    payload: DBIInspectionLinkRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBIInspectionLinkResponse:
    def operation() -> DBIInspectionLinkResponse:
        link, created = _workflow(session).propose_link(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            campaign_id=campaign_id,
            observation_id=payload.observation_id,
            observation_version_id=payload.observation_version_id,
        )
        return DBIInspectionLinkResponse(link_id=link.id, created=created)

    return _institutional_write(session, operation)


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/inspection-links/{link_id}/technical-validation",
    response_model=DBIInspectionSignatureResponse,
)
def validate_inspection_technical(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    link_id: UUID,
    payload: DBIInspectionSignatureRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBIInspectionSignatureResponse:
    def operation() -> DBIInspectionSignatureResponse:
        state = _workflow(session).validate_technical(
            context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, link_id=link_id,
        )
        return DBIInspectionSignatureResponse(stage=state.stage)

    return _institutional_write(session, operation)


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/inspection-links/{link_id}/administrative-authorization",
    response_model=DBIInspectionSignatureResponse,
)
def authorize_inspection_administrative(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    link_id: UUID,
    payload: DBIInspectionSignatureRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBIInspectionSignatureResponse:
    def operation() -> DBIInspectionSignatureResponse:
        state = _workflow(session).authorize_administrative(
            context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, link_id=link_id,
        )
        return DBIInspectionSignatureResponse(stage=state.stage)

    return _institutional_write(session, operation)
