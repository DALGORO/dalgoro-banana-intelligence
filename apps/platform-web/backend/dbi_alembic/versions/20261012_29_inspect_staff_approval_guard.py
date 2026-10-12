"""Serialize DALGORO staff changes with INSPECT approvals (read-only runtime).

Revision ID: dbi_0029_staff_approval_guard
Revises: dbi_0028_institutional_staff

Adds BEFORE trigger advisory exclusive transaction guard for ALL staff writes.
The READ-only app takes a shared transaction guard before checking roles and
signing in the same DB transaction. No endpoints, grants, or real staff.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "dbi_0029_staff_approval_guard"
down_revision: str | None = "dbi_0028_institutional_staff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Application reader must use precisely this same signed BIGINT key.
# Not the Alembic migration advisory-lock key.
STAFF_APPROVAL_LOCK_KEY = 451235456312


def upgrade() -> None:
    op.execute(text(f"""
        CREATE FUNCTION dbi.dbi_inspect_staff_write_guard()
        RETURNS trigger LANGUAGE plpgsql AS $body$
        BEGIN
            PERFORM pg_advisory_xact_lock({STAFF_APPROVAL_LOCK_KEY}::bigint);
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $body$
    """))
    op.execute(text("""
        CREATE TRIGGER dbi_inspect_staff_write_guard
        BEFORE INSERT OR UPDATE OR DELETE ON dbi_inspect_staff_roles
        FOR EACH ROW EXECUTE FUNCTION dbi.dbi_inspect_staff_write_guard()
    """))


def downgrade() -> None:
    op.execute(text(
        "DROP TRIGGER IF EXISTS dbi_inspect_staff_write_guard "
        "ON dbi_inspect_staff_roles"
    ))
    op.execute(text(
        "DROP FUNCTION IF EXISTS dbi.dbi_inspect_staff_write_guard()"
    ))
