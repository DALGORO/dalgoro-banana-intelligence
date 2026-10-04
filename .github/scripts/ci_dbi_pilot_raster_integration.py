"""Integración PostGIS del puente local DBI-PILOT-RASTER-001."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / ".github" / "scripts"))

from app.dbi.raster.pilot_builder import (  # noqa: E402
    DBIPilotRasterBuilder,
    DBIPilotRasterUnavailable,
)
from app.dbi.storage_contracts import (  # noqa: E402
    DBIStoragePurpose,
    DBIStorageWriteRequest,
)
from app.dbi.storage_local import DBILocalObjectStore  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from ci_dbi_raster_integration import (  # noqa: E402
    DATABASE,
    FARM_ID,
    HOST,
    ORTHO_ID,
    ORTHO_PAYLOAD,
    PLOT_ID,
    PORT,
    RASTER_ROLE,
    TENANT,
    _provision_raster_role,
)
from ci_dbi_worker_integration import (  # noqa: E402
    NOW,
    _admin_connect,
    _provision_role_and_shared_fixture,
)


PILOT_ORTHO_ID = UUID("85000000-0000-4000-8000-000000000099")
PILOT_ORTHO_PAYLOAD = b"pilot-raster-source-ci" * 8192
FAKE_COG = b"pilot-raster-ci-cog" * 4096
FAKE_COG_SHA = hashlib.sha256(FAKE_COG).hexdigest()
SOURCE_SHA = hashlib.sha256(PILOT_ORTHO_PAYLOAD).hexdigest()


def _require_scope() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("La integración Pilot Raster sólo corre en GitHub Actions.")
    if os.environ.get("DBI_RASTER_RUN_INTEGRATION") != "1":
        raise RuntimeError("Falta DBI_RASTER_RUN_INTEGRATION=1.")
    if os.environ.get("DBI_ENVIRONMENT") != "test":
        raise RuntimeError("La integración Pilot Raster exige DBI_ENVIRONMENT=test.")


def _factory():
    engine = create_engine(
        f"postgresql+psycopg://{RASTER_ROLE}@{HOST}:{PORT}/{DATABASE}",
        poolclass=NullPool,
        future=True,
    )
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _pilot_source_metadata():
    return DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref=TENANT,
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=PILOT_ORTHO_ID,
        ),
        content_type="image/tiff",
        size_bytes=len(PILOT_ORTHO_PAYLOAD),
        sha256_hex=SOURCE_SHA,
    )


def _provision_pilot_source() -> None:
    metadata = _pilot_source_metadata()
    with _admin_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO dbi.dbi_analysis_input_assets
                    (id, tenant_ref, farm_id, plot_id, asset_kind, status, object_key,
                     content_type, size_bytes, sha256, crs, created_by_ref, verified_at,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'orthophoto', 'verified', %s, %s, %s, %s,
                        'EPSG:32717', 'actor-pilot-raster-ci', %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    object_key = EXCLUDED.object_key,
                    content_type = EXCLUDED.content_type,
                    size_bytes = EXCLUDED.size_bytes,
                    sha256 = EXCLUDED.sha256,
                    crs = EXCLUDED.crs,
                    verified_at = EXCLUDED.verified_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    PILOT_ORTHO_ID,
                    TENANT,
                    FARM_ID,
                    PLOT_ID,
                    metadata.address.object_key,
                    metadata.content_type,
                    metadata.size_bytes,
                    metadata.sha256,
                    NOW,
                    NOW,
                    NOW,
                ),
            )


def _put_source(store: DBILocalObjectStore) -> None:
    store.put(
        DBIStorageWriteRequest(metadata=_pilot_source_metadata()),
        BytesIO(PILOT_ORTHO_PAYLOAD),
    )


def _fake_flight_script(path: Path, marker: Path) -> None:
    source = f'''from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

source_path = Path(sys.argv[1])
cog_path = Path(sys.argv[2])
manifest_path = Path(sys.argv[sys.argv.index("--manifest") + 1])
profile = sys.argv[sys.argv.index("--profile-version") + 1]
payload = {FAKE_COG!r}
cog_path.write_bytes(payload)
source_bytes = source_path.read_bytes()
manifest = {{
    "schema_version": "dbi-raster-flight-test.v1",
    "product_kind": "rgb_visual",
    "profile_version": profile,
    "generator": "pilot-raster-ci-v1",
    "source_name": source_path.name,
    "source_size_bytes": len(source_bytes),
    "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
    "cog_name": cog_path.name,
    "cog_size_bytes": len(payload),
    "cog_sha256": hashlib.sha256(payload).hexdigest(),
    "descriptor": {{
        "width": 1024,
        "height": 768,
        "band_count": 3,
        "dtypes": ["uint8", "uint8", "uint8"],
        "crs": "EPSG:32717",
        "transform": [0.03, 0.0, 620000.0, 0.0, -0.03, 9640000.0],
        "bounds": [620000.0, 9639976.96, 620030.72, 9640000.0],
        "nodata": [None, None, None],
        "scales": [1.0, 1.0, 1.0],
        "offsets": [0.0, 0.0, 0.0],
        "tiled": True,
        "block_shapes": [[512, 512], [512, 512], [512, 512]],
        "compression": "deflate",
        "overview_levels": [2, 4]
    }}
}}
manifest_path.write_text(
    json.dumps(manifest, ensure_ascii=False),
    encoding="utf-8",
)
Path({str(marker)!r}).write_text("executed", encoding="utf-8")
print(json.dumps({{"status": "validated"}}))
'''
    path.write_text(source, encoding="utf-8")


def validate_builder(factory, root: Path) -> None:
    store = DBILocalObjectStore(root / "storage")
    _put_source(store)

    fake_script = root / "fake_flight_test.py"
    marker = root / "renderer-marker.txt"
    _fake_flight_script(fake_script, marker)

    session = factory()
    try:
        builder = DBIPilotRasterBuilder(
            session,
            store,
            raster_python=sys.executable,
            flight_test_script=fake_script,
            timeout_seconds=30,
        )
        before = set(store.staging_directory.iterdir())
        first = builder.prepare_rgb(
            tenant_ref=TENANT,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            asset_id=PILOT_ORTHO_ID,
        )
        session.commit()

        after = set(store.staging_directory.iterdir())
        assert before == after
        assert marker.is_file()
        assert first.created is True
        assert first.status == "ready"
        assert first.source_asset_id == PILOT_ORTHO_ID
        assert first.sha256 == FAKE_COG_SHA
        assert first.width == 1024
        assert first.height == 768
        assert first.band_count == 3

        marker.unlink()
        replay = builder.prepare_rgb(
            tenant_ref=TENANT,
            farm_id=FARM_ID,
            plot_id=PLOT_ID,
            asset_id=PILOT_ORTHO_ID,
        )
        session.commit()
        assert replay.product_id == first.product_id
        assert replay.created is False
        assert not marker.exists(), "El replay no debe volver a ejecutar Rasterio."

        address = DBIStoragePolicy.build_address(
            tenant_ref=TENANT,
            purpose=DBIStoragePurpose.RASTER_PRODUCT,
            object_id=first.product_id,
        )
        record = store.stat(address)
        assert record.metadata.sha256 == FAKE_COG_SHA
        assert record.metadata.size_bytes == len(FAKE_COG)
    finally:
        session.rollback()
        session.close()


def validate_rejects_unknown_source(factory, root: Path) -> None:
    store = DBILocalObjectStore(root / "storage-unknown")
    session = factory()
    try:
        builder = DBIPilotRasterBuilder(
            session,
            store,
            raster_python=sys.executable,
            flight_test_script=root / "fake_flight_test.py",
            timeout_seconds=30,
        )
        try:
            builder.prepare_rgb(
                tenant_ref=TENANT,
                farm_id=FARM_ID,
                plot_id=PLOT_ID,
                asset_id=uuid4(),
            )
        except DBIPilotRasterUnavailable:
            pass
        else:
            raise AssertionError("Una ortofoto desconocida debía rechazarse.")
    finally:
        session.rollback()
        session.close()


def main() -> None:
    _require_scope()
    _provision_role_and_shared_fixture()
    _provision_pilot_source()
    _provision_raster_role()
    engine, factory = _factory()
    try:
        with TemporaryDirectory(prefix="dbi-pilot-raster-ci-") as directory:
            root = Path(directory)
            validate_builder(factory, root)
            validate_rejects_unknown_source(factory, root)
    finally:
        engine.dispose()
    print(
        "DBI-PILOT-RASTER-001 aprobado: COG aislado, registro ready, "
        "replay sin rerender y staging limpio."
    )


if __name__ == "__main__":
    main()
