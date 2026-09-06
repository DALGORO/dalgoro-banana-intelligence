"""Integración PostgreSQL de persistencia derivada DBI-MULTI-001."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.models.multispectral import DBIMultispectralExtractionRecord  # noqa: E402
from app.dbi.multispectral import (  # noqa: E402
    DBIMultispectralExtractionCandidate,
    DBIMultispectralExtractionRepository,
    DBIMultispectralPersistenceConflict,
    DBISpectralVariableSummary,
    multispectral_extraction_id,
)

HOST = "127.0.0.1"
PORT = 5432
DATABASE = "dbi_test"
ADMIN_ROLE = "postgres"
MULTI_ROLE = "dbi_test_multispectral"
TENANT = "tenant-multi-ci"
ORGANIZATION = "organization-multi-ci"
FARM_ID = UUID("10000000-0000-4000-8000-000000000080")
PLOT_ID = UUID("20000000-0000-4000-8000-000000000080")
OBSERVATION_ID = UUID("60000000-0000-4000-8000-000000000080")
OBSERVATION_VERSION_ID = UUID("70000000-0000-4000-8000-000000000081")
SCIENTIFIC_RASTER_ID = UUID("80000000-0000-4000-8000-000000000080")
RGB_RASTER_ID = UUID("80000000-0000-4000-8000-000000000081")
STACK_FINGERPRINT = "a" * 64
EMPTY_PAYLOAD_SHA256 = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
BOUNDARY_WKT = (
    "MULTIPOLYGON((("
    "-79.9350 -3.2800,"
    "-79.9150 -3.2800,"
    "-79.9150 -3.2600,"
    "-79.9350 -3.2600,"
    "-79.9350 -3.2800"
    ")))"
)

_INDEX_FORMULAS = {
    "ndvi": ("ndvi_v1", "(nir-red)/(nir+red)"),
    "ndre": ("ndre_v1", "(nir-red_edge)/(nir+red_edge)"),
    "gndvi": ("gndvi_v1", "(nir-green)/(nir+green)"),
    "evi2": ("evi2_v1", "2.5*(nir-red)/(nir+2.4*red+1)"),
    "ci_red_edge": ("ci_red_edge_v1", "(nir/red_edge)-1"),
    "ci_green": ("ci_green_v1", "(nir/green)-1"),
}


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración MULTI sólo corre en GitHub Actions.")
    if os.environ.get("DBI_MULTI_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta habilitar DBI_MULTI_RUN_INTEGRATION.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración MULTI exige DBI_ENVIRONMENT=test.")
    url = os.environ.get("DBI_DATABASE_URL", "")
    if MULTI_ROLE not in url or HOST not in url or DATABASE not in url:
        raise RuntimeError("DBI_DATABASE_URL no apunta al rol MULTI autorizado.")


def _admin_connect():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=ADMIN_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _url() -> str:
    return f"postgresql+psycopg://{MULTI_ROLE}@{HOST}:{PORT}/{DATABASE}"


def _insert_raster(cursor, *, raster_id: UUID, product_kind: str, suffix: str) -> None:
    cursor.execute(
        """
        INSERT INTO dbi.dbi_raster_products
            (id, tenant_ref, farm_id, plot_id, source_kind, source_ref,
             source_sha256, product_kind, profile_version, generator_version,
             object_key, content_type, size_bytes, sha256, crs, width, height,
             band_count, dtype, transform_json, bounds_json, nodata_json,
             scales_json, offsets_json, block_width, block_height, compression,
             overview_levels_json, status, created_at, retired_at)
        VALUES
            (%s, %s, %s, %s, 'analysis_artifact', %s, %s, %s,
             %s, 'multi-ci-v1', %s, 'image/tiff', 4096, %s, 'EPSG:32717',
             512, 512, %s, 'uint16', %s, %s, %s, %s, %s,
             256, 256, 'deflate', '[2,4]', 'ready', CURRENT_TIMESTAMP, NULL)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            raster_id,
            TENANT,
            FARM_ID,
            PLOT_ID,
            UUID(f"81000000-0000-4000-8000-{int(suffix):012d}"),
            ("1" if product_kind == "scientific" else "2") * 64,
            product_kind,
            f"{product_kind}_ci_v1",
            f"dbi/ci/multi/{suffix}.tif",
            ("3" if product_kind == "scientific" else "4") * 64,
            4 if product_kind == "scientific" else 3,
            "[0.1,0,500000,0,-0.1,9600000]",
            "[500000,9599948.8,500051.2,9600000]",
            "[0,0,0,0]" if product_kind == "scientific" else "[0,0,0]",
            "[0.0001,0.0001,0.0001,0.0001]"
            if product_kind == "scientific"
            else "[1,1,1]",
            "[0,0,0,0]" if product_kind == "scientific" else "[0,0,0]",
        ),
    )


