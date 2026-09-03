"""Adapta la integración DBI existente a la cabeza durable de QUEUE-001."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
sys.path.insert(0, str(BACKEND))

import ci_dbi_migration_integration as migration  # noqa: E402
from app.db.dbi_config import load_dbi_database_config  # noqa: E402

EXPECTED_HEAD = "dbi_0012_durable_delivery"
DELIVERY_CONSTRAINTS = frozenset(
    {
        "uq_dbi_analysis_job_attempts_id_job",
        "fk_dbi_delivery_messages_attempt_job",
        "uq_dbi_delivery_messages_stream_attempt",
        "ck_dbi_delivery_messages_stream",
        "ck_dbi_delivery_messages_status",
        "ck_dbi_delivery_messages_stream_schema",
        "ck_dbi_delivery_messages_sha256",
        "ck_dbi_delivery_messages_payload_size",
        "ck_dbi_delivery_messages_delivery_count",
        "ck_dbi_delivery_messages_active_lease",
        "ck_dbi_delivery_messages_delivered_at",
        "ck_dbi_delivery_messages_error_code",
    }
)
DELIVERY_INDEXES = frozenset(
    {
        "ix_dbi_delivery_messages_claim",
        "ix_dbi_delivery_messages_lease_expiry",
        "ix_dbi_delivery_messages_job",
        "ix_dbi_delivery_messages_correlation",
    }
)


def validate_delivery_schema() -> None:
    config = load_dbi_database_config()
    engine = create_engine(config.url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM dbi.alembic_version_dbi")
            ).scalar_one()
            assert revision == EXPECTED_HEAD

            constraints = set(
                connection.execute(
                    text(
                        """
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE table_schema = 'dbi'
                          AND table_name IN (
                            'dbi_analysis_job_attempts',
                            'dbi_delivery_messages'
                          )
                        """
                    )
                ).scalars()
            )
            assert DELIVERY_CONSTRAINTS <= constraints, sorted(
                DELIVERY_CONSTRAINTS - constraints
            )

            indexes = set(
                connection.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'dbi'
                          AND tablename = 'dbi_delivery_messages'
                        """
                    )
                ).scalars()
            )
            assert DELIVERY_INDEXES <= indexes, sorted(DELIVERY_INDEXES - indexes)

            columns = {
                row["column_name"]: row
                for row in connection.execute(
                    text(
                        """
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'dbi'
                          AND table_name = 'dbi_delivery_messages'
                        """
                    )
                ).mappings()
            }
            for required in (
                "payload_json",
                "payload_sha256",
                "lease_ref",
                "lease_expires_at",
                "last_lease_ref",
                "delivery_count",
                "max_deliveries",
            ):
                assert required in columns
    finally:
        engine.dispose()


def main() -> None:
    migration.EXPECTED_HEAD = EXPECTED_HEAD
    migration.main()
    validate_delivery_schema()
    print("DBI-QUEUE-001 migración dbi_0012 aprobada en PostGIS efímero.")


if __name__ == "__main__":
    main()
