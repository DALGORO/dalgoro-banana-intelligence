"""Adaptador de cabeza Alembic para DBI-SAMPLING-001."""

from __future__ import annotations

import ci_dbi_migration_cli_base as base

base.HEAD = "dbi_0016_sampling_plans"


if __name__ == "__main__":
    base.main()
