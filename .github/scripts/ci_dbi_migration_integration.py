"""Prueba real de migraciones DBI contra PostgreSQL/PostGIS efímero de CI.

Este archivo es un fixture exclusivo de GitHub Actions. Aprovisiona una base
desechable local con privilegios mínimos y después usa la herramienta DBI real.
No admite hosts remotos, staging ni producción.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.dbi_base import DBIBase  # noqa: E402
from app.db.dbi_config import load_dbi_database_config  # noqa: E402
from app.dbi import models as dbi_models  # noqa: E402,F401
from app.dbi.migration_apply import apply_migrations_controlled  # noqa: E402
from app.dbi.migration_control import DBIMigrationControlError  # noqa: E402
from app.dbi.migration_lock import (  # noqa: E402
    acquire_migration_lock,
    migration_lock,
)
from app.dbi.migration_plan import generate_offline_plan  # noqa: E402
from app.dbi.migration_preflight import run_migration_preflight  # noqa: E402
from app.dbi.migration_runner import upgrade_head_on_connection  # noqa: E402

HOST = "127.0.0.1"
PORT = 5432
ADMIN_DATABASE = "postgres"
ADMIN_ROLE = "postgres"
DBI_DATABASE = "dbi_test"
DBI_OWNER_ROLE = "dbi_test_owner"
DBI_MIGRATOR_ROLE = "dbi_test_migrator"
EXPECTED_HEAD = "dbi_0013_model_registry"
LEGACY_TABLES = frozenset({"documents", "users", "companies"})
SPATIAL_CONSTRAINTS = frozenset(
    {
        "ck_dbi_plots_boundary_not_empty",
        "ck_dbi_plots_boundary_valid",
    }
)
SCOPE_HIERARCHY_CONSTRAINTS = frozenset(
    {
        "uq_dbi_farms_id_organization",
        "uq_dbi_plots_id_farm",
        "fk_dbi_membership_scopes_farm_organization",
        "fk_dbi_membership_scopes_plot_farm",
    }
)
MULTIPART_CONSTRAINTS = frozenset(
    {
        "uq_dbi_analysis_input_assets_id_tenant",
        "fk_dbi_multipart_sessions_asset_tenant",
        "uq_dbi_multipart_sessions_id_tenant",
        "uq_dbi_multipart_sessions_idempotency",
        "ck_dbi_multipart_sessions_provider_context",
        "ck_dbi_multipart_sessions_checksum_pair",
        "ck_dbi_multipart_sessions_terminal_timestamps",
        "ck_dbi_multipart_sessions_active_expiry",
        "fk_dbi_multipart_parts_session_tenant",
    }
)
MULTIPART_INDEXES = frozenset(
    {
        "ix_dbi_multipart_sessions_cleanup",
        "uq_dbi_multipart_sessions_active_asset",
    }
)
FLIGHT_MANIFEST_CONSTRAINTS = frozenset(
    {
        "ck_dbi_analysis_input_assets_kind",
        "uq_dbi_flight_source_bundles_id_tenant",
        "uq_dbi_flight_source_bundles_flight",
        "fk_dbi_flight_source_bundles_plot_farm",
        "fk_dbi_flight_source_bundles_master_tenant",
        "ck_dbi_flight_source_bundles_schema",
        "ck_dbi_flight_source_bundles_sha256",
        "fk_dbi_flight_source_entries_bundle_tenant",
        "fk_dbi_flight_source_entries_asset_tenant",
        "uq_dbi_flight_source_entries_logical_name",
        "uq_dbi_flight_source_entries_ordinal",
        "ck_dbi_flight_source_entries_role",
        "ck_dbi_flight_source_entries_sha256",
    }
)
FLIGHT_MANIFEST_INDEXES = frozenset(
    {
        "ix_dbi_flight_source_bundles_master",
        "ix_dbi_flight_source_entries_asset",
        "ix_dbi_flight_source_entries_capture",
    }
)


def _require_ci_scope() -> None:
    """Falla cerrado fuera de GitHub Actions o ante variables heredadas."""

    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError(
            "La integración DBI efímera solo puede ejecutarse en GitHub Actions."
        )
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL no está permitida en la integración DBI.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError(
            "La integración DBI efímera exige DBI_ENVIRONMENT=test."
        )
    if not os.environ.get("DBI_DATABASE_URL"):
        raise RuntimeError(
            "La integración DBI efímera exige DBI_DATABASE_URL."
        )


def _admin_connect(database: str):
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=database,
        user=ADMIN_ROLE,
        autocommit=True,
        connect_timeout=10,
    )


def _provision_ephemeral_database() -> None:
    """Crea únicamente el fixture local; la herramienta de migración no aprovisiona."""

    with _admin_connect(ADMIN_DATABASE) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                (DBI_OWNER_ROLE,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(DBI_OWNER_ROLE))
                )

            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                (DBI_MIGRATOR_ROLE,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(DBI_MIGRATOR_ROLE))
                )

            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (DBI_DATABASE,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE DATABASE {} OWNER {} TEMPLATE template0 "
                        "ENCODING 'UTF8'"
                    ).format(
                        sql.Identifier(DBI_DATABASE),
                        sql.Identifier(DBI_OWNER_ROLE),
                    )
                )

            cursor.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(DBI_DATABASE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DBI_DATABASE),
                    sql.Identifier(DBI_MIGRATOR_ROLE),
                )
            )

    with _admin_connect(DBI_DATABASE) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            cursor.execute(
                sql.SQL(
                    "CREATE SCHEMA IF NOT EXISTS dbi AUTHORIZATION {}"
                ).format(sql.Identifier(DBI_OWNER_ROLE))
            )
            cursor.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            cursor.execute("REVOKE ALL ON SCHEMA dbi FROM PUBLIC")
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    sql.Identifier(DBI_MIGRATOR_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA dbi TO {}").format(
                    sql.Identifier(DBI_MIGRATOR_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = dbi, public").format(
                    sql.Identifier(DBI_MIGRATOR_ROLE)
                )
            )


def _migration_graph() -> tuple[set[str], str]:
    alembic_config = Config(str(BACKEND / "dbi_alembic.ini"))
    scripts = ScriptDirectory.from_config(alembic_config)
    heads = scripts.get_heads()
    if heads != [EXPECTED_HEAD]:
        raise AssertionError(f"Cabeza DBI inesperada: {heads!r}")
    known_revisions = {
        revision.revision for revision in scripts.walk_revisions()
    }
    if not known_revisions or EXPECTED_HEAD not in known_revisions:
        raise AssertionError("El linaje DBI no contiene la cabeza esperada.")
    return known_revisions, EXPECTED_HEAD


def _dbi_config():
    config = load_dbi_database_config()
    identity = (
        config.environment,
        config.database_name,
        config.url.username,
        config.url.host,
        config.url.port,
    )
    expected = (
        "test",
        DBI_DATABASE,
        DBI_MIGRATOR_ROLE,
        HOST,
        PORT,
    )
    if identity != expected:
        raise RuntimeError(
            "Las variables DBI de integración no apuntan al fixture local autorizado."
        )
    return config


def _table_names(connection) -> set[str]:
    return set(
        connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'dbi'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
        ).scalars()
    )


def _validate_plan_and_preflight_are_read_only(
    connection,
    *,
    config,
    known_revisions: set[str],
    head_revision: str,
):
    before = _table_names(connection)
    plan = generate_offline_plan(config, running_in_ci=True)
    preflight = run_migration_preflight(
        connection,
        target=plan.target,
        known_revisions=known_revisions,
        head_revision=head_revision,
    )
    after = _table_names(connection)

    if before != after:
        raise AssertionError("Plan o preflight modificaron el esquema DBI.")
    if not preflight.database_is_empty:
        raise AssertionError(
            "El fixture inicial debía estar sin tabla de versión."
        )
    return plan


def _validate_real_lock(engine) -> None:
    with engine.connect() as first, engine.connect() as second:
        with migration_lock(first):
            try:
                acquire_migration_lock(second)
            except DBIMigrationControlError:
                pass
            else:
                raise AssertionError(
                    "Dos sesiones adquirieron el lock DBI simultáneamente."
                )


def _validate_postflight(connection, *, expected_head: str) -> set[str]:
    revision = connection.execute(
        text("SELECT version_num FROM dbi.alembic_version_dbi")
    ).scalar_one()
    if revision != expected_head:
        raise AssertionError(f"Revisión final DBI inesperada: {revision!r}")

    expected_tables = {
        table.name for table in DBIBase.metadata.tables.values()
    }
    actual_tables = _table_names(connection)
    required_tables = expected_tables | {"alembic_version_dbi"}
    if actual_tables != required_tables:
        missing = sorted(required_tables - actual_tables)
        unexpected = sorted(actual_tables - required_tables)
        raise AssertionError(
            "Tablas DBI divergentes. "
            f"Faltantes={missing}; inesperadas={unexpected}"
        )
    if LEGACY_TABLES & actual_tables:
        raise AssertionError(
            "Se detectaron tablas heredadas dentro del esquema DBI."
        )

    geometry = connection.execute(
        text(
            """
            SELECT type, srid
            FROM public.geometry_columns
            WHERE f_table_schema = 'dbi'
              AND f_table_name = 'dbi_plots'
              AND f_geometry_column = 'boundary'
            """
        )
    ).mappings().one()
    if geometry["type"] != "MULTIPOLYGON" or int(geometry["srid"]) != 4326:
        raise AssertionError(
            f"Contrato espacial DBI inválido: {dict(geometry)!r}"
        )

    index_definition = connection.execute(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'dbi'
              AND tablename = 'dbi_plots'
              AND indexname = 'ix_dbi_plots_boundary_gist'
            """
        )
    ).scalar_one()
    if "using gist" not in index_definition.lower():
        raise AssertionError("El índice espacial DBI no usa GiST.")

    constraints = set(
        connection.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = 'dbi'
                  AND table_name = 'dbi_plots'
                  AND constraint_type = 'CHECK'
                """
            )
        ).scalars()
    )
    if not SPATIAL_CONSTRAINTS <= constraints:
        raise AssertionError(
            "Faltan restricciones espaciales: "
            f"{sorted(SPATIAL_CONSTRAINTS - constraints)}"
        )

    hierarchy_constraints = set(
        connection.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = 'dbi'
                  AND table_name IN (
                    'dbi_farms',
                    'dbi_plots',
                    'dbi_membership_scopes'
                  )
                """
            )
        ).scalars()
    )
    if not SCOPE_HIERARCHY_CONSTRAINTS <= hierarchy_constraints:
        raise AssertionError(
            "Faltan restricciones jerárquicas DBI: "
            f"{sorted(SCOPE_HIERARCHY_CONSTRAINTS - hierarchy_constraints)}"
        )

    multipart_constraints = set(
        connection.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = 'dbi'
                  AND table_name IN (
                    'dbi_analysis_input_assets',
                    'dbi_asset_multipart_sessions',
                    'dbi_asset_multipart_parts'
                  )
                """
            )
        ).scalars()
    )
    if not MULTIPART_CONSTRAINTS <= multipart_constraints:
        raise AssertionError(
            "Faltan restricciones multipartes DBI: "
            f"{sorted(MULTIPART_CONSTRAINTS - multipart_constraints)}"
        )

    multipart_indexes = {
        row["indexname"]: row["indexdef"]
        for row in connection.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'dbi'
                  AND tablename = 'dbi_asset_multipart_sessions'
                """
            )
        ).mappings()
    }
    if not MULTIPART_INDEXES <= multipart_indexes.keys():
        raise AssertionError(
            "Faltan índices multipartes DBI: "
            f"{sorted(MULTIPART_INDEXES - multipart_indexes.keys())}"
        )
    active_index = multipart_indexes[
        "uq_dbi_multipart_sessions_active_asset"
    ].lower()
    if not all(
        marker in active_index
        for marker in ("create unique index", "where", "initiated", "uploading")
    ):
        raise AssertionError(
            "El índice único de sesión multipartes activa es inválido."
        )

    flight_manifest_constraints = set(
        connection.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = 'dbi'
                  AND table_name IN (
                    'dbi_analysis_input_assets',
                    'dbi_flight_source_bundles',
                    'dbi_flight_source_entries'
                  )
                """
            )
        ).scalars()
    )
    if not FLIGHT_MANIFEST_CONSTRAINTS <= flight_manifest_constraints:
        raise AssertionError(
            "Faltan restricciones del manifiesto de vuelo DBI: "
            f"{sorted(FLIGHT_MANIFEST_CONSTRAINTS - flight_manifest_constraints)}"
        )

    flight_manifest_indexes = set(
        connection.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'dbi'
                  AND tablename IN (
                    'dbi_flight_source_bundles',
                    'dbi_flight_source_entries'
                  )
                """
            )
        ).scalars()
    )
    if not FLIGHT_MANIFEST_INDEXES <= flight_manifest_indexes:
        raise AssertionError(
            "Faltan índices del manifiesto de vuelo DBI: "
            f"{sorted(FLIGHT_MANIFEST_INDEXES - flight_manifest_indexes)}"
        )

    asset_kind_check = connection.execute(
        text(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'ck_dbi_analysis_input_assets_kind'
            """
        )
    ).scalar_one().lower()
    for asset_kind in ('orthophoto', 'flight_photo', 'flight_auxiliary'):
        if asset_kind not in asset_kind_check:
            raise AssertionError(
                f"El tipo de activo {asset_kind!r} falta en el contrato durable."
            )

    postgis_ok = connection.execute(
        text(
            """
            SELECT ST_IsValid(
                ST_GeomFromText(
                    'MULTIPOLYGON(((0 0, 0 1, 1 1, 1 0, 0 0)))',
                    4326
                )
            )
            """
        )
    ).scalar_one()
    if postgis_ok is not True:
        raise AssertionError("Las funciones PostGIS no están operativas.")

    return actual_tables


def main() -> None:
    _require_ci_scope()
    _provision_ephemeral_database()
    known_revisions, head_revision = _migration_graph()
    config = _dbi_config()
    engine = create_engine(config.url, poolclass=NullPool)

    try:
        _validate_real_lock(engine)

        with engine.connect() as connection:
            plan = _validate_plan_and_preflight_are_read_only(
                connection,
                config=config,
                known_revisions=known_revisions,
                head_revision=head_revision,
            )

            first = apply_migrations_controlled(
                config,
                connection,
                confirmation="APPLY dbi_test",
                running_in_ci=True,
                known_revisions=known_revisions,
                head_revision=head_revision,
                upgrade_head=upgrade_head_on_connection,
            )
            if not first.applied:
                raise AssertionError(
                    "La primera ejecución debía aplicar el linaje DBI."
                )

            tables = _validate_postflight(
                connection,
                expected_head=head_revision,
            )

            second = apply_migrations_controlled(
                config,
                connection,
                confirmation="APPLY dbi_test",
                running_in_ci=True,
                known_revisions=known_revisions,
                head_revision=head_revision,
                upgrade_head=upgrade_head_on_connection,
            )
            if second.applied:
                raise AssertionError(
                    "La segunda ejecución debía ser idempotente."
                )

        evidence = {
            "database": DBI_DATABASE,
            "environment": "test",
            "head_revision": head_revision,
            "plan_sha256": plan.fingerprint,
            "first_apply": first.applied,
            "second_apply": second.applied,
            "table_count": len(tables),
        }
        print(json.dumps(evidence, sort_keys=True))
        print(
            "Migración DBI real aprobada en PostgreSQL/PostGIS efímero."
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
