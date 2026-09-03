"""Valida geometrías, contratos y consultas espaciales DBI offline."""

from __future__ import annotations

import inspect
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from pydantic import ValidationError
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects import postgresql

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_spatial.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-spatial-secret")
os.environ.pop("DBI_ENVIRONMENT", None)
os.environ.pop("DBI_DATABASE_URL", None)

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.api.v1 import dbi_spatial, get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.models import Plot  # noqa: E402
from app.dbi.read_schemas import PlotRead, PlotSpatialRead  # noqa: E402
from app.dbi.repositories import PlotRepository  # noqa: E402
from app.dbi.spatial import (  # noqa: E402
    DBI_BOUNDARY_MAX_COORDINATES,
    DBI_SPATIAL_RESULT_LIMIT,
    DBI_SPATIAL_SRID,
    GeoJSONMultiPolygon,
    boundary_from_database,
    boundary_to_database,
)
from app.dbi.write_schemas import PlotCreate, PlotUpdate  # noqa: E402

HEAD = "dbi_0012_durable_delivery"
SPATIAL_REVISION = "dbi_0006_plot_boundaries"
VALID_BOUNDARY = {
    "type": "MultiPolygon",
    "coordinates": [
        [
            [
                [-79.9000, -3.2000],
                [-79.8990, -3.2000],
                [-79.8990, -3.1990],
                [-79.9000, -3.1990],
                [-79.9000, -3.2000],
            ]
        ]
    ],
}


def _assert_validation_error(factory, **kwargs) -> None:
    try:
        factory(**kwargs)
    except ValidationError:
        return
    raise AssertionError(f"{factory.__name__} debía rechazar los datos proporcionados.")


def validate_spatial_contract() -> None:
    payload = GeoJSONMultiPolygon.model_validate(VALID_BOUNDARY)
    assert payload.type == "MultiPolygon"
    assert DBI_SPATIAL_SRID == 4326
    assert DBI_BOUNDARY_MAX_COORDINATES == 10_000
    assert DBI_SPATIAL_RESULT_LIMIT == 20

    _assert_validation_error(
        GeoJSONMultiPolygon,
        type="Polygon",
        coordinates=VALID_BOUNDARY["coordinates"][0],
    )
    _assert_validation_error(
        GeoJSONMultiPolygon,
        type="MultiPolygon",
        coordinates=[[[[-79.9, -3.2], [-79.8, -3.2], [-79.8, -3.1], [-79.9, -3.1]]]],
    )
    _assert_validation_error(
        GeoJSONMultiPolygon,
        type="MultiPolygon",
        coordinates=[[[[181.0, 0.0], [181.0, 1.0], [180.0, 1.0], [181.0, 0.0]]]],
    )
    _assert_validation_error(
        GeoJSONMultiPolygon,
        type="MultiPolygon",
        coordinates=[
            [
                [
                    [-79.9, -3.2],
                    [-79.8, -3.1],
                    [-79.9, -3.1],
                    [-79.8, -3.2],
                    [-79.9, -3.2],
                ]
            ]
        ],
    )

    database_value = boundary_to_database(payload)
    assert isinstance(database_value, WKBElement)
    assert database_value.srid == DBI_SPATIAL_SRID
    assert boundary_from_database(database_value) == payload


def validate_model_metadata() -> None:
    table = Plot.__table__
    boundary = table.columns["boundary"]
    assert boundary.nullable is True
    assert isinstance(boundary.type, Geometry)
    assert boundary.type.geometry_type == "MULTIPOLYGON"
    assert boundary.type.srid == DBI_SPATIAL_SRID
    assert boundary.type.spatial_index is False

    constraint_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_dbi_plots_boundary_not_empty",
        "ck_dbi_plots_boundary_valid",
    }.issubset(constraint_names)

    spatial_index = next(
        index for index in table.indexes if index.name == "ix_dbi_plots_boundary_gist"
    )
    assert spatial_index.dialect_options["postgresql"]["using"] == "gist"


def validate_http_schemas() -> None:
    assert "boundary" not in PlotRead.model_fields
    assert "boundary" in PlotSpatialRead.model_fields

    created = PlotCreate(code="L-001", name="Lote", boundary=VALID_BOUNDARY)
    assert created.boundary is not None

    cleared = PlotUpdate(boundary=None)
    assert cleared.boundary is None
    assert cleared.model_fields_set == {"boundary"}

    stored_boundary = boundary_to_database(created.boundary)
    now = datetime.now(timezone.utc)
    response = PlotSpatialRead.model_validate(
        SimpleNamespace(
            id=uuid4(),
            farm_id=uuid4(),
            code="L-001",
            name="Lote",
            area_hectares=None,
            boundary=stored_boundary,
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    assert response.boundary == created.boundary
    assert response.model_dump(mode="json")["boundary"]["type"] == "MultiPolygon"


class FakeResult:
    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[object]:
        return []


class FakeSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    def execute(self, statement: object) -> FakeResult:
        self.statements.append(statement)
        return FakeResult()


def _compiled_sql(statement: object) -> tuple[str, list[object]]:
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"render_postcompile": True},
    )
    return str(compiled).lower(), list(compiled.params.values())


def validate_summary_query_defers_geometry() -> None:
    session = FakeSession()
    PlotRepository(session).list_by_farm(
        organization_ref="organization-1",
        farm_id=uuid4(),
    )
    sql, _ = _compiled_sql(session.statements[-1])
    assert "dbi_plots.boundary" not in sql


