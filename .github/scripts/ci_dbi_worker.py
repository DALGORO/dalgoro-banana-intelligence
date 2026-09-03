"""Puerta offline de contratos, streaming y aislamiento para DBI-WORKER-001."""

from __future__ import annotations

import inspect
import sys
import tempfile
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.storage_contracts import (  # noqa: E402
    DBIStorageIntegrityError,
    DBIStoragePurpose,
    DBIStorageWriteRequest,
)
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402
from app.dbi.storage_policy import DBIStoragePolicy  # noqa: E402
from app.dbi.storage_s3 import DBIS3ObjectStore  # noqa: E402
from app.dbi.worker.contracts import (  # noqa: E402
    DBIWorkerConflict,
    MODEL_ARTIFACT_TENANT_REF,
    ResolvedAnalysisPlan,
    ResolvedModelArtifact,
    ResolvedPipelineConfig,
    ResolvedPrivateObject,
    WorkerProcessingEvidence,
)
from app.dbi.worker.materialization import (  # noqa: E402
    DBIWorkerWorkspaceManager,
)
from app.dbi.worker.pipeline_adapter import (  # noqa: E402
    AUTHOR,
    build_legacy_runtime_config,
)
from app.dbi.worker.resolution import _uuid_ref  # noqa: E402

TENANT = "tenant-ci-worker"
FARM_ID = UUID("81000000-0000-4000-8000-000000000001")
PLOT_ID = UUID("82000000-0000-4000-8000-000000000001")
JOB_ID = UUID("83000000-0000-4000-8000-000000000001")
ATTEMPT_ID = UUID("84000000-0000-4000-8000-000000000001")


def _put(store, *, tenant: str, purpose: DBIStoragePurpose, payload: bytes, content_type: str):
    object_id = uuid4()
    address = DBIStoragePolicy.build_address(
        tenant_ref=tenant,
        purpose=purpose,
        object_id=object_id,
    )
    metadata = DBIStoragePolicy.build_metadata(
        address=address,
        content_type=content_type,
        size_bytes=len(payload),
        sha256_hex=sha256(payload).hexdigest(),
    )
    store.put(DBIStorageWriteRequest(metadata=metadata), BytesIO(payload))
    return object_id, metadata


