"""Prueba PostGIS de fotos privadas INSPECT con acceso SELECT-only a Asset."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
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

from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.inspection import (  # noqa: E402
    DBICoreObservation,
    DBIFoureObservation,
    DBILeafCountObservation,
    DBIObservedBool,
    DBIObservedText,
    DBIPhotoEvidence,
)
from app.dbi.inspection.api_schemas import (  # noqa: E402
    DBIFieldObservationBody,
    DBIFieldObservationCreateRequest,
)
from app.dbi.inspection.service import DBIFieldObservationService  # noqa: E402
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
FIELD_PHOTO_ID = UUID("30000000-0000-4000-8000-000000000079")
NOW = datetime(2026, 9, 5, 18, 30, tzinfo=timezone.utc)


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración de foto INSPECT sólo corre en GitHub Actions.")
    if os.environ.get("DBI_INSPECTION_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta habilitar DBI_INSPECTION_RUN_INTEGRATION.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración de foto INSPECT exige DBI_ENVIRONMENT=test.")
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


def _provision_select_only_asset_fixture() -> None:
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (INSPECTION_ROLE,))
            if cursor.fetchone() is None:
                raise RuntimeError("El rol INSPECT base debe existir antes de probar fotos.")

            cursor.execute(
                "SELECT 1 FROM dbi.dbi_plots WHERE id = %s AND farm_id = %s",
                (PLOT_ID, FARM_ID),
            )
            if cursor.fetchone() is None:
                raise RuntimeError("El fixture finca/lote INSPECT base no existe.")

            cursor.execute(
                sql.SQL(
                    "REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
                    "ON dbi.dbi_analysis_input_assets FROM {}"
                ).format(sql.Identifier(INSPECTION_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT ON dbi.dbi_analysis_input_assets TO {}"
                ).format(sql.Identifier(INSPECTION_ROLE))
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(INSPECTION_ROLE)
                )
            )

            cursor.execute(
                """
                INSERT INTO dbi.dbi_analysis_input_assets
                    (id, tenant_ref, farm_id, plot_id, asset_kind, status,
                     object_key, content_type, size_bytes, sha256, crs,
                     created_by_ref, verified_at, created_at, updated_at)
                VALUES
                    (%s, %s, %s, %s, 'field_photo', 'verified',
                     'field/ci/inspection/general-photo.jpg', 'image/jpeg',
                     256, %s, NULL, 'fixture-inspect-photo-ci', %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    tenant_ref = EXCLUDED.tenant_ref,
                    farm_id = EXCLUDED.farm_id,
                    plot_id = EXCLUDED.plot_id,
                    asset_kind = EXCLUDED.asset_kind,
                    status = EXCLUDED.status,
                    object_key = EXCLUDED.object_key,
                    content_type = EXCLUDED.content_type,
                    size_bytes = EXCLUDED.size_bytes,
                    sha256 = EXCLUDED.sha256,
                    crs = EXCLUDED.crs,
                    created_by_ref = EXCLUDED.created_by_ref,
                    verified_at = EXCLUDED.verified_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    FIELD_PHOTO_ID,
                    TENANT,
                    FARM_ID,
                    PLOT_ID,
                    "b" * 64,
                    NOW,
                    NOW,
                    NOW,
                ),
            )

            cursor.execute(
                "SELECT has_table_privilege(%s, 'dbi.dbi_analysis_input_assets', 'SELECT'), "
                "has_table_privilege(%s, 'dbi.dbi_analysis_input_assets', 'INSERT'), "
                "has_table_privilege(%s, 'dbi.dbi_analysis_input_assets', 'UPDATE'), "
                "has_table_privilege(%s, 'dbi.dbi_analysis_input_assets', 'DELETE')",
                (INSPECTION_ROLE, INSPECTION_ROLE, INSPECTION_ROLE, INSPECTION_ROLE),
            )
            if cursor.fetchone() != (True, False, False, False):
                raise AssertionError("El rol INSPECT no conserva Asset en modo SELECT-only.")


def _text(value: str) -> DBIObservedText:
    return DBIObservedText(state="observed", value=value)


def _context() -> DBIAccessContext:
    return DBIAccessContext(
        principal_ref="operator-inspect-photo-ci",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORGANIZATION}),
        farm_scopes=frozenset({DBIFarmScope(ORGANIZATION, FARM_ID)}),
        plot_scopes=frozenset({DBIPlotScope(ORGANIZATION, FARM_ID, PLOT_ID)}),
        permissions=frozenset({DBIPermission.READ, DBIPermission.WRITE}),
    )


def _request() -> DBIFieldObservationCreateRequest:
    core = DBICoreObservation(
        foure=DBIFoureObservation(state="observed", value=3),
        yls=DBILeafCountObservation(state="observed", value=5),
        functional_leaves=DBILeafCountObservation(state="observed", value=8),
        mother_condition=_text("vigorous"),
        successor_condition=_text("present"),
        bunch_present=DBIObservedBool(state="observed", value=True),
        visible_affection=_text("black_sigatoka_suspected"),
        severity=_text("moderate"),
        observer_confidence=_text("high"),
        general_photo=DBIPhotoEvidence(state="observed", asset_id=FIELD_PHOTO_ID),
        lesion_photo=DBIPhotoEvidence(
            state="not_applicable",
            reason="lesion_photo_not_required",
        ),
        note="Captura con evidencia fotográfica privada verificada.",
    )
    return DBIFieldObservationCreateRequest(
        observation=DBIFieldObservationBody(
            observed_at=NOW,
            core=core,
        )
    )


def _validate_service_with_select_only_asset() -> None:
    engine = create_engine(_url(), poolclass=NullPool, future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        with factory() as session:
            result = DBIFieldObservationService(session).create(
                _context(),
                organization_ref=ORGANIZATION,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                request=_request(),
            )
            assert result.payload.core.general_photo.asset_id == FIELD_PHOTO_ID
            observation_id = result.observation_id
            session.commit()

        with factory() as session:
            row = session.execute(
                select(DBIFieldObservationVersionRecord).where(
                    DBIFieldObservationVersionRecord.observation_id == observation_id
                )
            ).scalar_one()
            persisted = json.loads(row.payload_json)
            assert persisted["core"]["general_photo"]["asset_id"] == str(FIELD_PHOTO_ID)
            serialized = json.dumps(persisted, sort_keys=True).lower()
            for forbidden in ("object_key", "signed_url", "presigned", "bucket", "local_path"):
                assert forbidden not in serialized
    finally:
        engine.dispose()


def _validate_asset_write_is_denied() -> None:
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
            cursor.execute(
                "SELECT status, asset_kind, content_type FROM dbi_analysis_input_assets WHERE id = %s",
                (FIELD_PHOTO_ID,),
            )
            assert cursor.fetchone() == ("verified", "field_photo", "image/jpeg")
            try:
                cursor.execute(
                    "UPDATE dbi_analysis_input_assets SET status = 'registered' WHERE id = %s",
                    (FIELD_PHOTO_ID,),
                )
            except psycopg.errors.InsufficientPrivilege:
                connection.rollback()
            else:
                raise AssertionError("El rol INSPECT no debe poder modificar el Asset fotográfico.")
    finally:
        connection.close()


def main() -> None:
    _require_scope()
    _provision_select_only_asset_fixture()
    _validate_service_with_select_only_asset()
    _validate_asset_write_is_denied()
    print(
        "DBI-INSPECT-001 foto aprobada: field_photo privada, mismo alcance y Asset SELECT-only."
    )


if __name__ == "__main__":
    main()
