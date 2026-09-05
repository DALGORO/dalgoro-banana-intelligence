"""Integración PostgreSQL/PostGIS de persistencia DBI-INSPECT-001."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.inspection import (  # noqa: E402
    DBICoreObservation,
    DBIFieldObservationCorrection,
    DBIFieldObservationCreate,
    DBIFieldObservationPayload,
    DBIFieldObservationRepository,
    DBIFoureObservation,
    DBIGPSFix,
    DBIInspectionConflict,
    DBILeafCountObservation,
    DBIObservedBool,
    DBIObservedText,
    DBIPhotoEvidence,
)
from app.dbi.models.inspection import DBIFieldObservationVersionRecord  # noqa: E402

HOST = "127.0.0.1"
PORT = 5432
DATABASE = "dbi_test"
ADMIN_ROLE = "postgres"
INSPECTION_ROLE = "dbi_test_inspection"
TENANT = "tenant-inspect-ci"
ORGANIZATION = "organization-inspect-ci"
FARM_ID = UUID("10000000-0000-4000-8000-000000000079")
PLOT_ID = UUID("20000000-0000-4000-8000-000000000079")
OBSERVATION_ID = UUID("60000000-0000-4000-8000-000000000079")
VERSION_1 = UUID("70000000-0000-4000-8000-000000000079")
VERSION_2 = UUID("70000000-0000-4000-8000-000000000080")
UP_ID = UUID("40000000-0000-4000-8000-000000000079")
NOW = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
BOUNDARY_WKT = (
    "MULTIPOLYGON((("
    "-79.9350 -3.2800,"
    "-79.9150 -3.2800,"
    "-79.9150 -3.2600,"
    "-79.9350 -3.2600,"
    "-79.9350 -3.2800"
    ")))"
)


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración INSPECT sólo corre en GitHub Actions.")
    if os.environ.get("DBI_INSPECTION_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta habilitar DBI_INSPECTION_RUN_INTEGRATION.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración INSPECT exige DBI_ENVIRONMENT=test.")
    url = os.environ.get("DBI_DATABASE_URL", "")
    if INSPECTION_ROLE not in url or HOST not in url or DATABASE not in url:
        raise RuntimeError("DBI_DATABASE_URL no apunta al rol INSPECT autorizado.")


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
    return f"postgresql+psycopg://{INSPECTION_ROLE}@{HOST}:{PORT}/{DATABASE}"


def _provision_role_and_fixture() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (INSPECTION_ROLE,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(INSPECTION_ROLE))
                )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DATABASE), sql.Identifier(INSPECTION_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(INSPECTION_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    sql.Identifier(INSPECTION_ROLE)
                )
            )
            for table_name in (
                "dbi_farms",
                "dbi_plots",
                "dbi_sampling_plans",
                "dbi_sampling_points",
                "dbi_field_observations",
                "dbi_field_observation_versions",
            ):
                cursor.execute(
                    sql.SQL("GRANT SELECT ON dbi.{} TO {}").format(
                        sql.Identifier(table_name), sql.Identifier(INSPECTION_ROLE)
                    )
                )
            for table_name in (
                "dbi_field_observations",
                "dbi_field_observation_versions",
            ):
                cursor.execute(
                    sql.SQL("GRANT INSERT ON dbi.{} TO {}").format(
                        sql.Identifier(table_name), sql.Identifier(INSPECTION_ROLE)
                    )
                )
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE (created_at) ON dbi.dbi_field_observations TO {}"
                ).format(sql.Identifier(INSPECTION_ROLE))
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(INSPECTION_ROLE)
                )
            )

            cursor.execute(
                """
                INSERT INTO dbi.dbi_farms
                    (id, organization_ref, code, name, status, created_at, updated_at)
                VALUES (%s, %s, 'CI-INSPECT-FARM', 'Finca INSPECT CI', 'active',
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
                VALUES (%s, %s, 'CI-INSPECT-PLOT', 'Lote INSPECT CI', 50.0,
                        ST_GeomFromText(%s, 4326), 'active',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    boundary = EXCLUDED.boundary,
                    status = 'active',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (PLOT_ID, FARM_ID, BOUNDARY_WKT),
            )


def _text(value: str) -> DBIObservedText:
    return DBIObservedText(state="observed", value=value)


def _payload(*, tenant_ref: str = TENANT, up_id: UUID | None = None, foure: int = 3):
    return DBIFieldObservationPayload(
        tenant_ref=tenant_ref,
        organization_ref=ORGANIZATION,
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        operator_ref="operator-inspect-ci",
        observed_at=NOW,
        gps_fix=DBIGPSFix(
            longitude=-79.9252919,
            latitude=-3.2716971,
            accuracy_m=4.2,
            captured_at=NOW,
        ),
        sampling_point_id=None,
        up_id=up_id,
        core=DBICoreObservation(
            foure=DBIFoureObservation(state="observed", value=foure),
            yls=DBILeafCountObservation(state="observed", value=5),
            functional_leaves=DBILeafCountObservation(state="observed", value=8),
            mother_condition=_text("vigorous"),
            successor_condition=_text("present"),
            bunch_present=DBIObservedBool(state="observed", value=True),
            visible_affection=_text("black_sigatoka_suspected"),
            severity=_text("moderate"),
            observer_confidence=_text("high"),
            general_photo=DBIPhotoEvidence(
                state="not_measured", reason="private_asset_upload_pending"
            ),
            lesion_photo=DBIPhotoEvidence(
                state="not_measured", reason="private_asset_upload_pending"
            ),
            note="Primera visita; UP pendiente de asociación.",
        ),
        structural=None,
        diagnostic=None,
    )


def _validate_repository() -> None:
    engine = create_engine(_url(), poolclass=NullPool, future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        with factory() as session:
            repository = DBIFieldObservationRepository(session)
            first = repository.create_observation(
                DBIFieldObservationCreate(payload=_payload()),
                recorded_by_ref="recorder-inspect-ci",
                observation_id=OBSERVATION_ID,
                version_id=VERSION_1,
            )
            assert first.version == 1
            assert first.payload.up_id is None
            assert first.payload.core.foure.value == 3
            session.commit()

        with factory() as session:
            repository = DBIFieldObservationRepository(session)
            second = repository.correct_observation(
                DBIFieldObservationCorrection(
                    base_version_id=VERSION_1,
                    correction_reason=(
                        "Asociación posterior a UP y corrección Fouré confirmada en campo."
                    ),
                    payload=_payload(up_id=UP_ID, foure=2),
                ),
                recorded_by_ref="reviewer-inspect-ci",
                version_id=VERSION_2,
            )
            assert second.version == 2
            assert second.supersedes_version_id == VERSION_1
            assert second.payload.up_id == UP_ID
            assert second.payload.core.foure.value == 2
            session.commit()

        with factory() as session:
            repository = DBIFieldObservationRepository(session)
            versions = repository.list_versions(
                observation_id=OBSERVATION_ID,
                tenant_ref=TENANT,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            )
            assert len(versions) == 2
            assert versions[0].version_id == VERSION_1
            assert versions[0].payload.up_id is None
            assert versions[0].payload.core.foure.value == 3
            assert versions[1].version_id == VERSION_2
            assert versions[1].payload.up_id == UP_ID
            assert versions[1].payload.core.foure.value == 2
            assert repository.get_latest(
                observation_id=OBSERVATION_ID,
                tenant_ref="tenant-crossed",
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
            ) is None

            try:
                repository.correct_observation(
                    DBIFieldObservationCorrection(
                        base_version_id=VERSION_1,
                        correction_reason="Intento de fork obsoleto.",
                        payload=_payload(foure=1),
                    ),
                    recorded_by_ref="reviewer-inspect-ci",
                )
            except DBIInspectionConflict:
                pass
            else:
                raise AssertionError("Una corrección desde versión obsoleta debía fallar.")

            try:
                repository.correct_observation(
                    DBIFieldObservationCorrection(
                        base_version_id=VERSION_2,
                        correction_reason="Intento cruzado de tenant.",
                        payload=_payload(tenant_ref="tenant-crossed", up_id=UP_ID, foure=2),
                    ),
                    recorded_by_ref="reviewer-inspect-ci",
                )
            except DBIInspectionConflict:
                pass
            else:
                raise AssertionError("Una corrección cross-tenant debía fallar.")

            count = len(
                session.execute(
                    select(DBIFieldObservationVersionRecord).where(
                        DBIFieldObservationVersionRecord.observation_id == OBSERVATION_ID
                    )
                ).scalars().all()
            )
            assert count == 2
    finally:
        engine.dispose()


def _validate_raw_versions_are_not_updateable() -> None:
    connection = psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=INSPECTION_ROLE,
        autocommit=False,
        connect_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    "UPDATE dbi_field_observation_versions SET operator_ref = %s WHERE id = %s",
                    ("tampered", VERSION_1),
                )
            except psycopg.errors.InsufficientPrivilege:
                connection.rollback()
            else:
                raise AssertionError("El rol INSPECT no debe poder sobrescribir versiones crudas.")
    finally:
        connection.close()


def main() -> None:
    _require_scope()
    _provision_role_and_fixture()
    _validate_repository()
    _validate_raw_versions_are_not_updateable()
    print(
        "DBI-INSPECT-001 persistencia aprobada: append-only, versión, tenant y asociación UP posterior."
    )


if __name__ == "__main__":
    main()