def _plan(store: DBIInMemoryObjectStore) -> tuple[ResolvedAnalysisPlan, dict[str, bytes]]:
    payloads = {
        "orthophoto": b"o" * (64 * 1024 * 3 + 777),
        "boundary": b"b" * 16_384,
        "model": b"m" * (64 * 1024 * 2 + 333),
    }
    ortho_id, ortho_meta = _put(
        store,
        tenant=TENANT,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        payload=payloads["orthophoto"],
        content_type="image/tiff",
    )
    boundary_id, boundary_meta = _put(
        store,
        tenant=TENANT,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        payload=payloads["boundary"],
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    model_id, model_meta = _put(
        store,
        tenant=MODEL_ARTIFACT_TENANT_REF,
        purpose=DBIStoragePurpose.MODEL_ARTIFACT,
        payload=payloads["model"],
        content_type="application/octet-stream",
    )
    plan = ResolvedAnalysisPlan(
        job_id=JOB_ID,
        attempt_id=ATTEMPT_ID,
        correlation_id="correlation-ci-worker",
        tenant_ref=TENANT,
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        farm_name="Finca CI",
        plot_name="Lote CI",
        orthophoto=ResolvedPrivateObject(
            object_id=ortho_id,
            kind="orthophoto",
            metadata=ortho_meta,
            crs="EPSG:32717",
        ),
        boundary=ResolvedPrivateObject(
            object_id=boundary_id,
            kind="boundary",
            metadata=boundary_meta,
        ),
        exclusions=None,
        model=ResolvedModelArtifact(
            model_family="banana_detection",
            model_version="banana_ci_v1",
            artifact_id=model_id,
            metadata=model_meta,
            input_contract_version="orthophoto_tiles_v1",
            output_contract_version="banana_detections_v1",
        ),
        pipeline=ResolvedPipelineConfig(
            model_family="banana_detection",
            config_version="pipeline_ci_v1",
            config_sha256="a" * 64,
            payload={
                "target_density_plants_ha": 1400,
                "tile_size": 640,
                "overlap": 128,
                "confidence": 0.4,
                "iou": 0.7,
            },
        ),
    )
    return plan, payloads


def validate_contracts_are_private_and_strict() -> None:
    store = DBIInMemoryObjectStore(max_object_size_bytes=1024 * 1024)
    plan, _ = _plan(store)
    assert "object_key" not in repr(plan.orthophoto)
    assert "target_density_plants_ha" not in repr(plan.pipeline)
    assert WorkerProcessingEvidence.model_config.get("frozen") is True
    assert MODEL_ARTIFACT_TENANT_REF == "dbi-model-registry"
    assert _uuid_ref(str(JOB_ID), field_name="job") == JOB_ID
    try:
        _uuid_ref("not-a-uuid", field_name="model.artifact_ref")
    except DBIWorkerConflict:
        pass
    else:
        raise AssertionError("artifact_ref no UUID debía rechazarse para ejecución.")


def validate_streaming_materialization() -> None:
    store = DBIInMemoryObjectStore(max_object_size_bytes=1024 * 1024)
    plan, payloads = _plan(store)
    progress: list[int] = []
    with tempfile.TemporaryDirectory() as temporary:
        manager = DBIWorkerWorkspaceManager(Path(temporary))
        workspace = manager.prepare(plan)
        manager.materialize(
            store,
            plan=plan,
            workspace=workspace,
            progress=progress.append,
        )
        assert workspace.orthophoto_path.read_bytes() == payloads["orthophoto"]
        assert workspace.boundary_path.read_bytes() == payloads["boundary"]
        assert workspace.model_path.read_bytes() == payloads["model"]
        assert len(progress) >= 7, "la prueba debe observar múltiples chunks"
        assert not list(workspace.root.rglob("*.partial"))
        manager.cleanup(workspace)
        assert not workspace.root.exists()


class _BrokenCopyStore:
    def copy_to(self, _address, destination, *, progress=None):
        destination.write(b"partial-corrupt")
        if progress is not None:
            progress(len(b"partial-corrupt"))
        raise DBIStorageIntegrityError("synthetic truncation")


def validate_partial_materialization_fails_closed() -> None:
    base = DBIInMemoryObjectStore(max_object_size_bytes=1024 * 1024)
    plan, _ = _plan(base)
    with tempfile.TemporaryDirectory() as temporary:
        manager = DBIWorkerWorkspaceManager(Path(temporary))
        workspace = manager.prepare(plan)
        try:
            manager.materialize(
                _BrokenCopyStore(),
                plan=plan,
                workspace=workspace,
            )
        except DBIStorageIntegrityError:
            pass
        else:
            raise AssertionError("materialización truncada debía fallar.")
        assert not workspace.orthophoto_path.exists()
        assert not workspace.orthophoto_path.with_suffix(".tif.partial").exists()


def validate_ephemeral_config_boundary() -> None:
    store = DBIInMemoryObjectStore(max_object_size_bytes=1024 * 1024)
    plan, _ = _plan(store)
    with tempfile.TemporaryDirectory() as temporary:
        workspace = DBIWorkerWorkspaceManager(Path(temporary)).prepare(plan)
        runtime = build_legacy_runtime_config(plan, workspace)
        analysis = runtime["analysis"]
        assert analysis["author"] == AUTHOR == "Ing. Darwin A. González Romero"
        assert analysis["orthophoto_path"] == str(workspace.orthophoto_path)
        assert analysis["model_path"] == str(workspace.model_path)
        assert runtime["parameters"]["yolo_confidence"] == 0.4
        assert runtime["parameters"]["yolo_iou"] == 0.7

        divergent = ResolvedPipelineConfig(
            model_family=plan.pipeline.model_family,
            config_version="bad",
            config_sha256="b" * 64,
            payload={
                "target_density_plants_ha": 1400,
                "model_path": "/forbidden/from/registry.pt",
            },
        )
        bad_plan = replace(plan, pipeline=divergent)
        try:
            build_legacy_runtime_config(bad_plan, workspace)
        except DBIWorkerConflict:
            pass
        else:
            raise AssertionError("rutas desde pipeline_config debían rechazarse.")


def validate_static_boundaries() -> None:
    worker_dir = BACKEND / "app" / "dbi" / "worker"
    repository_source = (worker_dir / "repository.py").read_text(encoding="utf-8").lower()
    service_source = (worker_dir / "service.py").read_text(encoding="utf-8").lower()
    adapter_source = (worker_dir / "pipeline_adapter.py").read_text(encoding="utf-8").lower()

    for forbidden in (".commit(", ".rollback(", "requests.", "boto3", "redis", "celery"):
        assert forbidden not in repository_source
    for forbidden in ("green api", "green-api", "sheets", "sam", "yolo-seg"):
        assert forbidden not in service_source
    for required in ("run-full-analysis", "--resume-run", "--from-stage", "--stop-after"):
        assert required in adapter_source
    assert "interfaz_banano" not in adapter_source

    streaming_source = inspect.getsource(DBIS3ObjectStore.copy_to).lower()
    assert "get_object" in streaming_source
    assert "sha256" in streaming_source
    assert "b\"\".join" not in streaming_source
    assert "chunks.append" not in streaming_source
    assert "max_object_size_bytes" not in streaming_source


def main() -> None:
    validate_contracts_are_private_and_strict()
    validate_streaming_materialization()
    validate_partial_materialization_fails_closed()
    validate_ephemeral_config_boundary()
    validate_static_boundaries()
    print("DBI-WORKER-001 offline aprobado: aislamiento, streaming y adapter seguros.")


if __name__ == "__main__":
    main()
