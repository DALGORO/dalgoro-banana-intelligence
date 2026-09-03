"""Selección, empaquetado y publicación idempotente de artefactos del Worker."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

from app.dbi.storage_contracts import (
    DBIPrivateObjectStore,
    DBIStoragePurpose,
    DBIStorageWriteRequest,
)
from app.dbi.storage_policy import DBIStoragePolicy
from app.dbi.worker.contracts import DBIWorkerConflict, ResolvedAnalysisPlan
from app.dbi.worker.materialization import DBIWorkerWorkspace
from app.schemas.dbi_analysis_jobs import ArtifactManifest, ArtifactRole, PipelineStage

_ARTIFACT_NAMESPACE = UUID("5a41f651-902d-4e61-83d0-1b777bf7a8c5")


@dataclass(frozen=True, slots=True)
class _ArtifactSource:
    role: ArtifactRole
    path: Path
    content_type: str
    stage: PipelineStage
    crs: str | None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DBIWorkerConflict("created_at de artefactos debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _single_file(root: Path, pattern: str, *, label: str) -> Path:
    matches = sorted(path for path in root.glob(pattern) if path.is_file())
    if len(matches) != 1:
        raise DBIWorkerConflict(f"se esperaba exactamente un artefacto {label}.")
    if matches[0].stat().st_size <= 0:
        raise DBIWorkerConflict(f"artefacto {label} está vacío.")
    return matches[0]


def _single_directory(root: Path, pattern: str, *, label: str) -> Path:
    matches = sorted(path for path in root.glob(pattern) if path.is_dir())
    if len(matches) != 1:
        raise DBIWorkerConflict(f"se esperaba exactamente un directorio {label}.")
    return matches[0]


def _deterministic_zip(source: Path, destination: Path) -> Path:
    temporary = destination.with_suffix(destination.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    if destination.exists():
        destination.unlink()
    files = sorted(path for path in source.rglob("*") if path.is_file())
    if not files:
        raise DBIWorkerConflict("paquete cartográfico no contiene archivos.")
    with zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for path in files:
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    temporary.replace(destination)
    return destination


def _sha_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    if size <= 0:
        raise DBIWorkerConflict("artefacto oficial no puede estar vacío.")
    return digest.hexdigest(), size


def collect_artifact_sources(
    *,
    plan: ResolvedAnalysisPlan,
    workspace: DBIWorkerWorkspace,
    run_directory: Path,
) -> list[_ArtifactSource]:
    gis = run_directory / "05_gis"
    maps = _single_directory(
        run_directory / "06_mapas",
        "paquete_cartografico_*",
        label="cartográfico",
    )
    report_dir = _single_directory(
        run_directory / "07_reporte",
        "informe_dalgoro_v2_*",
        label="de informe",
    )
    package_zip = _deterministic_zip(
        maps,
        workspace.root / "cartographic_package.zip",
    )
    return [
        _ArtifactSource(
            ArtifactRole.VALIDATED_INVENTORY,
            gis / "inventario_banano_validado.gpkg",
            "application/geopackage+sqlite3",
            PipelineStage.CALCULATE_STATISTICS,
            plan.orthophoto.crs,
        ),
        _ArtifactSource(
            ArtifactRole.ANALYSIS_BOUNDARY,
            gis / "limite_analisis.gpkg",
            "application/geopackage+sqlite3",
            PipelineStage.CALCULATE_STATISTICS,
            plan.orthophoto.crs,
        ),
        _ArtifactSource(
            ArtifactRole.HEX_DENSITY,
            _single_file(gis, "densidad_hexagonal_objetivo_*/densidad_hexagonal.gpkg", label="hex"),
            "application/geopackage+sqlite3",
            PipelineStage.GENERATE_HEX_DENSITY,
            plan.orthophoto.crs,
        ),
        _ArtifactSource(
            ArtifactRole.PLANTING_PRIORITY,
            _single_file(
                gis,
                "prioridad_operativa_*/candidatos_siembra_priorizados.gpkg",
                label="prioridad",
            ),
            "application/geopackage+sqlite3",
            PipelineStage.PRIORITIZE_PLANTING_OPPORTUNITIES,
            plan.orthophoto.crs,
        ),
        _ArtifactSource(
            ArtifactRole.KDE_DENSITY,
            _single_file(
                gis,
                "mapa_calor_kde_*/densidad_kde_corregida_plantas_ha.tif",
                label="KDE",
            ),
            "image/tiff",
            PipelineStage.GENERATE_KDE_DENSITY,
            plan.orthophoto.crs,
        ),
        _ArtifactSource(
            ArtifactRole.CARTOGRAPHIC_PACKAGE,
            package_zip,
            "application/zip",
            PipelineStage.GENERATE_CARTOGRAPHIC_PACKAGE,
            plan.orthophoto.crs,
        ),
        _ArtifactSource(
            ArtifactRole.TECHNICAL_REPORT,
            _single_file(report_dir, "informe_tecnico_*.pdf", label="informe PDF"),
            "application/pdf",
            PipelineStage.GENERATE_TECHNICAL_REPORT,
            None,
        ),
        _ArtifactSource(
            ArtifactRole.PIPELINE_STATE,
            run_directory / "estado_pipeline.json",
            "application/json",
            PipelineStage.GENERATE_TECHNICAL_REPORT,
            None,
        ),
        _ArtifactSource(
            ArtifactRole.PIPELINE_MANIFEST,
            run_directory / "manifiesto_pipeline.json",
            "application/json",
            PipelineStage.GENERATE_TECHNICAL_REPORT,
            None,
        ),
    ]


def publish_artifacts(
    store: DBIPrivateObjectStore,
    *,
    plan: ResolvedAnalysisPlan,
    workspace: DBIWorkerWorkspace,
    run_directory: Path,
    created_at: datetime,
) -> list[ArtifactManifest]:
    timestamp = _utc(created_at)
    manifests: list[ArtifactManifest] = []
    for source in collect_artifact_sources(
        plan=plan,
        workspace=workspace,
        run_directory=run_directory,
    ):
        if not source.path.is_file() or source.path.stat().st_size <= 0:
            raise DBIWorkerConflict(f"falta artefacto oficial {source.role.value}.")
        digest, size = _sha_size(source.path)
        artifact_id = uuid5(
            _ARTIFACT_NAMESPACE,
            f"dbi:worker:artifact:v1:{plan.attempt_id}:{source.role.value}",
        )
        address = DBIStoragePolicy.build_address(
            tenant_ref=plan.tenant_ref,
            purpose=DBIStoragePurpose.ANALYSIS_ARTIFACT,
            object_id=artifact_id,
        )
        metadata = DBIStoragePolicy.build_metadata(
            address=address,
            content_type=source.content_type,
            size_bytes=size,
            sha256_hex=digest,
        )
        with source.path.open("rb") as handle:
            persisted = store.put(DBIStorageWriteRequest(metadata=metadata), handle)
        if persisted.record.metadata != metadata:
            raise DBIWorkerConflict("artefacto privado persistido diverge del manifiesto.")
        manifests.append(
            ArtifactManifest(
                artifact_id=str(artifact_id),
                job_id=str(plan.job_id),
                role=source.role,
                object_key=address.object_key,
                content_type=source.content_type,
                size_bytes=size,
                sha256=digest,
                produced_by_stage=source.stage,
                crs=source.crs,
                created_at=timestamp,
            )
        )
    return manifests
