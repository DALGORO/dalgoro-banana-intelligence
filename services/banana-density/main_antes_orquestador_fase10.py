from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_DIRECTORY = PROJECT_ROOT / "src"

if str(SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIRECTORY))


from banana_analyzer.system_check import run_system_check
from banana_analyzer.validation import run_raster_validation

from banana_analyzer.excel_boundary import run_boundary_validation

from banana_analyzer.raster_clipping import (
    run_raster_clipping,
)

from banana_analyzer.tiling import (
    run_tile_generation,
)

from banana_analyzer.yolo_inference import (
    run_yolo_inference,
)

from banana_analyzer.georeferencing import (
    run_detection_georeferencing,
)

from banana_analyzer.vector_outputs import (
    run_vector_export,
)

from banana_analyzer.deduplication import (
    run_deduplication,
)

from banana_analyzer.statistics import (
    run_spatial_statistics,
)

from banana_analyzer.spatial_pattern_analysis import (
    run_spatial_pattern_analysis,
)

from banana_analyzer.hex_density import (
    run_hex_density,
)

from banana_analyzer.planting_opportunities import (
    run_planting_opportunities,
)

from banana_analyzer.operational_priority import (
    run_operational_priority,
)

from banana_analyzer.kde_density_map import (
    run_kde_density_map,
)

from banana_analyzer.cartographic_package import (
    run_cartographic_package,
)

from banana_analyzer.technical_report import (
    run_technical_report,
)

