"""Adaptador de cabeza Alembic para DBI-INSPECT-001."""

from __future__ import annotations

import ci_dbi_migration_cli_base as base

base.HEAD = "dbi_0022_portal_gis_imports"


if __name__ == "__main__":
    base.main()
