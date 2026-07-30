"""Valida escrituras DBI autorizadas y transaccionales offline."""

from __future__ import annotations

import inspect
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_authorized_writes.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-authorized-writes-secret")
os.environ.pop("DBI_ENVIRONMENT", None)
os.environ.pop("DBI_DATABASE_URL", None)

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.api.v1 import dbi_writes, get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.write_schemas import (  # noqa: E402
    CampaignCreate,
    FarmCreate,
    FarmUpdate,
    PlotCreate,
)


def _context(*, write: bool = True):
    farm_id = uuid4()
    plot_id = uuid4()
    permissions = {DBIPermission.WRITE} if write else {DBIPermission.READ}
    context = DBIAccessContext(
        principal_ref="principal-1",
        tenant_ref="tenant-1",
        organization_refs=frozenset({"organization-1"}),
        farm_scopes=frozenset(
            {DBIFarmScope(organization_ref="organization-1", farm_id=farm_id)}
        ),
        plot_scopes=frozenset(
            {
                DBIPlotScope(
                    organization_ref="organization-1",
                    farm_id=farm_id,
                    plot_id=plot_id,
                )
            }
        ),
        permissions=frozenset(permissions),
    )
    return context, farm_id, plot_id


def validate_router_contract() -> None:
    methods = {
        (route.path, method)
        for route in get_api_router().routes
        if route.path.startswith("/dbi/")
        for method in route.methods
    }
    expected = {
        ("/dbi/organizations/{organization_ref}/farms", "POST"),
        ("/dbi/organizations/{organization_ref}/farms/{farm_id}", "PATCH"),
        ("/dbi/organizations/{organization_ref}/farms/{farm_id}/plots", "POST"),
        (
            "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}",
            "PATCH",
        ),
        ("/dbi/organizations/{organization_ref}/farms/{farm_id}/campaigns", "POST"),
        (
            "/dbi/organizations/{organization_ref}/farms/{farm_id}/campaigns/{campaign_id}",
            "PATCH",
        ),
    }
    assert expected.issubset(methods)


def validate_strict_contracts() -> None:
    try:
        FarmCreate(code="F-1", name="Finca", internal=True)
    except ValidationError:
        pass
    else:
        raise AssertionError("Los contratos deben rechazar campos desconocidos.")

    try:
        FarmUpdate()
    except ValidationError:
        pass
    else:
        raise AssertionError("Una actualización vacía debía rechazarse.")

    try:
        PlotCreate(code="L-1", name="Lote", area_hectares=0)
    except ValidationError:
        pass
    else:
        raise AssertionError("El área no positiva debía rechazarse.")

    now = datetime.now(timezone.utc)
    try:
        CampaignCreate(
            code="C-1",
            name="Campaña",
            starts_at=now,
            ends_at=now.replace(year=now.year - 1),
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("El orden temporal inválido debía rechazarse.")


def validate_write_permission() -> None:
    context, _, _ = _context(write=False)
    try:
        dbi_writes._require_organization_write(context, "organization-1")
    except HTTPException as error:
        assert (error.status_code, error.detail) == (
            404,
            "Recurso DBI no encontrado.",
        )
    else:
        raise AssertionError("READ no debe autorizar escrituras.")


def validate_transaction_success() -> None:
    entity = SimpleNamespace()

    class RecordingSession:
        def __init__(self):
            self.commits = 0
            self.refreshes = 0
            self.rollbacks = 0

        def commit(self):
            self.commits += 1

        def refresh(self, value):
            assert value is entity
            self.refreshes += 1

        def rollback(self):
            self.rollbacks += 1

    session = RecordingSession()
    result = dbi_writes._commit_and_refresh(session, entity)
    assert result is entity
    assert (session.commits, session.refreshes, session.rollbacks) == (1, 1, 0)


def validate_transaction_conflict() -> None:
    class ConflictSession:
        def __init__(self):
            self.rollbacks = 0

        def commit(self):
            raise IntegrityError("statement", {}, Exception("duplicate"))

        def refresh(self, value):
            raise AssertionError("No debe refrescar tras conflicto.")

        def rollback(self):
            self.rollbacks += 1

    session = ConflictSession()
    try:
        dbi_writes._commit_and_refresh(session, SimpleNamespace())
    except HTTPException as error:
        assert (error.status_code, error.detail) == (
            409,
            "La escritura DBI entra en conflicto con datos existentes.",
        )
    else:
        raise AssertionError("El conflicto debía traducirse a 409.")
    assert session.rollbacks == 1


def validate_explicit_updates() -> None:
    entity = SimpleNamespace(name="Inicial", status="active", code="F-1")
    dbi_writes._apply_updates(
        entity,
        {"name": "Nueva", "code": "ALTERADO"},
        dbi_writes.FARM_UPDATE_FIELDS,
    )
    assert entity.name == "Nueva"
    assert entity.code == "F-1"


def validate_static_boundaries() -> None:
    source = inspect.getsource(dbi_writes)
    for forbidden in (
        "SessionLocal",
        "from app.db.session",
        "app.models.user",
        "app.models.company",
        "payload.__dict__",
        "setattr(entity, field_name, changes[field_name])\n    for",
    ):
        assert forbidden not in source
    assert "DBIPermission.WRITE" in source
    assert "session.commit()" in source
    assert "session.refresh(entity)" in source
    assert "session.rollback()" in source
    assert "model_dump(exclude_unset=True)" in source


if __name__ == "__main__":
    validate_router_contract()
    validate_strict_contracts()
    validate_write_permission()
    validate_transaction_success()
    validate_transaction_conflict()
    validate_explicit_updates()
    validate_static_boundaries()
    print("Escrituras DBI autorizadas validadas offline.")
