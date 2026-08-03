"""Valida persistencia multipartes DBI sin conexiones externas."""

from __future__ import annotations

import os
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.dbi_base import DBIBase  # noqa: E402
from app.dbi.models import (  # noqa: E402
    AnalysisInputAsset,
    AssetMultipartPart,
    AssetMultipartSession,
)

HEAD = "dbi_0010_asset_multipart"
SESSION_TABLE = "dbi_asset_multipart_sessions"
PART_TABLE = "dbi_asset_multipart_parts"
SESSION_COLUMNS = {
    "id",
    "asset_id",
    "tenant_ref",
    "status",
    "reason_code",
    "provider_upload_ref",
    "size_bytes",
    "part_size_bytes",
    "part_count",
    "max_grants_per_window",
    "max_client_concurrency",
    "checksum_algorithm",
    "checksum_type",
    "idempotency_key_hash",
    "request_fingerprint",
    "created_by_ref",
    "version",
    "expires_at",
    "last_activity_at",
    "completed_at",
    "aborted_at",
    "expired_at",
    "created_at",
    "updated_at",
}
PART_COLUMNS = {
    "session_id",
    "part_number",
    "tenant_ref",
    "size_bytes",
    "checksum",
    "etag",
    "observed_at",
}
REQUIRED_SESSION_CONSTRAINTS = {
    "ck_dbi_multipart_sessions_status",
    "ck_dbi_multipart_sessions_reason",
    "ck_dbi_multipart_sessions_provider_context",
    "ck_dbi_multipart_sessions_provider_ref",
    "ck_dbi_multipart_sessions_positive_size",
    "ck_dbi_multipart_sessions_positive_part_size",
    "ck_dbi_multipart_sessions_part_count",
    "ck_dbi_multipart_sessions_grant_window",
    "ck_dbi_multipart_sessions_concurrency",
    "ck_dbi_multipart_sessions_checksum_pair",
    "ck_dbi_multipart_sessions_idempotency_hash",
    "ck_dbi_multipart_sessions_request_fingerprint",
    "ck_dbi_multipart_sessions_positive_version",
    "ck_dbi_multipart_sessions_terminal_timestamps",
    "ck_dbi_multipart_sessions_active_expiry",
    "ck_dbi_multipart_sessions_timestamp_order",
}
REQUIRED_PART_CONSTRAINTS = {
    "ck_dbi_multipart_parts_number",
    "ck_dbi_multipart_parts_positive_size",
    "ck_dbi_multipart_parts_checksum",
    "ck_dbi_multipart_parts_etag",
}


def _named_constraints(table, constraint_type):
    return {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, constraint_type)
    }


def validate_metadata() -> None:
    """Comprueba tablas, columnas y claves compuestas de aislamiento."""

    assert {AssetMultipartSession, AssetMultipartPart, AnalysisInputAsset}
    session_table = DBIBase.metadata.tables[SESSION_TABLE]
    part_table = DBIBase.metadata.tables[PART_TABLE]
    asset_table = DBIBase.metadata.tables["dbi_analysis_input_assets"]

    assert set(session_table.columns.keys()) == SESSION_COLUMNS
    assert set(part_table.columns.keys()) == PART_COLUMNS
    assert set(session_table.primary_key.columns.keys()) == {"id"}
    assert set(part_table.primary_key.columns.keys()) == {
        "session_id",
        "part_number",
    }
    assert "idempotency_key" not in session_table.c

    asset_unique = _named_constraints(asset_table, UniqueConstraint)
    assert set(
        asset_unique["uq_dbi_analysis_input_assets_id_tenant"].columns.keys()
    ) == {"id", "tenant_ref"}

    session_unique = _named_constraints(session_table, UniqueConstraint)
    assert set(
        session_unique["uq_dbi_multipart_sessions_id_tenant"].columns.keys()
    ) == {"id", "tenant_ref"}
    assert set(
        session_unique["uq_dbi_multipart_sessions_idempotency"].columns.keys()
    ) == {"tenant_ref", "idempotency_key_hash"}

    session_fks = _named_constraints(session_table, ForeignKeyConstraint)
    asset_fk = session_fks["fk_dbi_multipart_sessions_asset_tenant"]
    assert [element.parent.name for element in asset_fk.elements] == [
        "asset_id",
        "tenant_ref",
    ]
    assert [element.target_fullname for element in asset_fk.elements] == [
        "dbi_analysis_input_assets.id",
        "dbi_analysis_input_assets.tenant_ref",
    ]
    assert asset_fk.ondelete == "CASCADE"

    part_fks = _named_constraints(part_table, ForeignKeyConstraint)
    session_fk = part_fks["fk_dbi_multipart_parts_session_tenant"]
    assert [element.parent.name for element in session_fk.elements] == [
        "session_id",
        "tenant_ref",
    ]
    assert [element.target_fullname for element in session_fk.elements] == [
        "dbi_asset_multipart_sessions.id",
        "dbi_asset_multipart_sessions.tenant_ref",
    ]
    assert session_fk.ondelete == "CASCADE"

    assert AssetMultipartSession.asset.property.mapper.class_ is AnalysisInputAsset
    assert AssetMultipartSession.parts.property.mapper.class_ is AssetMultipartPart
    assert AssetMultipartPart.session.property.mapper.class_ is AssetMultipartSession


