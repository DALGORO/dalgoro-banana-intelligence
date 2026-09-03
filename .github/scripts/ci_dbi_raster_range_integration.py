"""Demuestra lectura parcial de un producto Raster registrado sin full-buffer."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.raster.contracts import DBIRasterConflict  # noqa: E402
from app.dbi.raster.reader import (  # noqa: E402
    DBIRasterProductReader,
    DBIRasterProductUnavailable,
)
from ci_dbi_raster_integration import (  # noqa: E402
    COG_PAYLOAD,
    FARM_ID,
    PLOT_ID,
    RASTER_ROLE,
    TENANT,
    _candidate,
    _factory,
    _object_store,
    _provision_raster_role,
    _put_cog,
    _register,
    _require_scope,
)
from ci_dbi_worker_integration import _provision_role_and_shared_fixture  # noqa: E402


def main() -> None:
    _require_scope()
    _provision_role_and_shared_fixture()
    _provision_raster_role()
    engine, factory = _factory(RASTER_ROLE)
    store = _object_store()
    candidate = _candidate("cog_range_v1")
    _put_cog(store, candidate)
    _register(factory, store, candidate)

    session = factory()
    try:
        reader = DBIRasterProductReader(session, store)
        metadata = reader.metadata(
            product_id=candidate.object_id,
            tenant_ref=TENANT,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
        )
        assert metadata.size_bytes == len(COG_PAYLOAD)
        assert metadata.product_id == candidate.object_id
        assert not hasattr(metadata, "object_key")

        partial = reader.read_range(
            product_id=candidate.object_id,
            tenant_ref=TENANT,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            start=0,
            end_exclusive=1024,
        )
        assert partial.length == 1024
        assert partial.data == COG_PAYLOAD[:1024]
        assert partial.total_size_bytes == len(COG_PAYLOAD)
        assert partial.length < partial.total_size_bytes

        try:
            reader.read_range(
                product_id=candidate.object_id,
                tenant_ref=TENANT,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                start=0,
                end_exclusive=len(COG_PAYLOAD) + 1,
            )
        except DBIRasterConflict:
            pass
        else:
            raise AssertionError("Un rango fuera del objeto no fue rechazado.")

        try:
            reader.read_range(
                product_id=candidate.object_id,
                tenant_ref=TENANT,
                farm_id=FARM_ID,
                plot_id=type(PLOT_ID)(int=PLOT_ID.int + 1),
                start=0,
                end_exclusive=16,
            )
        except DBIRasterProductUnavailable:
            pass
        else:
            raise AssertionError("Un lote ajeno pudo leer el producto Raster.")
    finally:
        session.close()
        engine.dispose()

    print(
        "DBI-RASTER-001 range aprobado: 1 KiB leído sin materializar el COG completo."
    )


if __name__ == "__main__":
    main()