def build_argument_parser() -> argparse.ArgumentParser:
    """Construye la interfaz de comandos de la aplicación."""

    parser = argparse.ArgumentParser(
        prog="banana-analyzer",
        description=(
            "Plataforma para análisis automatizado de "
            "plantaciones de banano mediante ortofotos."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="operaciones disponibles",
    )

    subparsers.add_parser(
        "system-check",
        help="Verifica el entorno técnico del sistema.",
    )

    raster_parser = subparsers.add_parser(
        "validate-raster",
        help=(
            "Valida una ortofoto sin modificar "
            "el archivo original."
        ),
    )

    raster_parser.add_argument(
        "raster_path",
        type=str,
        help="Ruta completa de la ortofoto.",
    )
    
    boundary_parser = subparsers.add_parser(
        "validate-boundary",
        help=(
            "Construye y valida el límite de la finca "
            "desde coordenadas almacenadas en Excel."
        ),
    )

    boundary_parser.add_argument(
        "excel_path",
        type=str,
        help="Ruta completa del archivo .xls o .xlsx.",
    )

    boundary_parser.add_argument(
        "raster_path",
        type=str,
        help="Ruta completa de la ortofoto.",
    )

    boundary_parser.add_argument(
        "--sheet",
        type=str,
        default="0",
        help=(
            "Nombre o posición de la hoja Excel. "
            "Por defecto se utiliza la primera hoja."
        ),
    )
    
    clip_parser = subparsers.add_parser(
        "clip-raster",
        help=(
            "Construye el límite desde Excel y "
            "recorta automáticamente la ortofoto."
        ),
    )

    clip_parser.add_argument(
        "excel_path",
        type=str,
        help=(
            "Ruta completa del archivo de "
            "coordenadas .xls o .xlsx."
        ),
    )

    clip_parser.add_argument(
        "raster_path",
        type=str,
        help="Ruta completa de la ortofoto.",
    )

    clip_parser.add_argument(
        "--sheet",
        type=str,
        default="0",
        help=(
            "Nombre o posición de la hoja Excel. "
            "Por defecto se utiliza la primera."
        ),
    )

    clip_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta principal donde se crearán "
            "las ejecuciones. Por defecto se usa "
            "automatizacion_banano\\runs."
        ),
    )
    
    tiles_parser = subparsers.add_parser(
        "generate-tiles",
        help=(
            "Genera tiles GeoTIFF georreferenciados "
            "desde el raster recortado."
        ),
    )

    tiles_parser.add_argument(
        "raster_path",
        type=str,
        help=(
            "Ruta completa del GeoTIFF recortado."
        ),
    )

    tiles_parser.add_argument(
        "--tile-size",
        type=int,
        default=640,
        help=(
            "Tamaño del tile en píxeles. "
            "Valor predeterminado: 640."
        ),
    )

    tiles_parser.add_argument(
        "--overlap",
        type=int,
        default=128,
        help=(
            "Solape entre tiles en píxeles. "
            "Valor predeterminado: 128."
        ),
    )

    tiles_parser.add_argument(
        "--min-valid-percent",
        type=float,
        default=0.0,
        help=(
            "Porcentaje mínimo de área válida. "
            "Con 0 se omiten solo tiles totalmente vacíos."
        ),
    )

    tiles_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Normalmente se detecta automáticamente."
        ),
    )
    
    yolo_parser = subparsers.add_parser(
        "run-yolo",
        help=(
            "Ejecuta el modelo YOLO sobre los "
            "tiles GeoTIFF."
        ),
    )

    yolo_parser.add_argument(
        "tiles_directory",
        type=str,
        help=(
            "Carpeta que contiene los tiles GeoTIFF."
        ),
    )

    yolo_parser.add_argument(
        "model_path",
        type=str,
        help=(
            "Ruta completa del modelo YOLO."
        ),
    )

    yolo_parser.add_argument(
        "--confidence",
        type=float,
        default=0.40,
        help=(
            "Umbral mínimo de confianza. "
            "Valor provisional: 0.40."
        ),
    )

    yolo_parser.add_argument(
        "--iou",
        type=float,
        default=0.70,
        help=(
            "Umbral IoU de NMS dentro de cada tile."
        ),
    )

    yolo_parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help=(
            "Tamaño de inferencia. "
            "Valor predeterminado: 640."
        ),
    )

    yolo_parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help=(
            "Dispositivo: auto, cpu, cuda o índice GPU."
        ),
    )

    yolo_parser.add_argument(
        "--max-det",
        type=int,
        default=1000,
        help=(
            "Número máximo de detecciones por tile."
        ),
    )

    yolo_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional."
        ),
    )

    yolo_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Procesa solamente los primeros N tiles. "
            "Se utiliza para pruebas controladas."
        ),
    )
    
    georef_parser = subparsers.add_parser(
        "georeference-detections",
        help=(
            "Convierte los centros YOLO desde "
            "píxeles a coordenadas geográficas."
        ),
    )

    georef_parser.add_argument(
        "detections_csv",
        type=str,
        help=(
            "Ruta completa de detections_raw.csv."
        ),
    )

    georef_parser.add_argument(
        "tiles_directory",
        type=str,
        help=(
            "Carpeta que contiene los tiles "
            "GeoTIFF utilizados por YOLO."
        ),
    )

    georef_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto se utiliza la carpeta "
            "del CSV de detecciones."
        ),
    )
    
    vector_parser = subparsers.add_parser(
        "export-gis",
        help=(
            "Exporta detecciones georreferenciadas "
            "a CSV y GeoPackage."
        ),
    )

    vector_parser.add_argument(
        "input_csv",
        type=str,
        help=(
            "CSV con las columnas coord_x, "
            "coord_y y epsg."
        ),
    )

    vector_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto se utiliza 05_gis."
        ),
    )

    vector_parser.add_argument(
        "--name-prefix",
        type=str,
        default="inventario_banano_raw",
        help=(
            "Nombre base del CSV y GeoPackage."
        ),
    )

    vector_parser.add_argument(
        "--layer-name",
        type=str,
        default="detecciones_raw",
        help=(
            "Nombre de la capa dentro del GeoPackage."
        ),
    )
    
    dedup_parser = subparsers.add_parser(
        "deduplicate-detections",
        help=(
            "Elimina detecciones duplicadas entre "
            "tiles superpuestos."
        ),
    )

    dedup_parser.add_argument(
        "input_csv",
        type=str,
        help=(
            "Ruta de "
            "detections_georeferenced_raw.csv."
        ),
    )

    dedup_parser.add_argument(
        "--distance",
        type=float,
        default=0.50,
        help=(
            "Distancia máxima en metros para "
            "considerar dos detecciones duplicadas. "
            "Valor provisional: 0.50."
        ),
    )

    dedup_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto se utiliza "
            "04_detecciones_limpias."
        ),
    )
    
    statistics_parser = subparsers.add_parser(
        "calculate-statistics",
        help=(
            "Valida espacialmente el inventario "
            "y calcula superficie y densidad."
        ),
    )

    statistics_parser.add_argument(
        "clean_csv",
        type=str,
        help=(
            "Ruta de detections_deduplicated.csv."
        ),
    )

    statistics_parser.add_argument(
        "excel_path",
        type=str,
        help=(
            "Archivo Excel con las coordenadas "
            "del límite de la finca."
        ),
    )

    statistics_parser.add_argument(
        "raster_path",
        type=str,
        help=(
            "Ruta completa de la ortofoto original."
        ),
    )

    statistics_parser.add_argument(
        "--sheet",
        type=str,
        default="0",
        help=(
            "Nombre o posición de la hoja Excel."
        ),
    )

    statistics_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto se utiliza 05_gis."
        ),
    )
    
    spatial_pattern_parser = subparsers.add_parser(
        "analyze-spatial-pattern",
        help=(
            "Analiza vecinos cercanos, orientación, "
            "espaciamientos y parámetros cartográficos."
        ),
    )

    spatial_pattern_parser.add_argument(
        "inventory_gpkg",
        type=str,
        help=(
            "GeoPackage del inventario espacialmente "
            "validado."
        ),
    )

    spatial_pattern_parser.add_argument(
        "boundary_gpkg",
        type=str,
        help=(
            "GeoPackage que contiene el límite "
            "del análisis."
        ),
    )

    spatial_pattern_parser.add_argument(
        "--inventory-layer",
        type=str,
        default="plantas_banano_validas",
        help=(
            "Nombre de la capa de plantas dentro "
            "del GeoPackage."
        ),
    )

    spatial_pattern_parser.add_argument(
        "--boundary-layer",
        type=str,
        default="limite_analisis",
        help=(
            "Nombre de la capa de límite dentro "
            "del GeoPackage."
        ),
    )

    spatial_pattern_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Archivo YAML de configuración. "
            "Por defecto se utiliza "
            "config/spatial_analysis.yaml."
        ),
    )

    spatial_pattern_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto se crea "
            "05_gis/analisis_espacial."
        ),
    )
    
    hex_density_parser = subparsers.add_parser(
        "generate-hex-density",
        help=(
            "Genera el mapa operativo de densidad "
            "por hexágonos."
        ),
    )

    hex_density_parser.add_argument(
        "inventory_gpkg",
        type=str,
        help=(
            "GeoPackage del inventario espacialmente "
            "validado."
        ),
    )

    hex_density_parser.add_argument(
        "boundary_gpkg",
        type=str,
        help=(
            "GeoPackage que contiene el límite "
            "del análisis."
        ),
    )

    hex_density_parser.add_argument(
        "--inventory-layer",
        type=str,
        default="plantas_banano_validas",
        help=(
            "Nombre de la capa de plantas dentro "
            "del GeoPackage."
        ),
    )

    hex_density_parser.add_argument(
        "--boundary-layer",
        type=str,
        default="limite_analisis",
        help=(
            "Nombre de la capa de límite dentro "
            "del GeoPackage."
        ),
    )

    hex_density_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Archivo YAML de configuración. "
            "Por defecto se utiliza "
            "config/spatial_analysis.yaml."
        ),
    )

    hex_density_parser.add_argument(
        "--reference-density",
        type=float,
        default=None,
        help=(
            "Densidad objetivo manual en plantas "
            "por hectárea. Si se omite, se calcula "
            "automáticamente."
        ),
    )

    hex_density_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto se crea "
            "05_gis/densidad_hexagonal."
        ),
    )
    
    opportunities_parser = subparsers.add_parser(
        "detect-planting-opportunities",
        help=(
            "Identifica espacios geométricos que podrían "
            "admitir plantas según una densidad objetivo."
        ),
    )

    opportunities_parser.add_argument(
        "inventory_gpkg",
        type=str,
        help=(
            "GeoPackage del inventario de plantas "
            "espacialmente validado."
        ),
    )

    opportunities_parser.add_argument(
        "boundary_gpkg",
        type=str,
        help=(
            "GeoPackage que contiene el límite "
            "del área analizada."
        ),
    )

    opportunities_parser.add_argument(
        "--target-density",
        type=float,
        required=True,
        help=(
            "Densidad objetivo establecida por el productor, "
            "expresada en plantas por hectárea."
        ),
    )

    opportunities_parser.add_argument(
        "--inventory-layer",
        type=str,
        default="plantas_banano_validas",
        help=(
            "Nombre de la capa de plantas dentro "
            "del GeoPackage."
        ),
    )

    opportunities_parser.add_argument(
        "--boundary-layer",
        type=str,
        default="limite_analisis",
        help=(
            "Nombre de la capa de límite dentro "
            "del GeoPackage."
        ),
    )

    opportunities_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Archivo YAML de configuración. "
            "Por defecto utiliza "
            "config/spatial_analysis.yaml."
        ),
    )

    opportunities_parser.add_argument(
        "--exclusions-gpkg",
        type=str,
        default=None,
        help=(
            "GeoPackage opcional con vías, canales, "
            "infraestructura u otras exclusiones."
        ),
    )

    opportunities_parser.add_argument(
        "--exclusions-layer",
        type=str,
        default=None,
        help=(
            "Nombre de la capa de exclusiones. "
            "Se requiere cuando se proporciona "
            "--exclusions-gpkg."
        ),
    )

    opportunities_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto se crea una carpeta "
            "según la densidad objetivo."
        ),
    )
    
    priority_parser = subparsers.add_parser(
        "prioritize-planting-opportunities",
        help=(
            "Combina candidatos geométricos y déficit "
            "hexagonal para priorizar inspecciones."
        ),
    )

    priority_parser.add_argument(
        "hex_density_gpkg",
        type=str,
        help=(
            "GeoPackage de densidad hexagonal generado "
            "con la densidad objetivo del productor."
        ),
    )

    priority_parser.add_argument(
        "candidates_gpkg",
        type=str,
        help=(
            "GeoPackage que contiene los candidatos "
            "geométricos de siembra."
        ),
    )

    priority_parser.add_argument(
        "opportunities_gpkg",
        type=str,
        help=(
            "GeoPackage que contiene las zonas "
            "de oportunidad de siembra."
        ),
    )

    priority_parser.add_argument(
        "--target-density",
        type=float,
        required=True,
        help=(
            "Densidad objetivo del productor, "
            "expresada en plantas por hectárea."
        ),
    )

    priority_parser.add_argument(
        "--hex-layer",
        type=str,
        default="densidad_hexagonal",
        help=(
            "Nombre de la capa hexagonal."
        ),
    )

    priority_parser.add_argument(
        "--candidates-layer",
        type=str,
        default="candidatos_siembra",
        help=(
            "Nombre de la capa de candidatos."
        ),
    )

    priority_parser.add_argument(
        "--opportunities-layer",
        type=str,
        default="zonas_oportunidad_siembra",
        help=(
            "Nombre de la capa de zonas de oportunidad."
        ),
    )

    priority_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Archivo YAML de configuración. "
            "Por defecto utiliza "
            "config/spatial_analysis.yaml."
        ),
    )

    priority_parser.add_argument(
        "--exclusions-gpkg",
        type=str,
        default=None,
        help=(
            "GeoPackage opcional con vías, canales, "
            "infraestructura o áreas no cultivables."
        ),
    )

    priority_parser.add_argument(
        "--exclusions-layer",
        type=str,
        default=None,
        help=(
            "Nombre de la capa de exclusiones."
        ),
    )

    priority_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto se crea una carpeta según "
            "la densidad objetivo."
        ),
    )
    
    kde_parser = subparsers.add_parser(
        "generate-kde-density",
        help=(
            "Genera un mapa continuo KDE de densidad "
            "respecto del objetivo del productor."
        ),
    )

    kde_parser.add_argument(
        "inventory_gpkg",
        type=str,
        help=(
            "GeoPackage del inventario de plantas "
            "espacialmente validado."
        ),
    )

    kde_parser.add_argument(
        "boundary_gpkg",
        type=str,
        help=(
            "GeoPackage que contiene el límite "
            "del área analizada."
        ),
    )

    kde_parser.add_argument(
        "--target-density",
        type=float,
        required=True,
        help=(
            "Densidad objetivo establecida por el "
            "productor, en plantas por hectárea."
        ),
    )

    kde_parser.add_argument(
        "--inventory-layer",
        type=str,
        default="plantas_banano_validas",
        help=(
            "Nombre de la capa de plantas dentro "
            "del inventario GeoPackage."
        ),
    )

    kde_parser.add_argument(
        "--boundary-layer",
        type=str,
        default="limite_analisis",
        help=(
            "Nombre de la capa de límite dentro "
            "del GeoPackage."
        ),
    )

    kde_parser.add_argument(
        "--spatial-report",
        type=str,
        default=None,
        help=(
            "Ruta opcional de "
            "analisis_patron_espacial.json. "
            "Si se omite, se busca automáticamente."
        ),
    )

    kde_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Archivo YAML de configuración. "
            "Por defecto utiliza "
            "config/spatial_analysis.yaml."
        ),
    )

    kde_parser.add_argument(
        "--radius",
        type=float,
        default=None,
        help=(
            "Radio KDE manual en metros. "
            "Si se omite, se utiliza el radio "
            "recomendado por el análisis espacial."
        ),
    )

    kde_parser.add_argument(
        "--pixel-size",
        type=float,
        default=None,
        help=(
            "Tamaño de píxel manual en metros. "
            "Por defecto se utiliza 0.50 m."
        ),
    )

    kde_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto se crea una carpeta "
            "según la densidad objetivo."
        ),
    )
    
    cartography_parser = subparsers.add_parser(
        "generate-cartographic-package",
        help=(
            "Genera mapas finales a partir de los "
            "resultados GIS del análisis."
        ),
    )

    cartography_parser.add_argument(
        "run_directory",
        type=str,
        help=(
            "Carpeta principal de la ejecución "
            "dentro de runs."
        ),
    )

    cartography_parser.add_argument(
        "--target-density",
        type=float,
        required=True,
        help=(
            "Densidad objetivo del productor, "
            "expresada en plantas por hectárea."
        ),
    )

    cartography_parser.add_argument(
        "--farm-name",
        type=str,
        required=True,
        help=(
            "Nombre de la finca o lote que aparecerá "
            "en los mapas."
        ),
    )

    cartography_parser.add_argument(
        "--producer",
        type=str,
        default="",
        help=(
            "Nombre del productor o empresa."
        ),
    )

    cartography_parser.add_argument(
        "--author",
        type=str,
        default=(
            "Ing. Darwin A. González Romero"
        ),
        help=(
            "Autor responsable que aparecerá "
            "en los mapas."
        ),
    )

    cartography_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Archivo YAML cartográfico. "
            "Por defecto utiliza "
            "config/cartography.yaml."
        ),
    )

    cartography_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto utiliza "
            "06_mapas/paquete_cartografico_<densidad>."
        ),
    )
    
    report_parser = subparsers.add_parser(
        "generate-technical-report",
        help=(
            "Genera el informe técnico PDF a partir "
            "de los resultados y mapas del análisis."
        ),
    )

    report_parser.add_argument(
        "run_directory",
        type=str,
        help=(
            "Carpeta principal de la ejecución "
            "dentro de runs."
        ),
    )

    report_parser.add_argument(
        "--target-density",
        type=float,
        required=True,
        help=(
            "Densidad objetivo del productor, "
            "expresada en plantas por hectárea."
        ),
    )

    report_parser.add_argument(
        "--farm-name",
        type=str,
        required=True,
        help=(
            "Nombre de la finca o lote."
        ),
    )

    report_parser.add_argument(
        "--producer",
        type=str,
        default="",
        help=(
            "Nombre del productor o empresa."
        ),
    )

    report_parser.add_argument(
        "--author",
        type=str,
        default=(
            "Ing. Darwin A. González Romero"
        ),
        help=(
            "Autor responsable del informe."
        ),
    )

    report_parser.add_argument(
        "--report-date",
        type=str,
        default=None,
        help=(
            "Fecha que aparecerá en el informe. "
            "Ejemplo: 16/07/2026. "
            "Si se omite, utiliza la fecha actual."
        ),
    )

    report_parser.add_argument(
        "--maps-dir",
        type=str,
        default=None,
        help=(
            "Carpeta opcional del paquete cartográfico. "
            "Si se omite, se localiza automáticamente."
        ),
    )

    report_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Archivo YAML del informe. "
            "Por defecto utiliza config/report.yaml."
        ),
    )

    report_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Carpeta de salida opcional. "
            "Por defecto utiliza 07_reporte."
        ),
    )

    return parser


