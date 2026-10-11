"""E6: respaldo y restauración REAL solo en PostgreSQL/PostGIS efímero de CI.

Nunca acepta un host, base, rol o contenedor suministrado por el operador.
No aplica migraciones y no tiene ruta de ejecución contra staging/producción.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.dbi.migration_control import is_authorized_github_actions_runtime

IMAGE = (
    "postgis/postgis:16-3.5@sha256:"
    "4be58fcb1b50df187e73536e663149c2b3b2da2a541c2f518cfb6adebc65ed91"
)
HEX_CONTAINER = re.compile(r"[a-f0-9]{12,64}\Z")
_SAFE_STAGE = "initial" 


def _stage(value):
    global _SAFE_STAGE
    _SAFE_STAGE = value


class RehearsalBlocked(RuntimeError):
    """Bloqueo con error redactado, sin comandos ni credenciales."""


def check_runtime(values):
    """Rechazar ANTES de Docker o Postgres a todo destino no efímero autorizado."""
    if not is_authorized_github_actions_runtime(values):
        raise RehearsalBlocked("CI identity invalid")
    if (
        values.get("GITHUB_WORKFLOW") != "DBI migrations integration"
        or values.get("GITHUB_JOB") != "dbi-postgis-integration"
        or values.get("DBI_E6_EPHEMERAL_RESTORE") != "1"
        or values.get("DBI_ENVIRONMENT") != "test"
    ):
        raise RehearsalBlocked("CI test environment required")
    try:
        url = make_url(values.get("DBI_DATABASE_URL", ""))
    except (TypeError, ValueError):
        raise RehearsalBlocked("DBI URL invalid") from None
    if (
        url.drivername != "postgresql+psycopg"
        or url.database != "dbi_test"
        or url.username != "dbi_test_migrator"
        or url.host != "127.0.0.1"
        or url.port != 5432
        or url.password is not None
        or url.query
    ):
        raise RehearsalBlocked("CI database mismatch")


def _docker(*args, timeout=35, expect_failure=False):
    result = subprocess.run(
        ["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout, check=False,
    )
    if (result.returncode == 0) == expect_failure:
        raise RehearsalBlocked("ephemeral docker command result invalid")
    return result.stdout


def _container():
    ids = _docker("ps", "--filter", "publish=5432", "--format", "{{.ID}}")
    container_ids = ids.decode("ascii", errors="replace").splitlines()
    if len(container_ids) != 1 or HEX_CONTAINER.fullmatch(container_ids[0]) is None:
        raise RehearsalBlocked("exactly one ephemeral postgis container required")
    cid = container_ids[0]
    image = _docker("inspect", "--format", "{{.Config.Image}}", cid).decode().strip()
    if image != IMAGE:
        raise RehearsalBlocked("untrusted docker image")
    return cid


def _sql_conn(db):
    # String literal local-only: never propagated from secrets or user input.
    return psycopg.connect(
        host="127.0.0.1", port=5432, user="postgres", dbname=db,
        connect_timeout=5, options="-c statement_timeout=12000 -c lock_timeout=2000",
    )


def _db_action(admin, statement, name):
    admin.execute(sql.SQL(statement).format(sql.Identifier(name)))


def _fixture_fingerprint(db):
    with _sql_conn(db) as conn:
        rows = conn.execute(
            "SELECT id, tenant_ref, label, encode(ST_AsEWKB(shape), 'hex') "
            "FROM dbi.restore_probe ORDER BY id"
        ).fetchall()
        columns = conn.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema='dbi' AND table_name='restore_probe' "
            "ORDER BY ordinal_position"
        ).fetchall()
        constraints = conn.execute(
            "SELECT contype, pg_get_constraintdef(oid) "
            "FROM pg_constraint WHERE conrelid='dbi.restore_probe'::regclass "
            "ORDER BY contype, conname"
        ).fetchall()
        indexes = conn.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname='dbi' AND tablename='restore_probe' "
            "ORDER BY indexname"
        ).fetchall()
        has_postgis = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='postgis')"
        ).fetchone()[0]
    if not has_postgis or len(rows) not in (2, 3):
        raise RehearsalBlocked("invalid ephemeral fixture")
    payload = json.dumps(
        [rows, columns, constraints, indexes],
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest(), rows, indexes


def _setup_fixture(src):
    with _sql_conn(src) as conn:
        conn.execute("CREATE EXTENSION postgis")
        conn.execute("CREATE SCHEMA dbi")
        conn.execute(
            "CREATE TABLE dbi.restore_probe("
            "id integer PRIMARY KEY, tenant_ref varchar(40) NOT NULL, "
            "label text NOT NULL, shape geometry(Point,4326) NOT NULL, "
            "UNIQUE(tenant_ref,label))"
        )
        conn.execute("CREATE INDEX ix_restore_probe_shape_gist "
                     "ON dbi.restore_probe USING gist(shape)")
        for rid, tenant, label, lon, lat in (
            (1, "tenant-alpha", "parcela-norte", -79.81, -3.31),
            (2, "tenant-alpha", "parcela-sur", -79.79, -3.33),
            (3, "tenant-beta", "parcela-este", -79.75, -3.30),
        ):
            conn.execute(
                "INSERT INTO dbi.restore_probe(id,tenant_ref,label,shape) "
                "VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326))",
                (rid, tenant, label, lon, lat),
            )


def rehearse():
    _stage("guard")
    check_runtime(os.environ)
    _stage("docker_identify")
    cid = _container()
    token = uuid4().hex[:12]
    source = "dbi_e6_src_" + token
    dest = "dbi_e6_dst_" + token
    archive = "/tmp/dbi-e6-" + token + ".dump"
    corrupt = "/tmp/dbi-e6-" + token + ".corrupt"
    created = []
    cleanup_failed = False
    answer = None
    try:
        with _sql_conn("postgres") as admin:
            admin.autocommit = True
            try:
                _stage("create_databases")
                for name in (source, dest):
                    _db_action(admin, "CREATE DATABASE {}", name)
                    created.append(name)
                _stage("populate_fixture")
                _setup_fixture(source)
                expected_hash, original_rows, original_indexes = _fixture_fingerprint(source)
                if (len(original_rows) != 3
                        or {row[1] for row in original_rows}
                        != {"tenant-alpha", "tenant-beta"}
                        or not any("USING gist" in item[1] for item in original_indexes)):
                    raise RehearsalBlocked("fixture invalid before backup")
                _stage("dump_archive")
                _docker("exec", "--user", "postgres", cid,
                        "pg_dump", "-h", "/var/run/postgresql", "-U", "postgres",
                        "-d", source, "-n", "dbi", "-Fc",
                        "--no-owner", "--no-privileges", "-f", archive, timeout=45)
                _stage("read_archive")
                dump = _docker("exec", "--user", "postgres", cid, "cat", archive, timeout=35)
                if not dump.startswith(b"PGDMP") or not 256 <= len(dump) <= 2_000_000:
                    raise RehearsalBlocked("invalid backup archive")
                archive_sha = sha256(dump).hexdigest()
                _stage("reject_corrupted_archive")
                with tempfile.TemporaryDirectory(prefix="dbi-e6-corrupt-") as scratch:
                    broken = Path(scratch) / "broken.dump"
                    broken.write_bytes(dump[:16])
                    _docker("cp", str(broken), cid + ":" + corrupt)
                    _docker("exec", "--user", "postgres", cid,
                            "pg_restore", "--list", corrupt,
                            expect_failure=True)

                # Un cambio posterior en el origen no debe contaminar el snapshot.
                with _sql_conn(source) as conn:
                    conn.execute("DELETE FROM dbi.restore_probe WHERE id=2")
                if _fixture_fingerprint(source)[0] == expected_hash:
                    raise RehearsalBlocked("source mutation unexpectedly preserved")

                _stage("prepare_restore")
                with _sql_conn(dest) as conn:
                    conn.execute("CREATE EXTENSION postgis")
                _stage("run_restore")
                _docker("exec", "--user", "postgres", cid,
                        "pg_restore", "-h", "/var/run/postgresql", "-U", "postgres",
                        "-d", dest, "--exit-on-error", "--no-owner", "--no-privileges",
                        archive, timeout=45)
                _stage("compare_restored")
                restored_hash, restored_rows, restored_indexes = _fixture_fingerprint(dest)
                if (restored_hash != expected_hash or restored_rows != original_rows
                        or restored_indexes != original_indexes):
                    raise RehearsalBlocked("restored schema/geometry/data mismatch")
                answer = {
                    "operation": "ci-ephemeral-postgis-restore-rehearsal",
                    "environment": "test",
                    "source": "SYNTHETIC_EPHEMERAL",
                    "pg_dump_restore": "COMPLETED",
                    "archive_sha256": archive_sha,
                    "fixture_sha256": expected_hash,
                    "restored_sha256": restored_hash,
                    "recovered_rows": len(restored_rows),
                    "tenant_count": 2,
                    "geometry_and_schema": "MATCHED",
                    "corrupted_archive": "REJECTED",
                    "source_mutation": "ISOLATED_FROM_RESTORED_SNAPSHOT",
                    "staging_backup_restorability": "NOT_VERIFIED",
                    "migration_apply": "BLOCKED",
                    "deployment_readiness": "NOT_VERIFIED",
                }
            finally:
                for name in reversed(created):
                    try:
                        _db_action(admin, "DROP DATABASE {} WITH (FORCE)", name)
                    except Exception:
                        cleanup_failed = True
    finally:
        if answer is not None:
            _stage("cleanup_archive")
        for name in (archive, corrupt):
            try:
                # docker cp crea el archivo corrupto como root en /tmp sticky.
                _docker("exec", "--user", "root", cid, "rm", "-f", name)
            except Exception:
                cleanup_failed = True
    if cleanup_failed or answer is None:
        raise RehearsalBlocked("disposable resource cleanup incomplete")
    answer["cleanup"] = "COMPLETE"
    return answer


def test_guards():
    allowed = {
        "GITHUB_ACTIONS": "true", "CI": "true",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "DALGORO/dalgoro-banana-intelligence",
        "GITHUB_WORKFLOW": "DBI migrations integration",
        "GITHUB_WORKFLOW_REF": (
            "DALGORO/dalgoro-banana-intelligence/"
            ".github/workflows/dbi-migration-integration.yml@refs/pull/1/merge"
        ),
        "GITHUB_JOB": "dbi-postgis-integration",
        "GITHUB_EVENT_NAME": "pull_request",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "DBI_E6_EPHEMERAL_RESTORE": "1",
        "DBI_ENVIRONMENT": "test",
        "DBI_DATABASE_URL": (
            "postgresql+psycopg://dbi_test_migrator@127.0.0.1:5432/dbi_test"
        ),
    }
    check_runtime(allowed)
    variants = {
        "DBI_ENVIRONMENT": ("staging", "production", "development"),
        "DBI_DATABASE_URL": (
            "postgresql+psycopg://dbi_staging_migrator@127.0.0.1:5432/dbi_staging",
            "postgresql+psycopg://dbi_test_migrator@db.example.org:5432/dbi_test",
            "postgresql+psycopg://postgres@127.0.0.1:5432/postgres",
            "postgresql+psycopg://dbi_test_migrator:secret@127.0.0.1:5432/dbi_test",
        ),
        "GITHUB_WORKFLOW": ("CI modular", "Staging migrations"),
        "GITHUB_JOB": ("backend", "migrator"),
        "GITHUB_REPOSITORY": ("unknown/repo",),
        "GITHUB_ACTIONS": ("false",),
        "DBI_E6_EPHEMERAL_RESTORE": ("0",),
        "RUNNER_ENVIRONMENT": ("self-hosted",),
    }
    for key, values in variants.items():
        for value in values:
            try:
                check_runtime({**allowed, key: value})
            except RehearsalBlocked:
                continue
            raise AssertionError("Unsafe rehearsal guard accepted")
    return {
        "operation": "ci-ephemeral-postgis-restore-guard-test",
        "result": "PASS", "network_access": "NOT_ATTEMPTED",
        "migration_apply": "BLOCKED", "deployment_readiness": "NOT_VERIFIED",
    }


def main():
    parser = argparse.ArgumentParser()
    ops = parser.add_mutually_exclusive_group(required=True)
    ops.add_argument("--check-guards-offline", action="store_true")
    ops.add_argument("--rehearse-ci", action="store_true")
    args = parser.parse_args()
    try:
        report = test_guards() if args.check_guards_offline else rehearse()
        code = 0
    except Exception:
        # Solo identificadores internos de etapa; no errores PG/Docker/credenciales.
        report = {
            "operation": "ci-ephemeral-postgis-restore-rehearsal",
            "result": "BLOCKED",
            "diagnostic_stage": _SAFE_STAGE,
            "migration_apply": "BLOCKED",
            "deployment_readiness": "NOT_VERIFIED",
        }
        code = 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
