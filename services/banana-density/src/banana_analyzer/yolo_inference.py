from __future__ import annotations

import csv
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import torch
import ultralytics
from ultralytics import YOLO


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"

DEFAULT_CONFIDENCE = 0.40
DEFAULT_IOU = 0.70
DEFAULT_IMAGE_SIZE = 640
DEFAULT_MAX_DETECTIONS = 1000


@dataclass
class YoloInferenceResult:
    """Resultado estructurado de la inferencia YOLO."""

    success: bool
    started_at: str
    finished_at: str | None
    tiles_directory: str
    model_path: str
    requested_device: str
    selected_device: str | None = None
    output_directory: str | None = None
    detections_csv: str | None = None
    failed_tiles_csv: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def bytes_to_mib(value: int | float) -> float:
    """Convierte bytes a MiB."""

    return round(float(value) / (1024**2), 3)


def validate_inference_parameters(
    confidence: float,
    iou: float,
    image_size: int,
    max_detections: int,
    limit: int | None,
) -> list[str]:
    """Valida los parámetros utilizados por YOLO."""

    errors: list[str] = []

    if not 0.0 <= confidence <= 1.0:
        errors.append(
            "La confianza debe encontrarse entre 0 y 1."
        )

    if not 0.0 <= iou <= 1.0:
        errors.append(
            "El IoU debe encontrarse entre 0 y 1."
        )

    if image_size <= 0:
        errors.append(
            "El tamaño de inferencia debe ser mayor que cero."
        )

    if image_size % 32 != 0:
        errors.append(
            "El tamaño de inferencia debe ser múltiplo de 32."
        )

    if max_detections <= 0:
        errors.append(
            "El número máximo de detecciones debe ser mayor que cero."
        )

    if limit is not None and limit <= 0:
        errors.append(
            "El límite de tiles debe ser mayor que cero."
        )

    return errors


def calculate_sha256(file_path: Path) -> str:
    """Calcula el hash SHA-256 de un archivo."""

    digest = hashlib.sha256()

    with file_path.open("rb") as file:
        while True:
            block = file.read(1024 * 1024)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def resolve_device(
    requested_device: str,
) -> tuple[str | int, str]:
    """
    Determina el dispositivo que se enviará a Ultralytics.

    Retorna:
        dispositivo para Ultralytics,
        nombre descriptivo.
    """

    normalized_device = str(
        requested_device
    ).strip().lower()

    if normalized_device in {"", "auto"}:
        if torch.cuda.is_available():
            return 0, "cuda:0"

        return "cpu", "cpu"

    if normalized_device == "cpu":
        return "cpu", "cpu"

    if normalized_device.isdigit():
        gpu_index = int(normalized_device)

        if not torch.cuda.is_available():
            raise RuntimeError(
                "Se solicitó una GPU, pero PyTorch no tiene "
                "CUDA disponible."
            )

        if gpu_index >= torch.cuda.device_count():
            raise RuntimeError(
                f"La GPU {gpu_index} no existe. "
                f"GPUs disponibles: {torch.cuda.device_count()}."
            )

        return gpu_index, f"cuda:{gpu_index}"

    if normalized_device.startswith("cuda"):
        if not torch.cuda.is_available():
            raise RuntimeError(
                "Se solicitó CUDA, pero PyTorch no tiene "
                "CUDA disponible."
            )

        parts = normalized_device.split(":", maxsplit=1)

        gpu_index = (
            int(parts[1])
            if len(parts) == 2
            else 0
        )

        if gpu_index >= torch.cuda.device_count():
            raise RuntimeError(
                f"La GPU {gpu_index} no existe."
            )

        return gpu_index, f"cuda:{gpu_index}"

    raise ValueError(
        "El dispositivo debe ser 'auto', 'cpu', "
        "'cuda', 'cuda:0' o un número de GPU."
    )


def list_geotiff_tiles(
    tiles_directory: Path,
) -> list[Path]:
    """Lista los tiles GeoTIFF en orden estable."""

    supported_extensions = {
        ".tif",
        ".tiff",
    }

    tiles = [
        file_path
        for file_path in tiles_directory.iterdir()
        if (
            file_path.is_file()
            and file_path.suffix.lower()
            in supported_extensions
        )
    ]

    return sorted(
        tiles,
        key=lambda path: path.name.lower(),
    )