def validate_scoped_spatial_query() -> None:
    empty_session = FakeSession()
    assert PlotRepository(empty_session).list_intersecting_boundary(
        organization_ref="organization-1",
        farm_id=uuid4(),
        plot_ids=frozenset(),
        min_longitude=-80.0,
        min_latitude=-4.0,
        max_longitude=-79.0,
        max_latitude=-3.0,
        limit=DBI_SPATIAL_RESULT_LIMIT,
    ) == ()
    assert empty_session.statements == []

    session = FakeSession()
    farm_id = uuid4()
    plot_ids = frozenset({uuid4(), uuid4()})

    result = PlotRepository(session).list_intersecting_boundary(
        organization_ref="organization-1",
        farm_id=farm_id,
        plot_ids=plot_ids,
        min_longitude=-80.0,
        min_latitude=-4.0,
        max_longitude=-79.0,
        max_latitude=-3.0,
        limit=DBI_SPATIAL_RESULT_LIMIT,
    )
    assert result == []

    sql, values = _compiled_sql(session.statements[-1])
    assert "st_intersects" in sql
    assert "st_makeenvelope" in sql
    assert "dbi_plots.boundary is not null" in sql
    assert "dbi_plots.id in" in sql
    assert "limit" in sql
    assert "organization-1" in values
    assert farm_id in values
    assert DBI_SPATIAL_RESULT_LIMIT in values


def _context(*, read: bool = True) -> tuple[DBIAccessContext, UUID, UUID]:
    farm_id = uuid4()
    plot_id = uuid4()
    permissions = {DBIPermission.READ} if read else {DBIPermission.WRITE}
    return (
        DBIAccessContext(
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
        ),
        farm_id,
        plot_id,
    )


def validate_router_and_authorization() -> None:
    methods = {
        (route.path, method)
        for route in get_api_router().routes
        if route.path.startswith("/dbi/")
        for method in route.methods
    }
    assert (
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/spatial/intersections",
        "GET",
    ) in methods

    context, farm_id, plot_id = _context()
    dbi_spatial._require_farm_read(context, "organization-1", farm_id)
    assert dbi_spatial._authorized_plot_ids(
        context,
        "organization-1",
        farm_id,
    ) == frozenset({plot_id})

    denied_context, denied_farm_id, _ = _context(read=False)
    try:
        dbi_spatial._require_farm_read(
            denied_context,
            "organization-1",
            denied_farm_id,
        )
    except HTTPException as error:
        assert (error.status_code, error.detail) == (
            404,
            "Recurso DBI no encontrado.",
        )
    else:
        raise AssertionError("WRITE sin READ no debe autorizar consulta espacial.")

    invalid = dbi_spatial._invalid_envelope()
    assert (invalid.status_code, invalid.detail) == (
        422,
        "La envolvente espacial DBI es inválida.",
    )


def validate_migration_and_offline_sql() -> None:
    config = Config(str(BACKEND / "dbi_alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(SPATIAL_REVISION)
    assert revision is not None
    assert revision.down_revision == "dbi_0005_identity_memberships"
    assert scripts.get_heads() == [HEAD]

    lineage = {
        item.revision
        for item in scripts.iterate_revisions(HEAD, "base")
    }
    assert SPATIAL_REVISION in lineage
    assert "dbi_0007_admin_audit" in lineage

    output = StringIO()
    environment = {
        "DBI_ENVIRONMENT": "test",
        "DBI_DATABASE_URL": (
            "postgresql+psycopg://dbi_user:dbi-password"
            "@example.internal:5432/dbi_test"
        ),
    }
    with patch.dict(os.environ, environment, clear=True):
        with redirect_stdout(output):
            command.upgrade(config, "head", sql=True)

    sql = output.getvalue().lower()
    compact_sql = "".join(sql.split())
    assert "geometry(multipolygon,4326)" in compact_sql
    assert "ix_dbi_plots_boundary_gist" in sql
    assert "using gist" in sql
    assert "st_isvalid" in sql
    assert "st_isempty" in sql
    assert "dbi_0008_scope_hierarchy" in sql
    assert "create extension" not in sql
    assert "create table users" not in sql
    assert "create table companies" not in sql


def validate_static_boundaries() -> None:
    spatial_source = inspect.getsource(sys.modules["app.dbi.spatial"])
    router_source = inspect.getsource(dbi_spatial)
    repositories_source = inspect.getsource(sys.modules["app.dbi.repositories"])
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")

    assert "make_valid" not in spatial_source
    assert "DBI_SPATIAL_SRID = 4326" in spatial_source
    assert "DBI_SPATIAL_RESULT_LIMIT = 20" in spatial_source
    assert "DBIPermission.READ" in router_source
    assert "DBI_SPATIAL_RESULT_LIMIT" in router_source
    assert "defer(Plot.boundary)" in repositories_source
    for forbidden in (
        "SessionLocal",
        "from app.db.session",
        "app.models.user",
        "app.models.company",
        "DATABASE_URL",
    ):
        assert forbidden not in spatial_source
        assert forbidden not in router_source

    assert "GeoAlchemy2==0.20.0" in requirements
    assert "shapely==2.1.2" in requirements


def main() -> None:
    validate_spatial_contract()
    validate_model_metadata()
    validate_http_schemas()
    validate_summary_query_defers_geometry()
    validate_scoped_spatial_query()
    validate_router_and_authorization()
    validate_migration_and_offline_sql()
    validate_static_boundaries()
    print("Geometrías y consultas espaciales DBI validadas offline.")


if __name__ == "__main__":
    main()