def main() -> int:
    """Punto de entrada principal de la aplicación."""

    parser = build_argument_parser()
    arguments = parser.parse_args()

    if arguments.command is None:
        return run_system_check()

    if arguments.command == "system-check":
        return run_system_check()

    if arguments.command == "validate-raster":
        return run_raster_validation(
            arguments.raster_path
        )
        
    if arguments.command == "validate-boundary":
        return run_boundary_validation(
            excel_path=arguments.excel_path,
            raster_path=arguments.raster_path,
            sheet_reference=arguments.sheet,
        )
        
    if arguments.command == "clip-raster":
        return run_raster_clipping(
            excel_path=arguments.excel_path,
            raster_path=arguments.raster_path,
            sheet_reference=arguments.sheet,
            output_root=arguments.output_dir,
        )
        
    if arguments.command == "generate-tiles":
        return run_tile_generation(
            raster_path=arguments.raster_path,
            tile_size=arguments.tile_size,
            overlap=arguments.overlap,
            min_valid_percent=(
                arguments.min_valid_percent
            ),
            output_dir=arguments.output_dir,
        )
        
    if arguments.command == "run-yolo":
        return run_yolo_inference(
            tiles_directory=(
                arguments.tiles_directory
            ),
            model_path=arguments.model_path,
            confidence=arguments.confidence,
            iou=arguments.iou,
            image_size=arguments.imgsz,
            requested_device=arguments.device,
            max_detections=(
                arguments.max_det
            ),
            output_dir=arguments.output_dir,
            limit=arguments.limit,
        )
        
    if (
        arguments.command
        == "georeference-detections"
    ):
        return run_detection_georeferencing(
            detections_csv=(
                arguments.detections_csv
            ),
            tiles_directory=(
                arguments.tiles_directory
            ),
            output_dir=arguments.output_dir,
        )
        
    if arguments.command == "export-gis":
        return run_vector_export(
            input_csv=arguments.input_csv,
            output_dir=arguments.output_dir,
            name_prefix=arguments.name_prefix,
            layer_name=arguments.layer_name,
        )
        
    if (
        arguments.command
        == "deduplicate-detections"
    ):
        return run_deduplication(
            input_csv=arguments.input_csv,
            distance_threshold_m=(
                arguments.distance
            ),
            output_dir=arguments.output_dir,
        )
        
    if arguments.command == "calculate-statistics":
        return run_spatial_statistics(
            clean_csv=arguments.clean_csv,
            excel_path=arguments.excel_path,
            raster_path=arguments.raster_path,
            sheet_reference=arguments.sheet,
            output_dir=arguments.output_dir,
        )
        
    if (
        arguments.command
        == "analyze-spatial-pattern"
    ):
        return run_spatial_pattern_analysis(
            inventory_gpkg=(
                arguments.inventory_gpkg
            ),
            boundary_gpkg=(
                arguments.boundary_gpkg
            ),
            inventory_layer=(
                arguments.inventory_layer
            ),
            boundary_layer=(
                arguments.boundary_layer
            ),
            config_path=arguments.config,
            output_dir=arguments.output_dir,
        )
        
    if (
        arguments.command
        == "generate-hex-density"
    ):
        return run_hex_density(
            inventory_gpkg=(
                arguments.inventory_gpkg
            ),
            boundary_gpkg=(
                arguments.boundary_gpkg
            ),
            inventory_layer=(
                arguments.inventory_layer
            ),
            boundary_layer=(
                arguments.boundary_layer
            ),
            config_path=arguments.config,
            reference_density=(
                arguments.reference_density
            ),
            output_dir=arguments.output_dir,
        )
        
    if (
        arguments.command
        == "detect-planting-opportunities"
    ):
        return run_planting_opportunities(
            inventory_gpkg=(
                arguments.inventory_gpkg
            ),
            boundary_gpkg=(
                arguments.boundary_gpkg
            ),
            target_density_plants_ha=(
                arguments.target_density
            ),
            inventory_layer=(
                arguments.inventory_layer
            ),
            boundary_layer=(
                arguments.boundary_layer
            ),
            config_path=arguments.config,
            exclusions_gpkg=(
                arguments.exclusions_gpkg
            ),
            exclusions_layer=(
                arguments.exclusions_layer
            ),
            output_dir=arguments.output_dir,
        )
        
    if (
        arguments.command
        == "prioritize-planting-opportunities"
    ):
        return run_operational_priority(
            hex_density_gpkg=(
                arguments.hex_density_gpkg
            ),
            candidates_gpkg=(
                arguments.candidates_gpkg
            ),
            opportunities_gpkg=(
                arguments.opportunities_gpkg
            ),
            target_density_plants_ha=(
                arguments.target_density
            ),
            hex_layer=arguments.hex_layer,
            candidates_layer=(
                arguments.candidates_layer
            ),
            opportunities_layer=(
                arguments.opportunities_layer
            ),
            config_path=arguments.config,
            exclusions_gpkg=(
                arguments.exclusions_gpkg
            ),
            exclusions_layer=(
                arguments.exclusions_layer
            ),
            output_dir=arguments.output_dir,
        )
        
    if arguments.command == "generate-kde-density":
        return run_kde_density_map(
            inventory_gpkg=(
                arguments.inventory_gpkg
            ),
            boundary_gpkg=(
                arguments.boundary_gpkg
            ),
            target_density_plants_ha=(
                arguments.target_density
            ),
            inventory_layer=(
                arguments.inventory_layer
            ),
            boundary_layer=(
                arguments.boundary_layer
            ),
            spatial_report_json=(
                arguments.spatial_report
            ),
            config_path=arguments.config,
            radius_m=arguments.radius,
            pixel_size_m=(
                arguments.pixel_size
            ),
            output_dir=arguments.output_dir,
        )
        
    if (
        arguments.command
        == "generate-cartographic-package"
    ):
        return run_cartographic_package(
            run_directory=(
                arguments.run_directory
            ),
            target_density_plants_ha=(
                arguments.target_density
            ),
            farm_name=arguments.farm_name,
            producer=arguments.producer,
            author=arguments.author,
            config_path=arguments.config,
            output_dir=arguments.output_dir,
        )
        
    if (
        arguments.command
        == "generate-technical-report"
    ):
        return run_technical_report(
            run_directory=(
                arguments.run_directory
            ),
            target_density_plants_ha=(
                arguments.target_density
            ),
            farm_name=arguments.farm_name,
            producer=arguments.producer,
            author=arguments.author,
            report_date=(
                arguments.report_date
            ),
            maps_dir=arguments.maps_dir,
            config_path=arguments.config,
            output_dir=arguments.output_dir,
        )

    parser.print_help()

    return 1


if __name__ == "__main__":
    raise SystemExit(main())