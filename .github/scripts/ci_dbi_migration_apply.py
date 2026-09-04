"""Adaptador de linaje apply Alembic para DBI-RASTER-001."""

from __future__ import annotations

import ci_dbi_migration_apply_base as base

base.HEAD = "dbi_0015_raster_products"
base.KNOWN = set(base.KNOWN) | {"dbi_0014_analysis_results", base.HEAD}


if __name__ == "__main__":
    base.main()