def validate_constraints_and_indexes() -> None:
    """Comprueba invariantes de estado, integridad e idempotencia."""

    session_table = DBIBase.metadata.tables[SESSION_TABLE]
    part_table = DBIBase.metadata.tables[PART_TABLE]
    session_checks = _named_constraints(session_table, CheckConstraint)
    part_checks = _named_constraints(part_table, CheckConstraint)

    assert REQUIRED_SESSION_CONSTRAINTS <= session_checks.keys()
    assert REQUIRED_PART_CONSTRAINTS <= part_checks.keys()

    status_sql = str(session_checks["ck_dbi_multipart_sessions_status"].sqltext)
    assert "completed_pending_content_verification" in status_sql
    assert "blocked_by_policy" in status_sql

    provider_sql = str(
        session_checks["ck_dbi_multipart_sessions_provider_context"].sqltext
    )
    assert "status IN ('initiated', 'aborted', 'expired')" in provider_sql
    assert "OR provider_upload_ref IS NOT NULL" in provider_sql
    assert "status = 'blocked_by_policy'" in provider_sql

    checksum_sql = str(
        session_checks["ck_dbi_multipart_sessions_checksum_pair"].sqltext
    )
    assert "SHA256" in checksum_sql and "COMPOSITE" in checksum_sql
    assert "CRC64NVME" in checksum_sql and "FULL_OBJECT" in checksum_sql

    indexes = {index.name: index for index in session_table.indexes}
    assert {
        "ix_dbi_multipart_sessions_tenant_ref",
        "ix_dbi_multipart_sessions_asset_id",
        "ix_dbi_multipart_sessions_cleanup",
        "uq_dbi_multipart_sessions_active_asset",
    } <= indexes.keys()
    active = indexes["uq_dbi_multipart_sessions_active_asset"]
    assert active.unique is True
    assert [column.name for column in active.columns] == [
        "tenant_ref",
        "asset_id",
    ]
    predicate = str(active.dialect_options["postgresql"]["where"])
    assert "initiated" in predicate and "uploading" in predicate


def validate_safe_model_representation() -> None:
    """Impide que referencias del proveedor y evidencias aparezcan en repr."""

    now = datetime.now(timezone.utc)
    session = AssetMultipartSession(
        id=uuid4(),
        asset_id=uuid4(),
        tenant_ref="tenant-a",
        status="initiated",
        provider_upload_ref="provider-secret-reference",
        size_bytes=10 * 1024**3,
        part_size_bytes=64 * 1024**2,
        part_count=160,
        max_grants_per_window=8,
        max_client_concurrency=4,
        checksum_algorithm="SHA256",
        checksum_type="COMPOSITE",
        idempotency_key_hash="a" * 64,
        request_fingerprint="b" * 64,
        created_by_ref="principal-a",
        expires_at=now + timedelta(hours=24),
        last_activity_at=now,
        created_at=now,
        updated_at=now,
    )
    part = AssetMultipartPart(
        session_id=session.id,
        part_number=1,
        tenant_ref="tenant-a",
        size_bytes=64 * 1024**2,
        checksum="Y2hlY2tzdW0=",
        etag="etag-1",
        observed_at=now,
    )
    assert "provider-secret-reference" not in repr(session)
    assert "Y2hlY2tzdW0=" not in repr(part)
    assert "etag-1" not in repr(part)


def validate_migration_graph_and_sql() -> None:
    """Verifica una sola cabeza y genera todo el DDL sin conectarse."""

    config = Config(str(BACKEND_ROOT / "dbi_alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert len(HEAD) <= 32
    assert all(
        len(item.revision) <= 32 for item in scripts.walk_revisions()
    )
    assert scripts.get_heads() == [HEAD]
    revision = scripts.get_revision(HEAD)
    assert revision is not None
    assert revision.down_revision == "dbi_0009_object_key_check"

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
    assert f"create table {SESSION_TABLE}" in sql
    assert f"create table {PART_TABLE}" in sql
    assert "uq_dbi_analysis_input_assets_id_tenant" in sql
    assert "fk_dbi_multipart_sessions_asset_tenant" in sql
    assert "fk_dbi_multipart_parts_session_tenant" in sql
    assert "uq_dbi_multipart_sessions_active_asset" in sql
    assert "where status in ('initiated', 'uploading')" in sql
    assert HEAD in sql
    for forbidden in (
        "create extension",
        "insert into dbi_",
        "gen_random_uuid",
        "uuid_generate",
        "create table users",
        "create table companies",
        "create table documents",
    ):
        assert forbidden not in sql


def validate_static_boundaries() -> None:
    """Mantiene este bloque fuera de API, SDK, credenciales y binarios."""

    model_source = (
        BACKEND_ROOT / "app" / "dbi" / "models" / "asset_multipart.py"
    ).read_text(encoding="utf-8").lower()
    migration_source = (
        BACKEND_ROOT
        / "dbi_alembic"
        / "versions"
        / "20260803_10_asset_multipart_sessions.py"
    ).read_text(encoding="utf-8").lower()
    combined = model_source + migration_source

    assert 'revision: str = "dbi_0010_asset_multipart"' in migration_source
    assert 'down_revision: str | none = "dbi_0009_object_key_check"' in migration_source
    assert "op.create_unique_constraint" in migration_source
    assert "postgresql_where" in combined
    assert "provider_upload_ref" in combined
    assert "idempotency_key_hash" in combined
    assert "idempotency_key:" not in combined

    for forbidden in (
        "create_engine",
        "sessionmaker",
        "fastapi",
        "apirouter",
        "boto",
        "google.cloud.storage",
        "azure.storage",
        "presigned",
        "signed_url",
        "http://",
        "https://",
        "op.execute",
        "op.bulk_insert",
        "largebinary",
        "bytea",
    ):
        assert forbidden not in combined


def main() -> None:
    validate_metadata()
    validate_constraints_and_indexes()
    validate_safe_model_representation()
    validate_migration_graph_and_sql()
    validate_static_boundaries()
    print("Persistencia multipartes DBI-ASSET-003 aprobada offline.")


if __name__ == "__main__":
    main()
