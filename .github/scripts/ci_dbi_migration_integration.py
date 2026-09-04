"""Adaptador de cabeza Alembic para DBI-RASTER-001.

Conserva íntegro el fixture histórico en ``ci_dbi_migration_integration_base``
y únicamente avanza la revisión esperada al incremento Raster actual.
"""

from __future__ import annotations

import ci_dbi_migration_integration_base as base

base.EXPECTED_HEAD = "dbi_0015_raster_products"


if __name__ == "__main__":
    base.main()
