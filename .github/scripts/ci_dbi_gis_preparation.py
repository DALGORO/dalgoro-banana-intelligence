"""Test offline de claim, integridad y vista previa GIS antes de publicación."""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_gis_preview.db")
os.environ.setdefault("JWT_SECRET", "ci-gis-preview-only")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.api.v1.dbi_portal_gis_imports import get_gis_import_preview  # noqa: E402
from app.dbi.authorization import DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission  # noqa: E402
from app.dbi.models.portal_gis_imports import DBIPortalGISImport, DBIPortalGISPreview  # noqa: E402
from app.dbi.portal_gis_worker_service import DBIPortalGISPreparationWorker, GISLayersPendingSelection  # noqa: E402
from app.dbi.storage_contracts import DBIStoragePurpose, DBIStorageWriteRequest  # noqa: E402
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class State:
    def __init__(self, row):
        self.row = row
        self.preview = None
        self.commits = 0


class Session:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        row = self.state.row
        if "FROM dbi_campaigns" in sql:
            for name in ("id", "tenant_ref", "organization_ref", "farm_id", "plot_id"):
                assert f"dbi_campaigns.{name} =" in sql
            # Esta fixture contiene una Campaign válida; la comparación
            # de valores cruzados se prueba en ci_dbi_gis_selected_layer_lifecycle.
            return type("CampaignResult", (), {
                "scalar_one_or_none": lambda self: object(),
            })()
        assert "dbi_portal_gis_imports" in sql
        if row.tenant_ref not in sql:
            found = None
        elif "attempt_count <" in sql and not (
            row.status in {"received", "processing"}
            or (row.status == "needs_selection" and row.source_format == "gpkg"
                and row.selected_layer is not None)
        ):
            found = None
        else:
            found = row
        class Result:
            def scalar_one_or_none(self):
                return found
        return Result()

    def get(self, model, id):
        assert model is DBIPortalGISPreview
        return self.state.preview if self.state.preview and self.state.preview.import_id == id else None

    def add(self, row):
        assert isinstance(row, DBIPortalGISPreview)
        self.state.preview = row

    def commit(self):
        self.state.commits += 1


def make_receipt(payload: bytes, *, tenant="tenant-gis"):
    now = datetime.now(timezone.utc)
    return DBIPortalGISImport(
        id=uuid4(), tenant_ref=tenant, organization_ref="org-gis",
        farm_id=uuid4(), plot_id=uuid4(), campaign_id=uuid4(),
        source_object_id=uuid4(), source_format="gpkg",
        original_filename="sector.gpkg", name="Inventario", layer_kind="plants",
        size_bytes=len(payload), sha256=sha256(payload).hexdigest(),
        status="received", attempt_count=0,
        created_at=now, created_by_ref="operator-gis",
    )


def manager(row):
    return DBIAccessContext(
        principal_ref="operator-gis", tenant_ref=row.tenant_ref,
        organization_refs=frozenset({"org-gis"}),
        farm_scopes=frozenset({DBIFarmScope("org-gis", row.farm_id)}),
        plot_scopes=frozenset({DBIPlotScope("org-gis", row.farm_id, row.plot_id)}),
        permissions=frozenset({DBIPermission.MANAGE}),
    )


def converter(expected_hash: str, *, corrupt=False, manifest_layer=None, expected_layer=None):
    def run(source: Path, output_dir: Path, *, layer=None):
        assert sha256(source.read_bytes()).hexdigest() == expected_hash
        assert layer == expected_layer
        raw = json.dumps(
            {"type": "FeatureCollection", "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-79.8, -3.3]},
                 "properties": {"plantas": 1500}}
            ]}, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        preview = output_dir / "safe.geojson"
        preview.write_bytes(raw)
        manifest = output_dir / "safe.manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": "dbi-portal-gis-conversion.v1",
            "source_sha256": expected_hash if not corrupt else "0" * 64,
            "source_size_bytes": source.stat().st_size,
            "output_sha256": sha256(raw).hexdigest(),
            "output_crs": "EPSG:4326",
            "feature_count": 1, "captured_at": None,
            "source_layer": manifest_layer if manifest_layer is not None else layer,
        }), encoding="utf-8")
        return preview, manifest
    return run


def stage(store, row, payload):
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref=row.tenant_ref, purpose=DBIStoragePurpose.TECHNICAL_SOURCE,
            object_id=row.source_object_id),
        content_type="application/geopackage+sqlite3",
        size_bytes=len(payload), sha256_hex=row.sha256,
    )
    store.put(DBIStorageWriteRequest(metadata=metadata), BytesIO(payload))


