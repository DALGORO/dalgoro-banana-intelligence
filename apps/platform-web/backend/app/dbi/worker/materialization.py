"""Workspace efímero y materialización streaming de recursos privados DBI."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.dbi.storage_contracts import DBIPrivateObjectStore
from app.dbi.storage_policy import DBIStoragePolicy
from app.dbi.worker.contracts import DBIWorkerConflict, ResolvedAnalysisPlan


@dataclass(frozen=True, slots=True)
class DBIWorkerWorkspace:
    root: Path
    inputs_dir: Path
    model_dir: Path
    config_dir: Path
    output_root: Path
    logs_dir: Path
    orthophoto_path: Path
    boundary_path: Path
    exclusions_path: Path | None
    model_path: Path
    pipeline_config_path: Path
    cancel_file: Path


_BOUNDARY_SUFFIX_BY_MIME = {
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


def _safe_remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _write_streaming(
    store: DBIPrivateObjectStore,
    *,
    metadata,
    destination: Path,
    progress: Callable[[int], None] | None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    if destination.exists():
        destination.unlink()
    try:
        with partial.open("wb") as handle:
            record = store.copy_to(
                metadata.address,
                handle,
                progress=progress,
            )
            handle.flush()
            os.fsync(handle.fileno())
        if record.metadata != metadata:
            raise DBIWorkerConflict("objeto materializado diverge de la identidad congelada.")
        partial.replace(destination)
    finally:
        if partial.exists():
            partial.unlink()


class DBIWorkerWorkspaceManager:
    """Crea un workspace aislado por tenant+attempt y lo limpia idempotentemente."""

    def __init__(self, root: str | Path) -> None:
        candidate = Path(root).expanduser().resolve(strict=False)
        if not candidate.is_absolute():
            raise ValueError("root del worker debe ser absoluto.")
        self._root = candidate

    def prepare(self, plan: ResolvedAnalysisPlan) -> DBIWorkerWorkspace:
        namespace = DBIStoragePolicy.tenant_namespace(plan.tenant_ref)
        attempt_root = self._root / namespace / str(plan.attempt_id)
        _safe_remove_tree(attempt_root)
        attempt_root.mkdir(parents=True, mode=0o700, exist_ok=False)

        inputs = attempt_root / "inputs"
        model = attempt_root / "model"
        config = attempt_root / "config"
        outputs = attempt_root / "runs"
        logs = attempt_root / "logs"
        for directory in (inputs, model, config, outputs, logs):
            directory.mkdir(parents=True, mode=0o700, exist_ok=False)

        boundary_suffix = _BOUNDARY_SUFFIX_BY_MIME.get(plan.boundary.metadata.content_type)
        if boundary_suffix is None:
            raise DBIWorkerConflict("formato de límite no ejecutable por el pipeline heredado.")
        exclusions_path = (
            inputs / "exclusions.gpkg" if plan.exclusions is not None else None
        )
        return DBIWorkerWorkspace(
            root=attempt_root,
            inputs_dir=inputs,
            model_dir=model,
            config_dir=config,
            output_root=outputs,
            logs_dir=logs,
            orthophoto_path=inputs / "orthophoto.tif",
            boundary_path=inputs / f"boundary{boundary_suffix}",
            exclusions_path=exclusions_path,
            model_path=model / "model.pt",
            pipeline_config_path=config / "pipeline.yaml",
            cancel_file=attempt_root / "cancel.requested",
        )

    def materialize(
        self,
        store: DBIPrivateObjectStore,
        *,
        plan: ResolvedAnalysisPlan,
        workspace: DBIWorkerWorkspace,
        progress: Callable[[int], None] | None = None,
    ) -> None:
        _write_streaming(
            store,
            metadata=plan.orthophoto.metadata,
            destination=workspace.orthophoto_path,
            progress=progress,
        )
        _write_streaming(
            store,
            metadata=plan.boundary.metadata,
            destination=workspace.boundary_path,
            progress=progress,
        )
        if plan.exclusions is not None:
            assert workspace.exclusions_path is not None
            _write_streaming(
                store,
                metadata=plan.exclusions.metadata,
                destination=workspace.exclusions_path,
                progress=progress,
            )
        _write_streaming(
            store,
            metadata=plan.model.metadata,
            destination=workspace.model_path,
            progress=progress,
        )

    def cleanup(self, workspace: DBIWorkerWorkspace) -> None:
        _safe_remove_tree(workspace.root)