def _provision_role_and_fixture() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (MULTI_ROLE,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(MULTI_ROLE))
                )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DATABASE), sql.Identifier(MULTI_ROLE)
                )
            )
            for schema_name in ("dbi", "public"):
                cursor.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(schema_name), sql.Identifier(MULTI_ROLE)
                    )
                )
            for table_name in (
                "dbi_farms",
                "dbi_plots",
                "dbi_field_observations",
                "dbi_field_observation_versions",
                "dbi_raster_products",
                "dbi_multispectral_extractions",
            ):
                cursor.execute(
                    sql.SQL("GRANT SELECT ON dbi.{} TO {}").format(
                        sql.Identifier(table_name), sql.Identifier(MULTI_ROLE)
                    )
                )
            cursor.execute(
                sql.SQL("GRANT INSERT ON dbi.dbi_multispectral_extractions TO {}").format(
                    sql.Identifier(MULTI_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(MULTI_ROLE)
                )
            )

            cursor.execute(
                """
                INSERT INTO dbi.dbi_farms
                    (id, organization_ref, code, name, status, created_at, updated_at)
                VALUES (%s, %s, 'CI-MULTI-FARM', 'Finca MULTI CI', 'active',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    organization_ref = EXCLUDED.organization_ref,
                    status = 'active',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (FARM_ID, ORGANIZATION),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_plots
                    (id, farm_id, code, name, area_hectares, boundary, status,
                     created_at, updated_at)
                VALUES (%s, %s, 'CI-MULTI-PLOT', 'Lote MULTI CI', 50.0,
                        ST_GeomFromText(%s, 4326), 'active',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    boundary = EXCLUDED.boundary,
                    status = 'active',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (PLOT_ID, FARM_ID, BOUNDARY_WKT),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_field_observations
                    (id, tenant_ref, organization_ref, farm_id, plot_id,
                     created_by_ref, created_at)
                VALUES (%s, %s, %s, %s, %s, 'multi-ci-recorder', CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO NOTHING
                """,
                (OBSERVATION_ID, TENANT, ORGANIZATION, FARM_ID, PLOT_ID),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_field_observation_versions
                    (id, observation_id, version, supersedes_version_id,
                     schema_version, payload_json, payload_sha256, operator_ref,
                     observed_at, gps_point, gps_accuracy_m, gps_captured_at,
                     sampling_point_id, up_id, evidence_kind, correction_reason,
                     recorded_by_ref, created_at)
                VALUES (%s, %s, 1, NULL, 'dbi-field-observation.v1', '{}', %s,
                        'multi-ci-operator', CURRENT_TIMESTAMP, NULL, NULL, NULL,
                        NULL, NULL, 'observed', NULL, 'multi-ci-recorder',
                        CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO NOTHING
                """,
                (OBSERVATION_VERSION_ID, OBSERVATION_ID, EMPTY_PAYLOAD_SHA256),
            )
            _insert_raster(
                cursor,
                raster_id=SCIENTIFIC_RASTER_ID,
                product_kind="scientific",
                suffix="80",
            )
            _insert_raster(
                cursor,
                raster_id=RGB_RASTER_ID,
                product_kind="rgb_visual",
                suffix="81",
            )


def _summaries(*, selected_count: int = 4) -> tuple[DBISpectralVariableSummary, ...]:
    summaries: list[DBISpectralVariableSummary] = []
    for index, band in enumerate(("green", "red", "red_edge", "nir"), start=1):
        summaries.append(
            DBISpectralVariableSummary(
                variable_kind="band",
                variable_ref=band,
                selected_count=selected_count,
                valid_count=selected_count,
                valid_fraction=1.0,
                mean=0.2 + index / 100,
                median=0.2 + index / 100,
                p10=0.1 + index / 100,
                p90=0.3 + index / 100,
                source_ref=UUID(f"82000000-0000-4000-8000-{index:012d}"),
                source_sha256=f"{index + 4:064x}",
            )
        )
    for index_ref, (formula_version, formula) in _INDEX_FORMULAS.items():
        summaries.append(
            DBISpectralVariableSummary(
                variable_kind="index",
                variable_ref=index_ref,
                selected_count=selected_count,
                valid_count=selected_count,
                valid_fraction=1.0,
                mean=0.5,
                median=0.5,
                p10=0.4,
                p90=0.6,
                formula_version=formula_version,
                formula=formula,
            )
        )
    return tuple(summaries)


def _candidate(
    *,
    tenant_ref: str = TENANT,
    source_raster_product_id: UUID = SCIENTIFIC_RASTER_ID,
    up_id: UUID | None = None,
    limitation: str = "Ventana versionada porque COPA_UP no está disponible.",
    selected_count: int = 4,
) -> DBIMultispectralExtractionCandidate:
    return DBIMultispectralExtractionCandidate(
        tenant_ref=tenant_ref,
        organization_ref=ORGANIZATION,
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        observation_version_id=OBSERVATION_VERSION_ID,
        source_raster_product_id=source_raster_product_id,
        sampling_point_id=None,
        up_id=up_id,
        support_mode="window",
        support_profile_version="window_5m_v1",
        support_limitation=limitation,
        stack_fingerprint=STACK_FINGERPRINT,
        selected_count=selected_count,
        summaries=_summaries(selected_count=selected_count),
    )


def _expect_conflict(callback) -> None:
    try:
        callback()
    except DBIMultispectralPersistenceConflict:
        return
    raise AssertionError("Se esperaba DBIMultispectralPersistenceConflict.")


def _validate_repository() -> UUID:
    engine = create_engine(_url(), poolclass=NullPool, future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    candidate = _candidate()
    expected_id = multispectral_extraction_id(candidate)
    try:
        with factory() as session:
            repository = DBIMultispectralExtractionRepository(session)
            row, inserted = repository.persist(candidate)
            assert inserted
            assert row.id == expected_id
            assert row.evidence_kind == "derived"
            assert row.observation_id == OBSERVATION_ID
            assert row.observation_version_id == OBSERVATION_VERSION_ID
            assert row.source_raster_product_id == SCIENTIFIC_RASTER_ID
            assert row.sampling_point_id is None
            assert row.up_id is None
            session.commit()

        with factory() as session:
            repository = DBIMultispectralExtractionRepository(session)
            replay, inserted = repository.persist(candidate)
            assert not inserted
            assert replay.id == expected_id
            assert repository.get_scoped(
                extraction_id=expected_id,
                tenant_ref=TENANT,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            ) is not None
            assert repository.get_scoped(
                extraction_id=expected_id,
                tenant_ref="tenant-crossed",
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            ) is None

            _expect_conflict(lambda: repository.persist(_candidate(tenant_ref="tenant-crossed")))
            _expect_conflict(
                lambda: repository.persist(
                    _candidate(up_id=UUID("92000000-0000-4000-8000-000000000080"))
                )
            )
            _expect_conflict(
                lambda: repository.persist(
                    _candidate(source_raster_product_id=RGB_RASTER_ID)
                )
            )
            _expect_conflict(
                lambda: repository.persist(
                    _candidate(limitation="Payload divergente bajo la misma identidad.")
                )
            )

            count = len(
                session.execute(select(DBIMultispectralExtractionRecord)).scalars().all()
            )
            assert count == 1
            session.rollback()
    finally:
        engine.dispose()
    return expected_id


def _validate_append_only(extraction_id: UUID) -> None:
    connection = psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=MULTI_ROLE,
        autocommit=False,
        connect_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    "UPDATE dbi_multispectral_extractions "
                    "SET support_limitation = %s WHERE id = %s",
                    ("tampered", extraction_id),
                )
            except psycopg.errors.InsufficientPrivilege:
                connection.rollback()
            else:
                raise AssertionError(
                    "El rol MULTI no debe poder sobrescribir evidencia derivada."
                )
    finally:
        connection.close()


def main() -> None:
    _require_scope()
    _provision_role_and_fixture()
    extraction_id = _validate_repository()
    _validate_append_only(extraction_id)
    print(
        "DBI-MULTI-001 persistencia aprobada: exact INSPECT + scientific Raster, "
        "idempotencia, scope tenant, replay divergente rechazado y UPDATE denegado."
    )


if __name__ == "__main__":
    main()
