"""CI del adaptador local subprocess para tiles Raster DBI."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.raster.local_tile_renderer import (  # noqa: E402
    DBILocalSubprocessRasterTileRenderer,
)
from app.dbi.raster.tile_service import (  # noqa: E402
    DBIRasterTileOutsideExtent,
    DBIRasterTileRenderRequest,
    DBIRasterTileRendererUnavailable,
)
from app.dbi.raster.tiles import (  # noqa: E402
    DBIRasterTileCoordinate,
    DBIRasterTileStyle,
)
from app.dbi.storage_contracts import (  # noqa: E402
    DBIStoragePurpose,
    DBIStorageWriteRequest,
)
from app.dbi.storage_local import DBILocalObjectStore  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402

TENANT = "tenant-raster-local-adapter-ci"
FARM = UUID("51000000-0000-4000-8000-000000000051")
PLOT = UUID("52000000-0000-4000-8000-000000000052")
PRODUCT = UUID("53000000-0000-4000-8000-000000000053")
PAYLOAD = b"fake-cog-bytes-for-local-renderer-ci"
SHA = sha256(PAYLOAD).hexdigest()
PNG = b"\x89PNG\r\n\x1a\nLOCAL-ADAPTER-CI"


def _store(root: Path) -> DBILocalObjectStore:
    store = DBILocalObjectStore(root)
    address = DBIStoragePolicy.build_address(
        tenant_ref=TENANT,
        purpose=DBIStoragePurpose.RASTER_PRODUCT,
        object_id=PRODUCT,
    )
    metadata = DBIStoragePolicy.build_metadata(
        address=address,
        content_type="image/tiff",
        size_bytes=len(PAYLOAD),
        sha256_hex=SHA,
    )
    store.put(DBIStorageWriteRequest(metadata=metadata), BytesIO(PAYLOAD))
    path = store.resolve_internal_path(address)
    assert path.is_file()
    assert path.read_bytes() == PAYLOAD
    return store


def _request() -> DBIRasterTileRenderRequest:
    return DBIRasterTileRenderRequest(
        tenant_ref=TENANT,
        farm_id=FARM,
        plot_id=PLOT,
        product_id=PRODUCT,
        product_kind="rgb_visual",
        product_sha256=SHA,
        source_profile_version="cog_v1",
        coordinate=DBIRasterTileCoordinate(z=14, x=4558, y=8344),
        style=DBIRasterTileStyle(
            style_id="rgb-natural-v1",
            render_mode="rgb",
            band_indexes=(1, 2, 3),
        ),
    )


def _write_script(path: Path, *, exit_code: int = 0) -> None:
    if exit_code == 0:
        source = (
            "import sys\n"
            "data = b'\\x89PNG\\r\\n\\x1a\\nLOCAL-ADAPTER-CI'\n"
            "sys.stdout.buffer.write(data)\n"
            "raise SystemExit(0)\n"
        )
    else:
        source = f"raise SystemExit({exit_code})\n"
    path.write_text(source, encoding="utf-8")


def validate_success_and_isolation(tmp: Path) -> None:
    store = _store(tmp / "storage")
    script = tmp / "renderer_ok.py"
    _write_script(script)

    renderer = DBILocalSubprocessRasterTileRenderer(
        store,
        script_path=script,
        python_executable=sys.executable,
        timeout_seconds=5,
    )
    result = renderer.render_tile(_request())
    assert result.data == PNG
    assert result.content_type == "image/png"

    source = (
        BACKEND / "app" / "dbi" / "raster" / "local_tile_renderer.py"
    ).read_text(encoding="utf-8").lower()
    for forbidden in (
        "import rasterio",
        "from rasterio",
        "import gdal",
        "from osgeo",
    ):
        assert forbidden not in source


def validate_outside_and_failure(tmp: Path) -> None:
    store = _store(tmp / "storage-errors")

    outside = tmp / "renderer_outside.py"
    _write_script(outside, exit_code=4)
    outside_renderer = DBILocalSubprocessRasterTileRenderer(
        store,
        script_path=outside,
        python_executable=sys.executable,
        timeout_seconds=5,
    )
    try:
        outside_renderer.render_tile(_request())
    except DBIRasterTileOutsideExtent:
        pass
    else:
        raise AssertionError("exit 4 debía mapearse a OutsideExtent.")

    failed = tmp / "renderer_failed.py"
    _write_script(failed, exit_code=5)
    failed_renderer = DBILocalSubprocessRasterTileRenderer(
        store,
        script_path=failed,
        python_executable=sys.executable,
        timeout_seconds=5,
    )
    try:
        failed_renderer.render_tile(_request())
    except DBIRasterTileRendererUnavailable:
        pass
    else:
        raise AssertionError("fallo de subprocess debía cerrar con 503 lógico.")


def main() -> None:
    with TemporaryDirectory(prefix="dbi-raster-local-adapter-") as directory:
        tmp = Path(directory)
        validate_success_and_isolation(tmp)
        validate_outside_and_failure(tmp)
    print(
        "DBI-RASTER-TILE-001 adapter local aprobado: path server-side, "
        "subprocess aislado, PNG, outside y fallo cerrado."
    )


if __name__ == "__main__":
    main()