def resolve_output_directory(
    tiles_directory: Path,
    output_dir: str | Path | None,
) -> Path:
    """
    Determina la carpeta de salida.

    Para:
        ejecución/02_tiles/geotiff

    devuelve:
        ejecución/03_detecciones_raw
    """

    if output_dir is not None:
        return Path(
            output_dir
        ).expanduser().resolve(strict=False)

    if (
        tiles_directory.name.lower() == "geotiff"
        and tiles_directory.parent.name
        == "02_tiles"
    ):
        run_directory = (
            tiles_directory.parent.parent
        )

        return (
            run_directory
            / "03_detecciones_raw"
        )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    return (
        PROJECT_ROOT
        / "runs"
        / (
            f"{tiles_directory.name}"
            f"_yolo_{timestamp}"
        )
        / "03_detecciones_raw"
    )


def prepare_output_directory(
    output_directory: Path,
) -> None:
    """Crea una salida sin sobrescribir resultados."""

    if (
        output_directory.exists()
        and any(output_directory.iterdir())
    ):
        raise FileExistsError(
            "La carpeta de detecciones ya contiene archivos. "
            "No se sobrescribirán resultados anteriores: "
            f"{output_directory}"
        )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )


def load_tile_for_yolo(
    tile_path: Path,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Lee un tile GeoTIFF y devuelve una imagen BGR uint8.

    Ultralytics recibe matrices NumPy con el orden utilizado
    normalmente por OpenCV: BGR.
    """

    with rasterio.open(tile_path) as source:
        if source.count < 1:
            raise ValueError(
                "El tile no contiene bandas."
            )

        if any(
            np.dtype(data_type) != np.dtype(
                np.uint8
            )
            for data_type in source.dtypes
        ):
            raise ValueError(
                "El tile no utiliza uint8. "
                "La conversión radiométrica debe definirse "
                "antes de ejecutar YOLO."
            )

        if source.count >= 3:
            raster_array = source.read(
                indexes=[1, 2, 3]
            )
        else:
            single_band = source.read(1)

            raster_array = np.stack(
                [
                    single_band,
                    single_band,
                    single_band,
                ],
                axis=0,
            )

        image_rgb = np.moveaxis(
            raster_array,
            0,
            -1,
        )

        valid_mask = source.dataset_mask()

        image_rgb[
            valid_mask == 0
        ] = 0

        image_bgr = np.ascontiguousarray(
            image_rgb[:, :, ::-1]
        )

        metadata = {
            "width": source.width,
            "height": source.height,
            "bands": source.count,
            "data_types": list(
                source.dtypes
            ),
            "crs": (
                source.crs.to_string()
                if source.crs is not None
                else None
            ),
        }

    return image_bgr, metadata


def get_class_name(
    names: Any,
    class_id: int,
) -> str:
    """Obtiene el nombre de una clase YOLO."""

    if isinstance(names, dict):
        return str(
            names.get(
                class_id,
                class_id,
            )
        )

    if (
        isinstance(names, (list, tuple))
        and 0 <= class_id < len(names)
    ):
        return str(names[class_id])

    return str(class_id)


def create_detection_row(
    detection_id: str,
    tile_path: Path,
    local_index: int,
    class_id: int,
    class_name: str,
    confidence: float,
    coordinates: np.ndarray,
    tile_width: int,
    tile_height: int,
) -> dict[str, Any]:
    """Construye una fila de detección cruda."""

    x_min, y_min, x_max, y_max = [
        float(value)
        for value in coordinates
    ]

    center_x = (
        x_min + x_max
    ) / 2.0

    center_y = (
        y_min + y_max
    ) / 2.0

    width = x_max - x_min
    height = y_max - y_min

    return {
        "detection_id": detection_id,
        "tile_id": tile_path.stem,
        "tile_file": tile_path.name,
        "tile_detection_index": (
            local_index
        ),
        "class_id": class_id,
        "class_name": class_name,
        "confidence": round(
            confidence,
            8,
        ),
        "x_min_px": round(x_min, 6),
        "y_min_px": round(y_min, 6),
        "x_max_px": round(x_max, 6),
        "y_max_px": round(y_max, 6),
        "center_x_px": round(
            center_x,
            6,
        ),
        "center_y_px": round(
            center_y,
            6,
        ),
        "width_px": round(width, 6),
        "height_px": round(height, 6),
        "tile_width_px": tile_width,
        "tile_height_px": tile_height,
    }


def save_json_report(
    result: YoloInferenceResult,
    report_path: Path,
) -> Path:
    """Guarda el informe de inferencia."""

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.report_path = str(
        report_path
    )

    with report_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            asdict(result),
            file,
            ensure_ascii=False,
            indent=4,
        )

    return report_path


def run_yolo_on_tiles(
    tiles_directory: str | Path,
    model_path: str | Path,
    confidence: float = DEFAULT_CONFIDENCE,
    iou: float = DEFAULT_IOU,
    image_size: int = DEFAULT_IMAGE_SIZE,
    requested_device: str = "auto",
    max_detections: int = DEFAULT_MAX_DETECTIONS,
    output_dir: str | Path | None = None,
    limit: int | None = None,
) -> YoloInferenceResult:
    """
    Ejecuta YOLO sobre los tiles GeoTIFF.

    Las salidas se mantienen en coordenadas de píxel.
    """

    started_at = datetime.now().isoformat(
        timespec="seconds"
    )

    start_time = time.perf_counter()

    normalized_tiles_directory = Path(
        tiles_directory
    ).expanduser().resolve(strict=False)

    normalized_model_path = Path(
        model_path
    ).expanduser().resolve(strict=False)

    result = YoloInferenceResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        tiles_directory=str(
            normalized_tiles_directory
        ),
        model_path=str(
            normalized_model_path
        ),
        requested_device=str(
            requested_device
        ),
    )

    output_directory: Path | None = None

    result.errors.extend(
        validate_inference_parameters(
            confidence=confidence,
            iou=iou,
            image_size=image_size,
            max_detections=max_detections,
            limit=limit,
        )
    )

    if not normalized_tiles_directory.is_dir():
        result.errors.append(
            "La carpeta de tiles no existe."
        )

    if not normalized_model_path.is_file():
        result.errors.append(
            "El modelo indicado no existe."
        )

    if result.errors:
        result.finished_at = (
            datetime.now().isoformat(
                timespec="seconds"
            )
        )

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        save_json_report(
            result,
            GLOBAL_LOGS_DIRECTORY
            / f"yolo_error_{timestamp}.json",
        )

        return result

    try:
        tiles = list_geotiff_tiles(
            normalized_tiles_directory
        )

        if not tiles:
            raise FileNotFoundError(
                "No se encontraron tiles .tif o .tiff."
            )

        total_available_tiles = len(tiles)

        if limit is not None:
            tiles = tiles[:limit]

        output_directory = (
            resolve_output_directory(
                tiles_directory=(
                    normalized_tiles_directory
                ),
                output_dir=output_dir,
            )
        )

        prepare_output_directory(
            output_directory
        )

        selected_device, device_name = (
            resolve_device(
                requested_device
            )
        )

        result.selected_device = device_name
        result.output_directory = str(
            output_directory
        )

        detections_csv_path = (
            output_directory
            / "detections_raw.csv"
        )

        failed_tiles_csv_path = (
            output_directory
            / "failed_tiles.csv"
        )

        result.detections_csv = str(
            detections_csv_path
        )

        model_hash = calculate_sha256(
            normalized_model_path
        )

        model = YOLO(
            str(normalized_model_path)
        )

        detection_fields = [
            "detection_id",
            "tile_id",
            "tile_file",
            "tile_detection_index",
            "class_id",
            "class_name",
            "confidence",
            "x_min_px",
            "y_min_px",
            "x_max_px",
            "y_max_px",
            "center_x_px",
            "center_y_px",
            "width_px",
            "height_px",
            "tile_width_px",
            "tile_height_px",
        ]

        failed_tiles: list[
            dict[str, str]
        ] = []

        processed_tiles = 0
        tiles_with_detections = 0
        tiles_without_detections = 0
        total_detections = 0

        speed_totals = {
            "preprocess_ms": 0.0,
            "inference_ms": 0.0,
            "postprocess_ms": 0.0,
        }

        with detections_csv_path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as detections_file:
            writer = csv.DictWriter(
                detections_file,
                fieldnames=detection_fields,
            )

            writer.writeheader()

            for tile_number, tile_path in enumerate(
                tiles,
                start=1,
            ):
                try:
                    image, tile_metadata = (
                        load_tile_for_yolo(
                            tile_path
                        )
                    )

                    predictions = model.predict(
                        source=image,
                        imgsz=image_size,
                        conf=confidence,
                        iou=iou,
                        device=selected_device,
                        max_det=max_detections,
                        save=False,
                        verbose=False,
                    )

                    if len(predictions) != 1:
                        raise RuntimeError(
                            "YOLO no devolvió exactamente "
                            "un resultado para el tile."
                        )

                    prediction = predictions[0]
                    boxes = prediction.boxes

                    speed = (
                        prediction.speed
                        if prediction.speed
                        else {}
                    )

                    speed_totals[
                        "preprocess_ms"
                    ] += float(
                        speed.get(
                            "preprocess",
                            0.0,
                        )
                    )

                    speed_totals[
                        "inference_ms"
                    ] += float(
                        speed.get(
                            "inference",
                            0.0,
                        )
                    )

                    speed_totals[
                        "postprocess_ms"
                    ] += float(
                        speed.get(
                            "postprocess",
                            0.0,
                        )
                    )

                    processed_tiles += 1

                    if (
                        boxes is None
                        or len(boxes) == 0
                    ):
                        tiles_without_detections += 1
                        continue

                    tiles_with_detections += 1

                    xyxy_array = (
                        boxes.xyxy
                        .detach()
                        .cpu()
                        .numpy()
                    )

                    confidence_array = (
                        boxes.conf
                        .detach()
                        .cpu()
                        .numpy()
                    )

                    class_array = (
                        boxes.cls
                        .detach()
                        .cpu()
                        .numpy()
                        .astype(int)
                    )

                    for local_index, (
                        coordinates,
                        detection_confidence,
                        class_id,
                    ) in enumerate(
                        zip(
                            xyxy_array,
                            confidence_array,
                            class_array,
                            strict=True,
                        ),
                        start=1,
                    ):
                        total_detections += 1

                        detection_id = (
                            f"det_"
                            f"{total_detections:09d}"
                        )

                        class_name = (
                            get_class_name(
                                prediction.names,
                                int(class_id),
                            )
                        )

                        writer.writerow(
                            create_detection_row(
                                detection_id=(
                                    detection_id
                                ),
                                tile_path=tile_path,
                                local_index=(
                                    local_index
                                ),
                                class_id=int(
                                    class_id
                                ),
                                class_name=(
                                    class_name
                                ),
                                confidence=float(
                                    detection_confidence
                                ),
                                coordinates=(
                                    coordinates
                                ),
                                tile_width=int(
                                    tile_metadata[
                                        "width"
                                    ]
                                ),
                                tile_height=int(
                                    tile_metadata[
                                        "height"
                                    ]
                                ),
                            )
                        )

                    print(
                        f"[{tile_number}/{len(tiles)}] "
                        f"{tile_path.name}: "
                        f"{len(boxes)} detecciones"
                    )

                except Exception as tile_error:
                    failed_tiles.append(
                        {
                            "tile_file": (
                                tile_path.name
                            ),
                            "error_type": (
                                type(
                                    tile_error
                                ).__name__
                            ),
                            "error_message": str(
                                tile_error
                            ),
                        }
                    )

                    print(
                        f"[{tile_number}/{len(tiles)}] "
                        f"ERROR: {tile_path.name}"
                    )

        if failed_tiles:
            result.failed_tiles_csv = str(
                failed_tiles_csv_path
            )

            with failed_tiles_csv_path.open(
                "w",
                newline="",
                encoding="utf-8-sig",
            ) as failed_file:
                failed_writer = csv.DictWriter(
                    failed_file,
                    fieldnames=[
                        "tile_file",
                        "error_type",
                        "error_message",
                    ],
                )

                failed_writer.writeheader()
                failed_writer.writerows(
                    failed_tiles
                )

        elapsed_seconds = round(
            time.perf_counter() - start_time,
            3,
        )

        average_speed: dict[
            str,
            float,
        ] = {}

        if processed_tiles > 0:
            average_speed = {
                key: round(
                    value / processed_tiles,
                    3,
                )
                for key, value
                in speed_totals.items()
            }

        result.metadata = {
            "model": {
                "name": (
                    normalized_model_path.name
                ),
                "size_mib": bytes_to_mib(
                    normalized_model_path
                    .stat()
                    .st_size
                ),
                "sha256": model_hash,
            },
            "software": {
                "ultralytics": (
                    ultralytics.__version__
                ),
                "torch": torch.__version__,
            },
            "parameters": {
                "confidence": confidence,
                "iou": iou,
                "image_size": image_size,
                "max_detections": (
                    max_detections
                ),
                "requested_device": (
                    requested_device
                ),
                "selected_device": (
                    device_name
                ),
                "limit": limit,
            },
            "tiles": {
                "available": (
                    total_available_tiles
                ),
                "selected": len(tiles),
                "processed": processed_tiles,
                "failed": len(
                    failed_tiles
                ),
                "with_detections": (
                    tiles_with_detections
                ),
                "without_detections": (
                    tiles_without_detections
                ),
            },
            "detections": {
                "total_raw": (
                    total_detections
                ),
            },
            "average_speed_per_tile": (
                average_speed
            ),
            "elapsed_seconds": (
                elapsed_seconds
            ),
            "partial_results": bool(
                failed_tiles
            ),
        }

        if processed_tiles == 0:
            result.errors.append(
                "No se procesó correctamente ningún tile."
            )

        if failed_tiles:
            result.errors.append(
                f"{len(failed_tiles)} tiles "
                "no pudieron procesarse. "
                "Los resultados son parciales."
            )

        result.success = (
            processed_tiles > 0
            and not failed_tiles
        )

    except Exception as error:
        result.errors.append(
            "No fue posible ejecutar la inferencia: "
            f"{type(error).__name__}: {error}"
        )

    result.finished_at = (
        datetime.now().isoformat(
            timespec="seconds"
        )
    )

    if output_directory is not None:
        report_path = (
            output_directory
            / "inference_report.json"
        )
    else:
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        report_path = (
            GLOBAL_LOGS_DIRECTORY
            / f"yolo_error_{timestamp}.json"
        )

    save_json_report(
        result=result,
        report_path=report_path,
    )

    return result


def print_inference_summary(
    result: YoloInferenceResult,
) -> None:
    """Muestra el resultado en la terminal."""

    print("=" * 72)
    print("INFERENCIA YOLO SOBRE TILES")
    print("=" * 72)

    print(
        f"Tiles: {result.tiles_directory}"
    )

    print(
        f"Modelo: {result.model_path}"
    )

    print(
        "Dispositivo: "
        f"{result.selected_device or 'NO RESUELTO'}"
    )

    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        tiles = result.metadata["tiles"]
        detections = result.metadata[
            "detections"
        ]

        print(
            "Tiles seleccionados: "
            f"{tiles['selected']}"
        )

        print(
            "Tiles procesados: "
            f"{tiles['processed']}"
        )

        print(
            "Tiles con detecciones: "
            f"{tiles['with_detections']}"
        )

        print(
            "Tiles sin detecciones: "
            f"{tiles['without_detections']}"
        )

        print(
            "Detecciones crudas: "
            f"{detections['total_raw']}"
        )

        print(
            "Tiempo total: "
            f"{result.metadata['elapsed_seconds']} "
            "segundos"
        )

    if result.detections_csv:
        print(
            "CSV de detecciones: "
            f"{result.detections_csv}"
        )

    if result.errors:
        print("\nERRORES:")

        for error in result.errors:
            print(f"  - {error}")

    if result.warnings:
        print("\nADVERTENCIAS:")

        for warning in result.warnings:
            print(f"  - {warning}")

    if result.report_path:
        print(
            "\nInforme: "
            f"{result.report_path}"
        )

    print("=" * 72)


def run_yolo_inference(
    tiles_directory: str | Path,
    model_path: str | Path,
    confidence: float = DEFAULT_CONFIDENCE,
    iou: float = DEFAULT_IOU,
    image_size: int = DEFAULT_IMAGE_SIZE,
    requested_device: str = "auto",
    max_detections: int = DEFAULT_MAX_DETECTIONS,
    output_dir: str | Path | None = None,
    limit: int | None = None,
) -> int:
    """Ejecuta YOLO desde main.py."""

    result = run_yolo_on_tiles(
        tiles_directory=tiles_directory,
        model_path=model_path,
        confidence=confidence,
        iou=iou,
        image_size=image_size,
        requested_device=requested_device,
        max_detections=max_detections,
        output_dir=output_dir,
        limit=limit,
    )

    print_inference_summary(result)

    return 0 if result.success else 1