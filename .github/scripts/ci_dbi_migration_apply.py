"""Adaptador de linaje apply Alembic para DBI-INSPECT-001."""

from __future__ import annotations

import ci_dbi_migration_apply_base as base

base.HEAD = "dbi_0017_field_observations"
base.KNOWN = set(base.KNOWN) | {
    "dbi_0014_analysis_results",
    "dbi_0015_raster_products",
    "dbi_0016_sampling_plans",
    base.HEAD,
}


if __name__ == "__main__":
    base.main()
