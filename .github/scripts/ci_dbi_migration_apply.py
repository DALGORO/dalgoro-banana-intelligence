"""Adaptador de linaje apply Alembic para DBI-CAMPAIGN-001."""

from __future__ import annotations

import ci_dbi_migration_apply_base as base

base.HEAD = "dbi_0023_gis_previews"
base.KNOWN = set(base.KNOWN) | {
    "dbi_0014_analysis_results",
    "dbi_0015_raster_products",
    "dbi_0016_sampling_plans",
    "dbi_0018_multi_extractions",
    "dbi_0019_campaign_domain",
    "dbi_0020_campaign_artifacts",
    "dbi_0021_portal_vectors",
    "dbi_0022_portal_gis_imports",
    base.HEAD,
}


if __name__ == "__main__":
    base.main()