def run():
    payload = b"SQLite format 3\x00" + b"test-gis-data"
    store = DBIInMemoryObjectStore()
    receipt = make_receipt(payload)
    stage(store, receipt, payload)
    state = State(receipt)
    with TemporaryDirectory(prefix="dbi-preview-tests-") as root:
        worker = DBIPortalGISPreparationWorker(
            lambda: Session(state), store, converter(receipt.sha256),
            workspace_root=Path(root),
        )
        assert worker.claim_one(tenant_ref="other-tenant") is None
        assert worker.process_one(tenant_ref=receipt.tenant_ref) == "prepared"
        assert receipt.status == "prepared"
        assert receipt.attempt_count == 1
        assert receipt.processing_ref is None
        assert state.preview.feature_count == 1
        assert state.preview.sha256 == sha256(state.preview.geojson_text.encode("utf-8")).hexdigest()
        assert worker.process_one(tenant_ref=receipt.tenant_ref) is None
        assert list(Path(root).iterdir()) == []  # temporales limpios

        preview = get_gis_import_preview(
            "org-gis", receipt.farm_id, receipt.plot_id, receipt.id,
            Session(state), manager(receipt),
        )
        assert preview.geojson["features"][0]["properties"]["plantas"] == 1500
        assert not hasattr(preview, "object_key")
        try:
            get_gis_import_preview(
                "org-gis", receipt.farm_id, uuid4(), receipt.id,
                Session(state), manager(receipt),
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("Vista previa de otro lote disponible")

        # Descubrimiento después de validar S3/SHA; sin preview y sin reclamos repetidos.
        multi = make_receipt(payload)
        stage(store, multi, payload)
        multi_state = State(multi)
        def discovery(source: Path, output_dir: Path, *, layer=None):
            assert layer is None
            assert sha256(source.read_bytes()).hexdigest() == multi.sha256
            return GISLayersPendingSelection(("plantas", "limites"))
        multi_worker = DBIPortalGISPreparationWorker(
            lambda: Session(multi_state), store, discovery, workspace_root=Path(root),
        )
        assert multi_worker.process_one(tenant_ref="otro-tenant") is None
        assert multi_worker.process_one(tenant_ref=multi.tenant_ref) == "needs_selection"
        assert multi.status == "needs_selection"
        assert multi.available_layers == ["plantas", "limites"]
        assert multi.attempt_count == 1 and multi.processing_ref is None
        assert multi_state.preview is None
        assert multi_worker.process_one(tenant_ref=multi.tenant_ref) is None
        assert list(Path(root).iterdir()) == []
        try:
            get_gis_import_preview("org-gis", multi.farm_id, multi.plot_id, multi.id,
                                   Session(multi_state), manager(multi))
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("Importación sin selección no debe tener preview")

        # Solo el worker posterior puede reclamar la selección MANAGE confirmada.
        multi.selected_layer = "limites"
        chosen_worker = DBIPortalGISPreparationWorker(
            lambda: Session(multi_state), store,
            converter(multi.sha256, expected_layer="limites"),
            workspace_root=Path(root),
        )
        assert chosen_worker.process_one(tenant_ref="otro-tenant") is None
        assert chosen_worker.process_one(tenant_ref=multi.tenant_ref) == "prepared"
        assert multi.status == "prepared" and multi.selected_layer == "limites"
        assert multi.attempt_count == 2 and multi.processing_ref is None
        assert multi_state.preview is not None
        assert chosen_worker.process_one(tenant_ref=multi.tenant_ref) is None
        assert list(Path(root).iterdir()) == []
        assert get_gis_import_preview(
            "org-gis", multi.farm_id, multi.plot_id, multi.id,
            Session(multi_state), manager(multi),
        ).feature_count == 1

        # El manifiesto debe identificar exactamente la capa elegida.
        wrong = make_receipt(payload)
        wrong.status, wrong.attempt_count = "needs_selection", 1
        wrong.available_layers, wrong.selected_layer = ["plantas", "limites"], "plantas"
        stage(store, wrong, payload)
        wrong_state = State(wrong)
        wrong_worker = DBIPortalGISPreparationWorker(
            lambda: Session(wrong_state), store,
            converter(wrong.sha256, expected_layer="plantas", manifest_layer="limites"),
            workspace_root=Path(root),
        )
        assert wrong_worker.process_one(tenant_ref=wrong.tenant_ref) == "failed"
        assert wrong_state.preview is None and wrong.status == "failed"

        # Fencing: si la selección cambia durante el procesamiento, no se guarda preview.
        raced = make_receipt(payload)
        raced.status, raced.attempt_count = "needs_selection", 1
        raced.available_layers, raced.selected_layer = ["plantas", "limites"], "plantas"
        stage(store, raced, payload)
        race_state = State(raced)
        race_worker = DBIPortalGISPreparationWorker(
            lambda: Session(race_state), store,
            converter(raced.sha256, expected_layer="plantas"),
            workspace_root=Path(root),
        )
        claim = race_worker.claim_one(tenant_ref=raced.tenant_ref)
        assert claim and claim.selected_layer == "plantas"
        preview_result = race_worker._prepare(claim)
        raced.selected_layer = "limites"
        assert race_worker._complete(claim, preview_result) is False
        assert race_state.preview is None and raced.status == "processing"

        # Se rechazan opciones inválidas sin almacenarlas ni publicarlas.
        invalid = make_receipt(payload)
        stage(store, invalid, payload)
        invalid_state = State(invalid)
        invalid_worker = DBIPortalGISPreparationWorker(
            lambda: Session(invalid_state), store,
            lambda source, dest, *, layer=None: GISLayersPendingSelection(("same", "same")),
            workspace_root=Path(root),
        )
        assert invalid_worker.process_one(tenant_ref=invalid.tenant_ref) == "failed"
        assert invalid.available_layers is None and invalid_state.preview is None

        broken = make_receipt(payload)
        broken_state = State(broken)
        invalid_worker = DBIPortalGISPreparationWorker(
            lambda: Session(broken_state), store, converter(broken.sha256, corrupt=True),
            workspace_root=Path(root),
        )
        # No existe un original privado para este segundo import_id.
        assert invalid_worker.process_one(tenant_ref=broken.tenant_ref) == "failed"
        assert broken.status == "failed"
        assert broken_state.preview is None

    print("Preparación GIS: claims privados, SHA, manifiestos, fencing y vista previa autorizada OK.")


if __name__ == "__main__":
    run()
