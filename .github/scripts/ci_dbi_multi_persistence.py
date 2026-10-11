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
from app.dbi.models.inspection import DBIFieldObservationVersionRecord  # noqa: E402
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
CAMPAIGN_ID = UUID("a0000000-0000-4000-8000-000000000080")
JOB_ID = UUID("b0000000-0000-4000-8000-000000000080")
ATTEMPT_ID = UUID("c0000000-0000-4000-8000-000000000080")
ARTIFACT_ID = UUID("81000000-0000-4000-8000-000000000080")
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
                "dbi_campaigns",
                "dbi_analysis_jobs",
                "dbi_analysis_job_attempts",
                "dbi_analysis_artifacts",
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
            # Cadena explícita única raster→artefacto→attempt→job→Campaign.
            # Datos 100% sintéticos en DB PostGIS efímera GitHub.
            cursor.execute(
                """
                INSERT INTO dbi.dbi_campaigns (
                    id, tenant_ref, organization_ref, farm_id, plot_id, code, name,
                    analysis_type, captured_at, starts_at, status, source_job_id
                ) VALUES (%s,%s,%s,%s,%s,'CI-MULTI-FLIGHT','Vuelo ficticio MULTI',
                          'multispectral', TIMESTAMPTZ '2026-09-14 09:00:00+00',
                          TIMESTAMPTZ '2026-09-14 09:00:00+00', 'ANALYZED', %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (CAMPAIGN_ID, TENANT, ORGANIZATION, FARM_ID, PLOT_ID, JOB_ID),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_analysis_jobs (
                    id, tenant_ref, request_id, correlation_id, farm_id, plot_id,
                    campaign_id, orthophoto_asset_ref, boundary_asset_ref,
                    model_version_ref, pipeline_config_version, requested_by_ref,
                    command_sha256, status
                ) VALUES (%s,%s,'ci-multi-flight','ci-multi-flight',%s,%s,%s,
                          'synthetic-photo','synthetic-boundary','ci-model',
                          'ci-pipeline','ci-operator',%s,'succeeded')
                ON CONFLICT (id) DO NOTHING
                """,
                (JOB_ID, TENANT, FARM_ID, PLOT_ID, CAMPAIGN_ID, "b" * 64),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_analysis_job_attempts
                    (id, job_id, attempt_number, status)
                VALUES (%s,%s,1,'succeeded')
                ON CONFLICT (id) DO NOTHING
                """,
                (ATTEMPT_ID, JOB_ID),
            )
            cursor.execute(
                """
                INSERT INTO dbi.dbi_analysis_artifacts (
                    id, job_id, attempt_id, role, object_key, content_type,
                    size_bytes, sha256, produced_by_stage
                ) VALUES (%s,%s,%s,'cartographic_package',
                          'dbi/ci/multi/campaign-source.tif','image/tiff',
                          4096,%s,'generate_cartographic_package')
                ON CONFLICT (id) DO NOTHING
                """,
                (ARTIFACT_ID, JOB_ID, ATTEMPT_ID, "1" * 64),
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
                organization_ref=ORGANIZATION,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            ) is not None
            assert repository.get_scoped(
                extraction_id=expected_id,
                tenant_ref="tenant-crossed",
                organization_ref=ORGANIZATION,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            ) is None
            assert repository.get_scoped(
                extraction_id=expected_id,
                tenant_ref=TENANT,
                organization_ref="organization-foreign",
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            ) is None

            assert [item.id for item in repository.list_scoped(
                tenant_ref=TENANT, organization_ref=ORGANIZATION,
                farm_id=FARM_ID, plot_id=PLOT_ID,
            )] == [expected_id]
            assert repository.list_scoped(
                tenant_ref="tenant-crossed", organization_ref=ORGANIZATION,
                farm_id=FARM_ID, plot_id=PLOT_ID,
            ) == []
            assert repository.list_scoped(
                tenant_ref=TENANT, organization_ref="organization-foreign",
                farm_id=FARM_ID, plot_id=PLOT_ID,
            ) == []
            observed = repository.observed_at_by_extraction_scoped(
                extraction_ids=[expected_id],
                tenant_ref=TENANT, organization_ref=ORGANIZATION,
                farm_id=FARM_ID, plot_id=PLOT_ID,
            )
            assert set(observed) == {expected_id}
            observed_at = session.execute(
                select(DBIFieldObservationVersionRecord.observed_at).where(
                    DBIFieldObservationVersionRecord.id == OBSERVATION_VERSION_ID,
                )
            ).scalar_one()
            assert observed[expected_id] == observed_at
            assert observed[expected_id].tzinfo is not None
            linked = repository.campaign_provenance_by_extraction_scoped(
                extraction_ids=[expected_id],
                tenant_ref=TENANT, organization_ref=ORGANIZATION,
                farm_id=FARM_ID, plot_id=PLOT_ID,
            )
            assert set(linked) == {expected_id}
            assert linked[expected_id][0] == CAMPAIGN_ID
            assert linked[expected_id][1].isoformat().startswith("2026-09-14T09:00:00")
            assert linked[expected_id][1].tzinfo is not None
            assert repository.campaign_provenance_by_extraction_scoped(
                extraction_ids=[], tenant_ref=TENANT,
                organization_ref=ORGANIZATION, farm_id=FARM_ID, plot_id=PLOT_ID,
            ) == {}
            for scope in (
                {"tenant_ref": "tenant-crossed", "organization_ref": ORGANIZATION,
                 "farm_id": FARM_ID, "plot_id": PLOT_ID},
                {"tenant_ref": TENANT, "organization_ref": "organization-foreign",
                 "farm_id": FARM_ID, "plot_id": PLOT_ID},
                {"tenant_ref": TENANT, "organization_ref": ORGANIZATION,
                 "farm_id": FARM_ID, "plot_id": UUID("20000000-0000-4000-8000-000000000081")},
                {"tenant_ref": TENANT, "organization_ref": ORGANIZATION,
                 "farm_id": UUID("10000000-0000-4000-8000-000000000081"),
                 "plot_id": PLOT_ID},
            ):
                assert repository.campaign_provenance_by_extraction_scoped(
                    extraction_ids=[expected_id], **scope,
                ) == {}
            _expect_conflict(lambda: repository.campaign_provenance_by_extraction_scoped(
                extraction_ids=[expected_id] * 21,
                tenant_ref=TENANT, organization_ref=ORGANIZATION,
                farm_id=FARM_ID, plot_id=PLOT_ID,
            ))
            assert repository.observed_at_by_extraction_scoped(
                extraction_ids=[], tenant_ref=TENANT,
                organization_ref=ORGANIZATION, farm_id=FARM_ID, plot_id=PLOT_ID,
            ) == {}
            for scope in (
                {"tenant_ref": "tenant-crossed", "organization_ref": ORGANIZATION,
                 "farm_id": FARM_ID, "plot_id": PLOT_ID},
                {"tenant_ref": TENANT, "organization_ref": "organization-foreign",
                 "farm_id": FARM_ID, "plot_id": PLOT_ID},
                {"tenant_ref": TENANT, "organization_ref": ORGANIZATION,
                 "farm_id": FARM_ID, "plot_id": UUID("20000000-0000-4000-8000-000000000081")},
                {"tenant_ref": TENANT, "organization_ref": ORGANIZATION,
                 "farm_id": UUID("10000000-0000-4000-8000-000000000081"), "plot_id": PLOT_ID},
            ):
                assert repository.observed_at_by_extraction_scoped(
                    extraction_ids=[expected_id], **scope,
                ) == {}
            try:
                repository.observed_at_by_extraction_scoped(
                    extraction_ids=[expected_id] * 21, tenant_ref=TENANT,
                    organization_ref=ORGANIZATION, farm_id=FARM_ID, plot_id=PLOT_ID,
                )
            except DBIMultispectralPersistenceConflict:
                pass
            else:
                raise AssertionError("El lote temporal debe limitar IDs a 20 distintos.")
            assert repository.list_scoped(
                tenant_ref=TENANT, organization_ref=ORGANIZATION,
                farm_id=FARM_ID, plot_id=UUID("20000000-0000-4000-8000-000000000081"),
            ) == []
            assert repository.list_scoped(
                tenant_ref=TENANT, organization_ref=ORGANIZATION,
                farm_id=UUID("10000000-0000-4000-8000-000000000081"),
                plot_id=PLOT_ID,
            ) == []

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


def _validate_campaign_chain_fail_closed(extraction_id: UUID) -> None:
    """Cualquier desacuerdo de la cadena produce vínculo desconocido, no otra campaña."""
    drift_cases = (
        ("dbi_campaigns", "source_job_id", CAMPAIGN_ID, None, JOB_ID),
        ("dbi_campaigns", "organization_ref", CAMPAIGN_ID,
         "organization-foreign", ORGANIZATION),
        ("dbi_analysis_jobs", "status", JOB_ID, "failed", "succeeded"),
        ("dbi_raster_products", "source_sha256", SCIENTIFIC_RASTER_ID,
         "e" * 64, "1" * 64),
    )
    engine = create_engine(_url(), poolclass=NullPool, future=True)
    try:
        with _admin_connect() as admin:
            with admin.cursor() as cursor:
                for table, field, key, tampered, original in drift_cases:
                    # Tabla/columna proceden de constantes internas, no de usuario.
                    statement = sql.SQL("UPDATE dbi.{} SET {} = %s WHERE id = %s").format(
                        sql.Identifier(table), sql.Identifier(field),
                    )
                    cursor.execute(statement, (tampered, key))
                    try:
                        with sessionmaker(bind=engine, future=True)() as session:
                            result = DBIMultispectralExtractionRepository(
                                session
                            ).campaign_provenance_by_extraction_scoped(
                                extraction_ids=[extraction_id],
                                tenant_ref=TENANT, organization_ref=ORGANIZATION,
                                farm_id=FARM_ID, plot_id=PLOT_ID,
                            )
                            assert result == {}, (table, field)
                    finally:
                        cursor.execute(statement, (original, key))
    finally:
        engine.dispose()


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
    _validate_campaign_chain_fail_closed(extraction_id)
    print(
        "DBI-MULTI-001 persistencia y Campaign auténtica: INSPECT + Raster + job, "
        "idempotencia, scope tenant, replay divergente rechazado y UPDATE denegado."
    )


if __name__ == "__main__":
    main()
