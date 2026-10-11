"""Consulta controlada y EXCLUSIVAMENTE de solo lectura de revisiones DBI staging.

Entrada separada del migrador: no importa apply, Alembic upgrade ni FastAPI.
No crea ni autoriza una vía para aplicar cambios en staging/producción.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.db.dbi_config import (
    DBIDatabaseConfigurationError, load_dbi_database_config,
)
from app.dbi.migration_cli import _migration_graph
from app.dbi.migration_control import DBIMigrationControlError, DBIMigrationTarget
from app.dbi.migration_preflight import run_migration_preflight

AUDITOR_ROLE = "dbi_staging_migration_auditor"
CONFIRMATION = "VERIFY dbi_staging READ ONLY"
REQUIRED_GIS_REVISION = "dbi_0026_gpkg_layer_choice"
DNS_HOST_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")


def _safe_output(**values: object) -> None:
    print(json.dumps(values, sort_keys=True, ensure_ascii=False))


def _validate_target(values: Mapping[str, str]) -> tuple[object, DBIMigrationTarget]:
    """Todo guard se aplica ANTES de crear un motor o abrir sockets."""
    if values.get("GITHUB_ACTIONS", "").lower() == "true" or values.get("CI", "").lower() == "true":
        raise DBIMigrationControlError("La verificación staging conectada está bloqueada en CI.")
    if values.get("DBI_ENVIRONMENT", "").strip() != "staging":
        raise DBIMigrationControlError("La verificación remota solo admite staging.")
    if values.get("DBI_STAGING_VERIFY_CONFIRM") != CONFIRMATION:
        raise DBIMigrationControlError("Falta la confirmación explícita de lectura staging.")
    config = load_dbi_database_config(values)
    if config.url.username != AUDITOR_ROLE:
        raise DBIMigrationControlError("Se exige el rol auditor de staging, no el migrador.")
    expected = values.get("DBI_STAGING_VERIFY_HOST", "").strip().lower()
    hostname = (config.url.host or "").lower()
    if (
        len(expected) < 4 or expected != hostname
        or DNS_HOST_PATTERN.fullmatch(expected) is None
        or "." not in expected
        or expected.endswith((".localhost", ".local", ".invalid"))
    ):
        raise DBIMigrationControlError("Host staging no coincide con el DNS autorizado.")
    try:
        ipaddress.ip_address(expected)
    except ValueError:
        pass
    else:
        raise DBIMigrationControlError("No se permiten IP literales como host staging.")
    if config.url.query.get("sslmode") != "verify-full":
        raise DBIMigrationControlError("Se exige TLS sslmode=verify-full en staging.")
    if config.url.port not in {None, 5432}:
        raise DBIMigrationControlError("Puerto de PostgreSQL staging no autorizado.")
    target = DBIMigrationTarget(
        environment="staging", database_name="dbi_staging",
        username=AUDITOR_ROLE, expected_migrator_role=AUDITOR_ROLE,
    )
    return config, target


def verify_staging(values: Mapping[str, str]) -> dict:
    """Verifica revisión y privilegios en transacción READ ONLY sin hacer apply."""
    config, target = _validate_target(values)
    known, head = _migration_graph()
    if REQUIRED_GIS_REVISION not in known:
        raise DBIMigrationControlError("La migración GIS DBI 26 falta en el código.")
    engine = create_engine(
        config.url, poolclass=NullPool,
        connect_args={
            "connect_timeout": 5,
            "options": (
                "-c default_transaction_read_only=on "
                "-c statement_timeout=8000 -c lock_timeout=2000"
            ),
        },
    )
    try:
        with engine.connect() as connection:
            # Se establece explícitamente antes del primer SELECT del preflight.
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            evidence = run_migration_preflight(
                connection, target=target, known_revisions=known, head_revision=head,
            )
            connection.rollback()
    finally:
        engine.dispose()
    return {
        "operation": "verify-staging-readonly",
        "environment": "staging",
        "database": "dbi_staging",
        "role": AUDITOR_ROLE,
        "code_head_revision": head,
        "database_revision": evidence.current_revision,
        "is_at_head": evidence.is_at_head,
        "postgis_available": evidence.postgis_available,
        "dbi_schema_available": evidence.dbi_schema_available,
        "migration_apply": "BLOCKED",
        "deployment_readiness": "NOT_VERIFIED",
    }


def main(argv: Sequence[str] | None = None, *, values: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dbi-staging-migration-verify",
        description="Consulta staging solo READ ONLY, nunca aplica migraciones.",
    )
    parser.add_argument("--verify-readonly", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        report = verify_staging(os.environ if values is None else values)
    except (DBIDatabaseConfigurationError, DBIMigrationControlError):
        _safe_output(operation="verify-staging-readonly", result="BLOCKED",
                     deployment_readiness="NOT_VERIFIED")
        return 2
    except (SQLAlchemyError, OSError, Exception):
        # No imprimir errores del proveedor, URL, DNS, SSL, token ni contraseñas.
        _safe_output(operation="verify-staging-readonly", result="UNAVAILABLE",
                     deployment_readiness="NOT_VERIFIED")
        return 3
    _safe_output(**report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
