"""Pruebas offline del servicio autorizado de activos DBI."""

from __future__ import annotations

from uuid import uuid4

from app.dbi.asset_registration import DBIAssetRegistrationPlan
from app.dbi.asset_schemas import AnalysisInputAssetRegister
from app.dbi.asset_service import DBIAssetService
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)


class FakeRepository:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[DBIAssetRegistrationPlan] = []

    def persist_registration(self, *, plan: DBIAssetRegistrationPlan) -> bool:
        self.calls.append(plan)
        return self.result


def _request(*, plot_id=None) -> AnalysisInputAssetRegister:
    return AnalysisInputAssetRegister(
        asset_id=uuid4(),
        plot_id=plot_id,
        asset_kind="orthophoto",
        content_type="image/tiff",
        size_bytes=128,
        sha256="a" * 64,
        crs="EPSG:32717",
    )


def _context(*, farm_id, plot_id=None, write=True) -> DBIAccessContext:
    organization = "org-1"
    farms = frozenset({DBIFarmScope(organization_ref=organization, farm_id=farm_id)})
    plots = (
        frozenset({DBIPlotScope(organization_ref=organization, farm_id=farm_id, plot_id=plot_id)})
        if plot_id is not None
        else frozenset()
    )
    permissions = frozenset({DBIPermission.WRITE}) if write else frozenset({DBIPermission.READ})
    return DBIAccessContext(
        principal_ref="principal-1",
        tenant_ref="tenant-1",
        organization_refs=frozenset({organization}),
        farm_scopes=farms,
        plot_scopes=plots,
        permissions=permissions,
    )


def _must_deny(callable_) -> None:
    try:
        callable_()
    except DBIAccessDenied:
        return
    raise AssertionError("La operación debía ser denegada.")


def main() -> None:
    farm_id = uuid4()
    repository = FakeRepository()
    service = DBIAssetService(repository)

    evidence = service.register(
        _context(farm_id=farm_id),
        organization_ref="org-1",
        farm_id=farm_id,
        request=_request(),
    )
    assert evidence.created is True
    assert len(repository.calls) == 1
    assert evidence.plan.tenant_ref == "tenant-1"
    assert evidence.plan.farm_id == farm_id
    assert evidence.plan.created_by_ref == "principal-1"
    assert evidence.plan.metadata.address.object_key.startswith("tenant-1/analysis-inputs/")

    plot_id = uuid4()
    plot_repository = FakeRepository(result=False)
    plot_service = DBIAssetService(plot_repository)
    plot_evidence = plot_service.register(
        _context(farm_id=farm_id, plot_id=plot_id),
        organization_ref="org-1",
        farm_id=farm_id,
        request=_request(plot_id=plot_id),
    )
    assert plot_evidence.created is False
    assert len(plot_repository.calls) == 1

    denied_repository = FakeRepository()
    denied_service = DBIAssetService(denied_repository)
    _must_deny(
        lambda: denied_service.register(
            _context(farm_id=farm_id, write=False),
            organization_ref="org-1",
            farm_id=farm_id,
            request=_request(),
        )
    )
    _must_deny(
        lambda: denied_service.register(
            _context(farm_id=farm_id),
            organization_ref="org-2",
            farm_id=farm_id,
            request=_request(),
        )
    )
    unknown_plot = uuid4()
    _must_deny(
        lambda: denied_service.register(
            _context(farm_id=farm_id),
            organization_ref="org-1",
            farm_id=farm_id,
            request=_request(plot_id=unknown_plot),
        )
    )
    assert denied_repository.calls == []

    print("Servicio autorizado de activos DBI aprobado offline.")


if __name__ == "__main__":
    main()
