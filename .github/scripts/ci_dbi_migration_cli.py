"""Adaptador de cabeza Alembic para DBI-RASTER-001."""

from __future__ import annotations

import ci_dbi_migration_cli_base as base

base.HEAD = "dbi_0015_raster_products"


if __name__ == "__main__":
    base.main()
