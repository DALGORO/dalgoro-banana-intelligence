"""Proyección de sólo lectura del portafolio agrícola autorizado.

La identidad procede exclusivamente del usuario autenticado, nunca de
un tenant indicado por el navegador. Los ámbitos los resuelve DBI.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.authorization import DBIAccessDenied, DBIPermission
from app.dbi.identity import DBIAccessContextResolver, DBIIdentityRepository
from app.dbi.models.agriculture import Farm, Plot
from app.dbi.models.identity import (
    DBIMembership, DBIMembershipStatus, DBIPrincipalStatus,
)

PORTAL_ACCOUNT_LIMIT = 32
PORTAL_FARM_LIMIT = 100
PORTAL_PLOT_LIMIT = 300


class PortalPlot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str
    code: str
    area_hectares: float | None


class PortalFarm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    organization_ref: str
    name: str
    code: str
    plots: list[PortalPlot]
    can_publish_layers: bool


class PortalAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_ref: str
    farms: list[PortalFarm]


def read_portal_accounts(session: Session, *, authenticated_user_id: int) -> list[PortalAccount]:
    """Lista fincas/lotes visibles con membresía activa y READ real.

    Sin DBIPrincipal o membresía: lista vacía; nunca toma empresas del
    usuario legacy como equivalente de autorización agrícola DBI.
    """
    identity = str(authenticated_user_id)
    repo = DBIIdentityRepository(session)
    principals = repo.list_principals(legacy_identity_ref=identity)
    if len(principals) != 1 or principals[0].status != DBIPrincipalStatus.ACTIVE.value:
        return []

    principal = principals[0]
    memberships = session.execute(
        select(DBIMembership.tenant_ref)
        .where(
            DBIMembership.principal_id == principal.id,
            DBIMembership.status == DBIMembershipStatus.ACTIVE.value,
        )
        .order_by(DBIMembership.tenant_ref)
        .limit(PORTAL_ACCOUNT_LIMIT)
    ).scalars().all()

    accounts: list[PortalAccount] = []
    resolver = DBIAccessContextResolver(repo)
    for tenant_ref in memberships:
        try:
            context = resolver.resolve(
                legacy_identity_ref=identity, tenant_ref=tenant_ref
            )
        except DBIAccessDenied:
            continue

        if DBIPermission.READ not in context.permissions or not context.farm_scopes:
            continue

        farm_ids = frozenset(scope.farm_id for scope in context.farm_scopes)
        farms = session.execute(
            select(Farm)
            .where(
                Farm.id.in_(farm_ids),
                Farm.organization_ref.in_(context.organization_refs),
                Farm.status != "archived",
            )
            .order_by(Farm.name, Farm.id)
            .limit(PORTAL_FARM_LIMIT)
        ).scalars().all()

        allowed_farms = {
            (scope.organization_ref, scope.farm_id)
            for scope in context.farm_scopes
        }
        farms = [
            farm for farm in farms
            if (farm.organization_ref, farm.id) in allowed_farms
        ]
        plot_ids = frozenset(scope.plot_id for scope in context.plot_scopes)
        authorized_plot_scope = frozenset(
            (scope.farm_id, scope.plot_id) for scope in context.plot_scopes
        )
        plots = (
            session.execute(
                select(Plot)
                .where(
                    Plot.id.in_(plot_ids),
                    Plot.farm_id.in_([farm.id for farm in farms]),
                    Plot.status != "archived",
                )
                .order_by(Plot.name, Plot.id)
                .limit(PORTAL_PLOT_LIMIT)
            ).scalars().all()
            if plot_ids and farms else []
        )

        plots_by_farm: dict[UUID, list[PortalPlot]] = {farm.id: [] for farm in farms}
        for plot in plots:
            if (plot.farm_id, plot.id) not in authorized_plot_scope:
                continue
            if plot.farm_id in plots_by_farm:
                plots_by_farm[plot.farm_id].append(
                    PortalPlot(
                        id=plot.id, code=plot.code, name=plot.name,
                        area_hectares=float(plot.area_hectares)
                        if plot.area_hectares is not None else None,
                    )
                )

        accounts.append(
            PortalAccount(
                tenant_ref=tenant_ref,
                farms=[
                    PortalFarm(
                        id=farm.id,
                        organization_ref=farm.organization_ref,
                        name=farm.name,
                        code=farm.code,
                        plots=plots_by_farm[farm.id],
                        can_publish_layers=DBIPermission.MANAGE in context.permissions,
                    )
                    for farm in farms
                ],
            )
        )
    return accounts
