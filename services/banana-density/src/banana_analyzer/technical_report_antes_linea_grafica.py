from __future__ import annotations

import csv
import html
import json
import math
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yaml
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "report.yaml"
DEFAULT_AUTHOR = "Ing. Darwin A. González Romero"


@dataclass
class TechnicalReportResult:
    """Resultado estructurado de la generación del informe técnico."""

    success: bool
    started_at: str
    finished_at: str | None
    run_directory: str
    target_density_plants_ha: float
    farm_name: str
    producer: str
    author: str
    output_directory: str | None = None
    report_pdf: str | None = None
    summary_csv: str | None = None
    manifest_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def density_label(value: float) -> str:
    """Convierte una densidad en texto seguro para nombres de archivo."""

    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return str(numeric).replace(".", "_")


def sanitize_name(value: str) -> str:
    """Convierte un texto en un nombre de archivo seguro."""

    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", normalized)
    normalized = normalized.strip("_")
    return normalized or "informe"


def load_config(config_path: str | Path | None) -> tuple[Path, dict[str, Any]]:
    """Carga la configuración del informe."""

    resolved_path = (
        Path(config_path).expanduser().resolve(strict=False)
        if config_path is not None
        else DEFAULT_CONFIG_PATH
    )

    if not resolved_path.is_file():
        raise FileNotFoundError(
            f"No existe la configuración del informe: {resolved_path}"
        )

    with resolved_path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}

    if "report" not in loaded:
        raise ValueError(
            "La configuración debe contener la sección 'report'."
        )

    return resolved_path, loaded["report"]


def resolve_page_size(page_size_name: str) -> tuple[float, float]:
    """Resuelve el tamaño de página configurado."""

    normalized = str(page_size_name).strip().upper()

    if normalized == "A4":
        return A4
    if normalized == "A4_LANDSCAPE":
        return landscape(A4)
    if normalized == "LETTER":
        return letter
    if normalized == "LETTER_LANDSCAPE":
        return landscape(letter)

    raise ValueError(
        "page_size debe ser A4, A4_LANDSCAPE, LETTER o LETTER_LANDSCAPE."
    )


def read_single_row_csv(path: Path) -> dict[str, Any]:
    """Lee un CSV de resumen y devuelve su primera fila."""

    if not path.is_file():
        raise FileNotFoundError(f"No existe el archivo: {path}")

    table = pd.read_csv(path, encoding="utf-8-sig")

    if table.empty:
        raise ValueError(f"El archivo está vacío: {path}")

    row = table.iloc[0].to_dict()

    return {
        str(key): value.item() if hasattr(value, "item") else value
        for key, value in row.items()
    }


def find_latest_directory(base_directory: Path, pattern: str) -> Path | None:
    """Busca la carpeta más reciente que coincida con un patrón."""

    candidates = [
        path
        for path in base_directory.glob(pattern)
        if path.is_dir()
    ]

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def discover_inputs(
    run_directory: Path,
    target_density_plants_ha: float,
    maps_dir: str | Path | None,
) -> dict[str, Path | None]:
    """Localiza resúmenes y mapas de las fases anteriores."""

    density_text = density_label(target_density_plants_ha)
    gis_directory = run_directory / "05_gis"

    if maps_dir is not None:
        resolved_maps_directory = (
            Path(maps_dir).expanduser().resolve(strict=False)
        )
    else:
        exact_maps_directory = (
            run_directory
            / "06_mapas"
            / f"paquete_cartografico_{density_text}"
        )

        if exact_maps_directory.is_dir():
            resolved_maps_directory = exact_maps_directory
        else:
            resolved_maps_directory = find_latest_directory(
                run_directory / "06_mapas",
                f"paquete_cartografico_{density_text}*",
            )

    return {
        "statistics": gis_directory / "estadisticas_banano.csv",
        "hex_summary": (
            gis_directory
            / f"densidad_hexagonal_objetivo_{density_text}"
            / "resumen_densidad_hexagonal.csv"
        ),
        "opportunities_summary": (
            gis_directory
            / f"oportunidades_siembra_{density_text}"
            / "resumen_oportunidades_siembra.csv"
        ),
        "priority_summary": (
            gis_directory
            / f"prioridad_operativa_{density_text}"
            / "resumen_prioridad_operativa.csv"
        ),
        "kde_summary": (
            gis_directory
            / f"mapa_calor_kde_{density_text}"
            / "resumen_mapa_calor_kde.csv"
        ),
        "maps_directory": resolved_maps_directory,
        "maps_manifest": (
            resolved_maps_directory / "manifiesto_paquete_cartografico.json"
            if resolved_maps_directory is not None
            else None
        ),
        "maps_index": (
            resolved_maps_directory / "indice_mapas.csv"
            if resolved_maps_directory is not None
            else None
        ),
    }


def validate_discovered_inputs(paths: dict[str, Path | None]) -> list[str]:
    """Valida que estén disponibles todos los insumos del informe."""

    labels = {
        "statistics": "estadísticas del inventario",
        "hex_summary": "resumen de densidad hexagonal",
        "opportunities_summary": "resumen de oportunidades de siembra",
        "priority_summary": "resumen de priorización operativa",
        "kde_summary": "resumen del mapa KDE",
        "maps_manifest": "manifiesto del paquete cartográfico",
        "maps_index": "índice del paquete cartográfico",
    }

    errors: list[str] = []

    for key, description in labels.items():
        path = paths.get(key)
        if path is None or not path.is_file():
            errors.append(
                f"No se encontró {description}: {path or 'ruta no resuelta'}"
            )

    maps_directory = paths.get("maps_directory")
    if maps_directory is None or not maps_directory.is_dir():
        errors.append(
            f"No se encontró la carpeta cartográfica: {maps_directory}"
        )

    return errors


def read_json(path: Path) -> dict[str, Any]:
    """Lee un archivo JSON."""

    with path.open("r", encoding="utf-8") as file:
        loaded = json.load(file)

    if not isinstance(loaded, dict):
        raise ValueError(f"El JSON no contiene un objeto: {path}")

    return loaded


def read_maps_index(index_path: Path, maps_directory: Path) -> list[dict[str, Any]]:
    """Lee y valida el índice de mapas."""

    with index_path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise ValueError("El índice cartográfico está vacío.")

    normalized: list[dict[str, Any]] = []

    for position, row in enumerate(rows, start=1):
        filename = str(row.get("filename", "")).strip()
        map_path = maps_directory / filename

        if not filename or not map_path.is_file():
            raise FileNotFoundError(
                f"No se encontró el mapa del índice: {map_path}"
            )

        normalized.append(
            {
                "order": int(row.get("order") or position),
                "map_id": str(row.get("map_id") or f"map_{position}"),
                "title": str(row.get("title") or map_path.stem),
                "purpose": str(row.get("purpose") or ""),
                "filename": filename,
                "path": map_path,
            }
        )

    normalized.sort(key=lambda item: item["order"])
    return normalized


def as_float(value: Any, default: float | None = None) -> float | None:
    """Convierte un valor a float sin propagar NaN."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default

    if not math.isfinite(numeric):
        return default

    return numeric


def as_int(value: Any, default: int = 0) -> int:
    """Convierte un valor a entero."""

    numeric = as_float(value)
    if numeric is None:
        return default
    return int(round(numeric))


def format_number(
    value: Any,
    decimals: int = 2,
    suffix: str = "",
) -> str:
    """Formatea un valor usando separadores legibles en español."""

    numeric = as_float(value)
    if numeric is None:
        return "No disponible"

    formatted = f"{numeric:,.{decimals}f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted}{suffix}"


def format_integer(value: Any) -> str:
    """Formatea un entero con separador de miles."""

    numeric = as_int(value)
    return f"{numeric:,}".replace(",", ".")


def escape_text(value: Any) -> str:
    """Escapa texto para Paragraph de ReportLab."""

    return html.escape(str(value or ""))


def validate_target_consistency(
    target_density_plants_ha: float,
    sources: dict[str, dict[str, Any]],
    maps_manifest: dict[str, Any],
    tolerance_percent: float,
) -> list[str]:
    """Comprueba que todos los productos correspondan al mismo escenario."""

    target = float(target_density_plants_ha)
    tolerance = abs(target) * float(tolerance_percent) / 100.0
    errors: list[str] = []

    checks = [
        (
            "densidad hexagonal",
            sources["hex"].get("densidad_referencia_plantas_ha"),
        ),
        (
            "oportunidades de siembra",
            sources["opportunities"].get("target_density_plants_ha"),
        ),
        (
            "priorización operativa",
            sources["priority"].get("target_density_plants_ha"),
        ),
        (
            "mapa KDE",
            sources["kde"].get("densidad_objetivo_plantas_ha"),
        ),
        (
            "paquete cartográfico",
            maps_manifest.get("target_density_plants_ha"),
        ),
    ]

    for label, observed in checks:
        numeric = as_float(observed)
        if numeric is None:
            errors.append(
                f"No fue posible verificar la densidad objetivo de {label}."
            )
            continue

        if abs(numeric - target) > tolerance:
            errors.append(
                f"La densidad de {label} ({numeric}) no coincide con "
                f"el escenario del informe ({target})."
            )

    return errors


def build_styles(config: dict[str, Any]) -> dict[str, ParagraphStyle]:
    """Construye los estilos del documento."""

    stylesheet = getSampleStyleSheet()
    primary = colors.HexColor(config.get("primary_color", "#1F5A3A"))
    secondary = colors.HexColor(config.get("secondary_color", "#3D6B4F"))
    text_color = colors.HexColor(config.get("text_color", "#202020"))
    muted_color = colors.HexColor(config.get("muted_text_color", "#606060"))

    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=stylesheet["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=27,
            textColor=primary,
            alignment=TA_CENTER,
            spaceAfter=18,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=stylesheet["Heading2"],
            fontName="Helvetica",
            fontSize=14,
            leading=18,
            textColor=secondary,
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "heading1": ParagraphStyle(
            "Heading1Custom",
            parent=stylesheet["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=primary,
            spaceBefore=8,
            spaceAfter=9,
            keepWithNext=True,
        ),
        "heading2": ParagraphStyle(
            "Heading2Custom",
            parent=stylesheet["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=secondary,
            spaceBefore=6,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "BodyCustom",
            parent=stylesheet["BodyText"],
            fontName="Helvetica",
            fontSize=9.6,
            leading=13.2,
            textColor=text_color,
            alignment=TA_JUSTIFY,
            spaceAfter=7,
        ),
        "body_left": ParagraphStyle(
            "BodyLeftCustom",
            parent=stylesheet["BodyText"],
            fontName="Helvetica",
            fontSize=9.4,
            leading=12.6,
            textColor=text_color,
            alignment=TA_LEFT,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "SmallCustom",
            parent=stylesheet["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=muted_color,
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "caption": ParagraphStyle(
            "CaptionCustom",
            parent=stylesheet["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8.3,
            leading=10.5,
            textColor=muted_color,
            alignment=TA_CENTER,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "legal": ParagraphStyle(
            "LegalCustom",
            parent=stylesheet["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.2,
            textColor=muted_color,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=stylesheet["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=10.5,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            parent=stylesheet["BodyText"],
            fontName="Helvetica",
            fontSize=8.3,
            leading=10.5,
            textColor=text_color,
            alignment=TA_LEFT,
        ),
    }


def table_from_rows(
    rows: Iterable[tuple[str, str]],
    styles: dict[str, ParagraphStyle],
    config: dict[str, Any],
    first_header: str = "Indicador",
    second_header: str = "Resultado",
) -> Table:
    """Construye una tabla de dos columnas."""

    data: list[list[Any]] = [
        [
            Paragraph(escape_text(first_header), styles["table_header"]),
            Paragraph(escape_text(second_header), styles["table_header"]),
        ]
    ]

    for label, value in rows:
        data.append(
            [
                Paragraph(escape_text(label), styles["table_cell"]),
                Paragraph(escape_text(value), styles["table_cell"]),
            ]
        )

    table = Table(
        data,
        colWidths=[6.6 * cm, 9.8 * cm],
        repeatRows=1,
        hAlign="LEFT",
    )

    primary = colors.HexColor(config.get("primary_color", "#1F5A3A"))
    alternate = colors.HexColor(config.get("table_alternate_color", "#EEF4F0"))
    grid = colors.HexColor(config.get("table_grid_color", "#B6C2BA"))

    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), primary),
        ("GRID", (0, 0), (-1, -1), 0.35, grid),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]

    for row_index in range(1, len(data)):
        if row_index % 2 == 0:
            commands.append(
                ("BACKGROUND", (0, row_index), (-1, row_index), alternate)
            )

    table.setStyle(TableStyle(commands))
    return table


def fit_image(path: Path, max_width: float, max_height: float) -> Image:
    """Crea una imagen manteniendo su proporción."""

    with PILImage.open(path) as image:
        width_px, height_px = image.size

    if width_px <= 0 or height_px <= 0:
        raise ValueError(f"La imagen no tiene dimensiones válidas: {path}")

    scale = min(max_width / width_px, max_height / height_px)
    width = width_px * scale
    height = height_px * scale

    return Image(str(path), width=width, height=height)


def build_indicator_rows(
    statistics: dict[str, Any],
    hex_summary: dict[str, Any],
    opportunities: dict[str, Any],
    priority: dict[str, Any],
    kde: dict[str, Any],
    target_density: float,
) -> list[tuple[str, str]]:
    """Construye los indicadores ejecutivos del informe."""

    return [
        (
            "Superficie analizada",
            format_number(statistics.get("area_ha"), 4, " ha"),
        ),
        (
            "Plantas detectadas y validadas",
            format_integer(statistics.get("plantas_dentro_limite")),
        ),
        (
            "Densidad actual",
            format_number(
                statistics.get("plantas_por_hectarea"),
                2,
                " plantas/ha",
            ),
        ),
        (
            "Densidad objetivo del productor",
            format_number(target_density, 0, " plantas/ha"),
        ),
        (
            "Detecciones fuera del límite",
            format_integer(statistics.get("detecciones_fuera_limite")),
        ),
        (
            "Hexágonos con déficit severo",
            format_integer(hex_summary.get("hexagonos_deficit_severo")),
        ),
        (
            "Hexágonos con déficit moderado",
            format_integer(hex_summary.get("hexagonos_deficit_moderado")),
        ),
        (
            "Oportunidades geométricas identificadas",
            format_integer(opportunities.get("opportunity_polygons")),
        ),
        (
            "Candidatos geométricos de siembra",
            format_integer(opportunities.get("candidate_positions")),
        ),
        (
            "Candidatos de prioridad alta",
            format_integer(priority.get("candidates_priority_high")),
        ),
        (
            "Candidatos de prioridad media",
            format_integer(priority.get("candidates_priority_medium")),
        ),
        (
            "Inspecciones de campo sugeridas",
            format_integer(priority.get("recommended_field_checks_total")),
        ),
        (
            "Radio KDE aplicado",
            format_number(kde.get("radio_kde_m"), 2, " m"),
        ),
    ]


def density_interpretation(current_density: float, target_density: float) -> str:
    """Genera una interpretación prudente de la densidad global."""

    ratio = current_density / target_density if target_density > 0 else 0.0

    if ratio < 0.90:
        return (
            "La densidad global estimada se encuentra por debajo del 90 % "
            "del objetivo indicado por el productor. El resultado justifica "
            "priorizar la revisión de sectores deficitarios, sin asumir que "
            "todo espacio abierto es cultivable."
        )

    if ratio <= 1.10:
        return (
            "La densidad global estimada se encuentra dentro de un intervalo "
            "próximo al objetivo del productor. Aun así, pueden coexistir "
            "sectores locales con déficit y sectores con concentración elevada."
        )

    return (
        "La densidad global estimada supera en más del 10 % el objetivo del "
        "productor. Se recomienda revisar las zonas de concentración elevada "
        "y descartar duplicados residuales antes de formular medidas de manejo."
    )


def build_recommendations(
    statistics: dict[str, Any],
    opportunities: dict[str, Any],
    priority: dict[str, Any],
    kde: dict[str, Any],
    target_density: float,
) -> list[str]:
    """Construye recomendaciones operativas basadas en los resultados."""

    current_density = as_float(statistics.get("plantas_por_hectarea"), 0.0) or 0.0
    recommendations: list[str] = []

    recommendations.append(
        "Realizar primero la inspección de los candidatos clasificados con "
        "prioridad alta y media, siguiendo el orden definido en la capa de "
        "priorización operativa."
    )

    if as_int(priority.get("recommended_field_checks_total")) > 0:
        recommendations.append(
            "Registrar en campo la decisión técnica de cada candidato: "
            "resiembra recomendada, vía, canal, drenaje, infraestructura, "
            "borde, área no cultivable, planta no detectada u otra condición."
        )

    if as_int(opportunities.get("exclusion_features")) == 0:
        recommendations.append(
            "Crear o incorporar una capa de exclusiones con vías, canales, "
            "drenajes e infraestructura para reducir falsos positivos en "
            "futuras ejecuciones."
        )

    if current_density < target_density:
        recommendations.append(
            "Evaluar la resiembra únicamente en espacios geométricos que, "
            "además del déficit de densidad, sean confirmados como área "
            "productiva disponible por el técnico responsable."
        )

    elevated_area = (
        as_float(kde.get("area_densidad_elevada_m2"), 0.0) or 0.0
    ) + (
        as_float(kde.get("area_densidad_muy_elevada_m2"), 0.0) or 0.0
    )

    if elevated_area > 0:
        recommendations.append(
            "Revisar los sectores de concentración elevada para diferenciar "
            "plantas reales muy próximas, cambios históricos de distribución "
            "y posibles detecciones duplicadas residuales."
        )

    recommendations.append(
        "Conservar los archivos de detecciones eliminadas, resúmenes JSON y "
        "capas GIS como evidencia de trazabilidad del análisis."
    )

    return recommendations


def build_methodology_steps() -> list[str]:
    """Devuelve la metodología resumida del sistema."""

    return [
        "Validación de la ortofoto, sistema de referencia y polígono de análisis.",
        "Recorte de la ortofoto y generación de mosaicos georreferenciados.",
        "Detección de plantas mediante el modelo YOLO configurado para banano.",
        "Conversión de centros de detección a coordenadas proyectadas.",
        "Eliminación de detecciones repetidas entre mosaicos con umbral de 1,00 m.",
        "Validación de plantas dentro del límite y cálculo de superficie y densidad.",
        "Evaluación de densidad local mediante hexágonos de 100 m².",
        "Estimación de oportunidades geométricas con Voronoi y superficie libre.",
        "Priorización de inspecciones según geometría, déficit local y seguridad de borde.",
        "Generación de densidad continua KDE con corrección del efecto de borde.",
        "Producción del paquete cartográfico y consolidación del informe técnico.",
    ]


def build_summary_record(
    statistics: dict[str, Any],
    opportunities: dict[str, Any],
    priority: dict[str, Any],
    kde: dict[str, Any],
    target_density: float,
) -> dict[str, Any]:
    """Construye el resumen CSV del informe."""

    return {
        "fecha_informe": datetime.now().isoformat(timespec="seconds"),
        "densidad_objetivo_plantas_ha": target_density,
        "area_ha": as_float(statistics.get("area_ha")),
        "plantas_validadas": as_int(statistics.get("plantas_dentro_limite")),
        "densidad_actual_plantas_ha": as_float(
            statistics.get("plantas_por_hectarea")
        ),
        "oportunidades_geometricas": as_int(
            opportunities.get("opportunity_polygons")
        ),
        "candidatos_geometricos": as_int(
            opportunities.get("candidate_positions")
        ),
        "candidatos_prioridad_alta": as_int(
            priority.get("candidates_priority_high")
        ),
        "candidatos_prioridad_media": as_int(
            priority.get("candidates_priority_medium")
        ),
        "inspecciones_sugeridas": as_int(
            priority.get("recommended_field_checks_total")
        ),
        "radio_kde_m": as_float(kde.get("radio_kde_m")),
        "estado_tecnico": "pendiente_revision_de_campo",
    }


def write_summary_csv(record: dict[str, Any], output_path: Path) -> None:
    """Escribe el resumen del informe de forma atómica."""

    temporary_path = output_path.with_suffix(".partial.csv")

    try:
        pd.DataFrame([record]).to_csv(
            temporary_path,
            index=False,
            encoding="utf-8-sig",
        )
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def draw_page_decorations(
    canvas: Any,
    document: Any,
    author: str,
    farm_name: str,
    config: dict[str, Any],
) -> None:
    """Dibuja encabezado, pie, autoría y número de página."""

    canvas.saveState()
    page_width, page_height = document.pagesize

    primary = colors.HexColor(config.get("primary_color", "#1F5A3A"))
    muted = colors.HexColor(config.get("muted_text_color", "#606060"))

    canvas.setStrokeColor(primary)
    canvas.setLineWidth(0.6)
    canvas.line(
        document.leftMargin,
        page_height - 1.15 * cm,
        page_width - document.rightMargin,
        page_height - 1.15 * cm,
    )

    canvas.setFont("Helvetica", 7.4)
    canvas.setFillColor(muted)
    canvas.drawString(
        document.leftMargin,
        page_height - 0.90 * cm,
        f"Informe técnico - {farm_name}",
    )

    canvas.setStrokeColor(primary)
    canvas.line(
        document.leftMargin,
        1.15 * cm,
        page_width - document.rightMargin,
        1.15 * cm,
    )

    canvas.setFont("Helvetica", 7.2)
    canvas.setFillColor(muted)
    canvas.drawString(
        document.leftMargin,
        0.72 * cm,
        f"Elaborado por {author} - Todos los derechos reservados",
    )
    canvas.drawRightString(
        page_width - document.rightMargin,
        0.72 * cm,
        f"Página {document.page}",
    )

    canvas.restoreState()


def build_pdf(
    output_path: Path,
    config: dict[str, Any],
    farm_name: str,
    producer: str,
    author: str,
    target_density: float,
    report_date: str,
    statistics: dict[str, Any],
    hex_summary: dict[str, Any],
    opportunities: dict[str, Any],
    priority: dict[str, Any],
    kde: dict[str, Any],
    maps: list[dict[str, Any]],
    source_paths: dict[str, Path | None],
) -> None:
    """Construye el informe PDF."""

    page_size = resolve_page_size(config.get("page_size", "A4"))
    styles = build_styles(config)

    margins = config.get("margins_cm", {})
    left_margin = float(margins.get("left", 1.8)) * cm
    right_margin = float(margins.get("right", 1.8)) * cm
    top_margin = float(margins.get("top", 1.8)) * cm
    bottom_margin = float(margins.get("bottom", 1.7)) * cm

    document = BaseDocTemplate(
        str(output_path),
        pagesize=page_size,
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
        title=config.get(
            "title",
            "Informe técnico de inventario y análisis espacial de banano",
        ),
        author=author,
        subject=(
            "Inventario automatizado, densidad, oportunidades geométricas "
            "de siembra y priorización operativa."
        ),
    )

    frame = Frame(
        document.leftMargin,
        document.bottomMargin,
        document.width,
        document.height,
        id="normal",
    )

    page_template = PageTemplate(
        id="main",
        frames=[frame],
        onPage=lambda canvas, doc: draw_page_decorations(
            canvas,
            doc,
            author,
            farm_name,
            config,
        ),
    )
    document.addPageTemplates([page_template])

    story: list[Any] = []

    # Portada
    story.append(Spacer(1, 2.1 * cm))
    story.append(
        Paragraph(
            escape_text(
                config.get(
                    "title",
                    "Informe técnico de inventario y análisis espacial de banano",
                )
            ),
            styles["cover_title"],
        )
    )
    story.append(
        Paragraph(
            escape_text(farm_name),
            styles["cover_subtitle"],
        )
    )
    story.append(Spacer(1, 0.45 * cm))

    cover_rows = [
        ("Productor o empresa", producer or "No especificado"),
        (
            "Densidad objetivo",
            format_number(target_density, 0, " plantas/ha"),
        ),
        ("Fecha del informe", report_date),
        ("Autor responsable", author),
        (
            "Sistema de referencia",
            f"EPSG:{as_int(statistics.get('epsg'))}",
        ),
    ]
    story.append(table_from_rows(cover_rows, styles, config, "Dato", "Contenido"))
    story.append(Spacer(1, 0.7 * cm))
    story.append(
        Paragraph(
            escape_text(
                config.get(
                    "cover_notice",
                    "Resultados generados mediante procesamiento geoespacial y detección automatizada. Las decisiones de resiembra y manejo requieren verificación técnica en campo.",
                )
            ),
            styles["legal"],
        )
    )
    story.append(Spacer(1, 0.35 * cm))
    story.append(
        Paragraph(
            escape_text(
                config.get(
                    "legal_notice",
                    "Elaborado por el Ing. Darwin A. González Romero. Todos los derechos pertenecen al autor. No se autoriza la reproducción, modificación o distribución sin autorización expresa.",
                )
            ),
            styles["legal"],
        )
    )
    story.append(PageBreak())

    # Resumen ejecutivo
    story.append(Paragraph("1. Resumen ejecutivo", styles["heading1"]))

    current_density = as_float(statistics.get("plantas_por_hectarea"), 0.0) or 0.0
    executive_text = (
        f"El análisis de la finca <b>{escape_text(farm_name)}</b> comprende "
        f"una superficie de <b>{format_number(statistics.get('area_ha'), 4)} ha</b> "
        f"y un inventario de <b>{format_integer(statistics.get('plantas_dentro_limite'))} "
        f"plantas</b> espacialmente validadas. La densidad estimada es de "
        f"<b>{format_number(current_density, 2)} plantas/ha</b>, frente a una "
        f"densidad objetivo de <b>{format_number(target_density, 0)} plantas/ha</b>. "
        f"{density_interpretation(current_density, target_density)}"
    )
    story.append(Paragraph(executive_text, styles["body"]))

    story.append(
        table_from_rows(
            build_indicator_rows(
                statistics,
                hex_summary,
                opportunities,
                priority,
                kde,
                target_density,
            ),
            styles,
            config,
        )
    )
    story.append(Spacer(1, 0.25 * cm))

    story.append(Paragraph("Conclusión operativa", styles["heading2"]))
    story.append(
        Paragraph(
            (
                "Las oportunidades y los candidatos generados representan "
                "espacios geométricos compatibles con el escenario de densidad. "
                "No constituyen plantas faltantes confirmadas ni una orden directa "
                "de resiembra. La validación del uso real del suelo, especialmente "
                "vías, canales, drenajes e infraestructura, corresponde al técnico "
                "responsable de la inspección."
            ),
            styles["body"],
        )
    )

    # Metodología
    story.append(Paragraph("2. Metodología aplicada", styles["heading1"]))
    for index, step in enumerate(build_methodology_steps(), start=1):
        story.append(
            Paragraph(
                f"<b>{index}.</b> {escape_text(step)}",
                styles["body_left"],
            )
        )

    story.append(Paragraph("Parámetros principales", styles["heading2"]))
    parameter_rows = [
        ("Densidad objetivo", format_number(target_density, 0, " plantas/ha")),
        ("Umbral de deduplicación", "1,00 m"),
        (
            "Unidad de densidad hexagonal",
            format_number(hex_summary.get("area_nominal_hexagono_m2"), 0, " m²"),
        ),
        ("Radio KDE", format_number(kde.get("radio_kde_m"), 2, " m")),
        ("Tamaño de píxel KDE", format_number(kde.get("pixel_kde_m"), 2, " m")),
        ("Corrección de borde KDE", str(kde.get("correccion_borde"))),
        ("Estado de candidatos", "Pendientes de revisión técnica"),
    ]
    story.append(table_from_rows(parameter_rows, styles, config))
    story.append(PageBreak())

    # Resultados detallados
    story.append(Paragraph("3. Resultados del inventario", styles["heading1"]))
    inventory_rows = [
        ("Área del límite", format_number(statistics.get("area_m2"), 2, " m²")),
        ("Área del límite", format_number(statistics.get("area_ha"), 4, " ha")),
        (
            "Detecciones deduplicadas de entrada",
            format_integer(statistics.get("detecciones_deduplicadas_entrada")),
        ),
        (
            "Plantas dentro del límite",
            format_integer(statistics.get("plantas_dentro_limite")),
        ),
        (
            "Detecciones fuera del límite",
            format_integer(statistics.get("detecciones_fuera_limite")),
        ),
        (
            "Duplicados eliminados previamente",
            format_integer(statistics.get("duplicados_eliminados_previos")),
        ),
        (
            "Densidad actual",
            format_number(statistics.get("plantas_por_hectarea"), 2, " plantas/ha"),
        ),
        (
            "Confianza media del modelo",
            format_number(statistics.get("confianza_media"), 4),
        ),
    ]
    story.append(table_from_rows(inventory_rows, styles, config))

    story.append(Paragraph("4. Densidad local", styles["heading1"]))
    density_rows = [
        ("Hexágonos totales", format_integer(hex_summary.get("hexagonos_totales"))),
        (
            "Hexágonos evaluables",
            format_integer(hex_summary.get("hexagonos_evaluables")),
        ),
        (
            "Déficit severo",
            format_integer(hex_summary.get("hexagonos_deficit_severo")),
        ),
        (
            "Déficit moderado",
            format_integer(hex_summary.get("hexagonos_deficit_moderado")),
        ),
        (
            "Densidad esperada",
            format_integer(hex_summary.get("hexagonos_densidad_esperada")),
        ),
        (
            "Densidad elevada",
            format_integer(hex_summary.get("hexagonos_densidad_elevada")),
        ),
        (
            "Densidad muy elevada",
            format_integer(hex_summary.get("hexagonos_densidad_muy_elevada")),
        ),
        (
            "Borde no evaluable",
            format_integer(hex_summary.get("hexagonos_borde_no_evaluable")),
        ),
    ]
    story.append(table_from_rows(density_rows, styles, config))

    story.append(Paragraph("5. Oportunidades y priorización", styles["heading1"]))
    opportunity_rows = [
        (
            "Área teórica por planta",
            format_number(opportunities.get("target_area_per_plant_m2"), 3, " m²"),
        ),
        (
            "Separación equivalente de referencia",
            format_number(opportunities.get("target_spacing_equivalent_m"), 3, " m"),
        ),
        (
            "Plantas existentes",
            format_integer(opportunities.get("existing_plants")),
        ),
        (
            "Plantas teóricas para el objetivo",
            format_number(opportunities.get("theoretical_target_plants"), 1),
        ),
        (
            "Diferencia teórica global",
            format_number(opportunities.get("global_target_difference"), 1),
        ),
        (
            "Polígonos de oportunidad",
            format_integer(opportunities.get("opportunity_polygons")),
        ),
        (
            "Candidatos geométricos",
            format_integer(opportunities.get("candidate_positions")),
        ),
        (
            "Prioridad alta",
            format_integer(priority.get("candidates_priority_high")),
        ),
        (
            "Prioridad media",
            format_integer(priority.get("candidates_priority_medium")),
        ),
        (
            "Prioridad baja",
            format_integer(priority.get("candidates_priority_low")),
        ),
        (
            "Inspecciones sugeridas",
            format_integer(priority.get("recommended_field_checks_total")),
        ),
    ]
    story.append(table_from_rows(opportunity_rows, styles, config))

    story.append(Paragraph("6. Tendencia continua KDE", styles["heading1"]))
    boundary_area_m2 = as_float(kde.get("area_limite_m2"), 0.0) or 0.0

    def area_with_percent(field_name: str) -> str:
        area_value = as_float(kde.get(field_name), 0.0) or 0.0
        percent = area_value / boundary_area_m2 * 100.0 if boundary_area_m2 > 0 else 0.0
        return (
            f"{format_number(area_value, 1)} m² "
            f"({format_number(percent, 1)} %)"
        )

    kde_rows = [
        ("Densidad KDE mínima", format_number(kde.get("densidad_kde_minima"), 1, " plantas/ha")),
        ("Densidad KDE media", format_number(kde.get("densidad_kde_media"), 1, " plantas/ha")),
        ("Densidad KDE mediana", format_number(kde.get("densidad_kde_mediana"), 1, " plantas/ha")),
        ("Densidad KDE máxima", format_number(kde.get("densidad_kde_maxima"), 1, " plantas/ha")),
        ("Área con déficit severo", area_with_percent("area_deficit_severo_m2")),
        ("Área con déficit moderado", area_with_percent("area_deficit_moderado_m2")),
        ("Área con densidad esperada", area_with_percent("area_densidad_esperada_m2")),
        ("Área con densidad elevada", area_with_percent("area_densidad_elevada_m2")),
        ("Área con densidad muy elevada", area_with_percent("area_densidad_muy_elevada_m2")),
        ("Área de borde no evaluable", area_with_percent("area_borde_no_evaluable_m2")),
    ]
    story.append(table_from_rows(kde_rows, styles, config))
    story.append(PageBreak())

    # Mapas
    story.append(Paragraph("7. Paquete cartográfico", styles["heading1"]))
    story.append(
        Paragraph(
            "Los mapas siguientes utilizan la misma densidad objetivo y el mismo "
            "sistema de referencia del análisis. Las imágenes se presentan para "
            "interpretación técnica y deben revisarse junto con las capas GIS.",
            styles["body"],
        )
    )

    max_map_width = float(config.get("map_max_width_cm", 17.0)) * cm
    max_map_height = float(config.get("map_max_height_cm", 17.8)) * cm

    for map_index, map_item in enumerate(maps, start=1):
        if map_index > 1:
            story.append(PageBreak())

        story.append(
            Paragraph(
                f"7.{map_index}. {escape_text(map_item['title'])}",
                styles["heading2"],
            )
        )
        story.append(
            KeepTogether(
                [
                    fit_image(
                        map_item["path"],
                        max_map_width,
                        max_map_height,
                    ),
                    Paragraph(
                        escape_text(map_item.get("purpose", "")),
                        styles["caption"],
                    ),
                ]
            )
        )

    story.append(PageBreak())

    # Recomendaciones y limitaciones
    story.append(Paragraph("8. Recomendaciones operativas", styles["heading1"]))
    recommendations = build_recommendations(
        statistics,
        opportunities,
        priority,
        kde,
        target_density,
    )

    for index, recommendation in enumerate(recommendations, start=1):
        story.append(
            Paragraph(
                f"<b>{index}.</b> {escape_text(recommendation)}",
                styles["body_left"],
            )
        )

    story.append(Paragraph("9. Limitaciones e interpretación", styles["heading1"]))
    limitations = [
        "El inventario depende de la calidad de la ortofoto, resolución espacial, visibilidad de las copas y desempeño del modelo YOLO.",
        "La deduplicación de 1,00 m reduce detecciones repetidas, pero puede conservar errores residuales o eliminar casos muy próximos que requieren auditoría.",
        "Los candidatos de siembra representan oportunidades geométricas, no faltantes confirmados ni recomendaciones automáticas de resiembra.",
        "Las zonas de densidad elevada representan concentración espacial de plantas, no traslape foliar confirmado.",
        "Vías, canales, drenajes, infraestructura y áreas no cultivables deben incorporarse como exclusiones o clasificarse durante la inspección técnica.",
        "Los resultados corresponden al momento de captura de la ortofoto y deben actualizarse cuando existan cambios importantes en la plantación.",
    ]

    for limitation in limitations:
        story.append(
            Paragraph(
                f"- {escape_text(limitation)}",
                styles["body_left"],
            )
        )

    story.append(Paragraph("10. Trazabilidad de resultados", styles["heading1"]))
    trace_rows = [
        ("Carpeta de ejecución", str(source_paths.get("run_directory", ""))),
        ("Estadísticas", str(source_paths.get("statistics", ""))),
        ("Resumen hexagonal", str(source_paths.get("hex_summary", ""))),
        ("Resumen de oportunidades", str(source_paths.get("opportunities_summary", ""))),
        ("Resumen de prioridad", str(source_paths.get("priority_summary", ""))),
        ("Resumen KDE", str(source_paths.get("kde_summary", ""))),
        ("Paquete cartográfico", str(source_paths.get("maps_directory", ""))),
    ]
    story.append(table_from_rows(trace_rows, styles, config, "Producto", "Ruta"))

    story.append(Spacer(1, 0.5 * cm))
    story.append(
        Paragraph(
            escape_text(
                config.get(
                    "legal_notice",
                    "Elaborado por el Ing. Darwin A. González Romero. Todos los derechos pertenecen al autor. No se autoriza la reproducción, modificación o distribución sin autorización expresa.",
                )
            ),
            styles["legal"],
        )
    )

    document.build(story)


def save_manifest(result: TechnicalReportResult, output_path: Path) -> Path:
    """Guarda el manifiesto JSON del informe."""

    result.manifest_path = str(output_path)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            asdict(result),
            file,
            ensure_ascii=False,
            indent=4,
        )

    return output_path


def generate_technical_report(
    run_directory: str | Path,
    target_density_plants_ha: float,
    farm_name: str,
    producer: str = "",
    author: str = DEFAULT_AUTHOR,
    report_date: str | None = None,
    maps_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> TechnicalReportResult:
    """Genera el informe técnico PDF a partir de las fases anteriores."""

    started_at = datetime.now().isoformat(timespec="seconds")
    start_time = time.perf_counter()

    normalized_run_directory = (
        Path(run_directory).expanduser().resolve(strict=False)
    )

    result = TechnicalReportResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        run_directory=str(normalized_run_directory),
        target_density_plants_ha=float(target_density_plants_ha),
        farm_name=str(farm_name).strip(),
        producer=str(producer).strip(),
        author=str(author).strip() or DEFAULT_AUTHOR,
    )

    if not normalized_run_directory.is_dir():
        result.errors.append("La carpeta de ejecución no existe.")

    if not result.farm_name:
        result.errors.append("El nombre de la finca es obligatorio.")

    if not math.isfinite(float(target_density_plants_ha)) or float(
        target_density_plants_ha
    ) <= 0:
        result.errors.append("La densidad objetivo debe ser mayor que cero.")

    resolved_output_directory = (
        Path(output_dir).expanduser().resolve(strict=False)
        if output_dir is not None
        else normalized_run_directory / "07_reporte"
    )
    result.output_directory = str(resolved_output_directory)

    density_text = density_label(target_density_plants_ha)
    farm_slug = sanitize_name(result.farm_name)
    pdf_path = (
        resolved_output_directory
        / f"informe_tecnico_{farm_slug}_{density_text}.pdf"
    )
    summary_csv_path = (
        resolved_output_directory
        / f"resumen_informe_{farm_slug}_{density_text}.csv"
    )
    manifest_path = (
        resolved_output_directory
        / f"manifiesto_informe_{farm_slug}_{density_text}.json"
    )

    existing_outputs = [
        path
        for path in (pdf_path, summary_csv_path, manifest_path)
        if path.exists()
    ]

    if existing_outputs:
        result.errors.append(
            "No se sobrescribirán salidas existentes: "
            + ", ".join(str(path) for path in existing_outputs)
        )

    if result.errors:
        result.finished_at = datetime.now().isoformat(timespec="seconds")
        return result

    generated_paths: list[Path] = []

    try:
        resolved_config_path, report_config = load_config(config_path)
        discovered = discover_inputs(
            normalized_run_directory,
            float(target_density_plants_ha),
            maps_dir,
        )
        result.errors.extend(validate_discovered_inputs(discovered))

        if result.errors:
            raise FileNotFoundError(
                "No están disponibles todas las entradas requeridas."
            )

        statistics = read_single_row_csv(discovered["statistics"])  # type: ignore[arg-type]
        hex_summary = read_single_row_csv(discovered["hex_summary"])  # type: ignore[arg-type]
        opportunities = read_single_row_csv(
            discovered["opportunities_summary"]  # type: ignore[arg-type]
        )
        priority = read_single_row_csv(discovered["priority_summary"])  # type: ignore[arg-type]
        kde = read_single_row_csv(discovered["kde_summary"])  # type: ignore[arg-type]
        maps_manifest = read_json(discovered["maps_manifest"])  # type: ignore[arg-type]
        maps = read_maps_index(
            discovered["maps_index"],  # type: ignore[arg-type]
            discovered["maps_directory"],  # type: ignore[arg-type]
        )

        tolerance_percent = float(
            report_config.get("target_density_tolerance_percent", 1.0)
        )
        result.errors.extend(
            validate_target_consistency(
                float(target_density_plants_ha),
                {
                    "hex": hex_summary,
                    "opportunities": opportunities,
                    "priority": priority,
                    "kde": kde,
                },
                maps_manifest,
                tolerance_percent,
            )
        )

        if result.errors:
            raise ValueError(
                "Las entradas pertenecen a escenarios de densidad incompatibles."
            )

        if not bool(maps_manifest.get("success", False)):
            raise ValueError(
                "El manifiesto cartográfico no registra una ejecución exitosa."
            )

        minimum_map_count = int(report_config.get("minimum_map_count", 6))
        if len(maps) < minimum_map_count:
            raise ValueError(
                f"El informe requiere al menos {minimum_map_count} mapas; "
                f"solo se encontraron {len(maps)}."
            )

        resolved_output_directory.mkdir(parents=True, exist_ok=True)

        temporary_pdf = pdf_path.with_suffix(".partial.pdf")
        if temporary_pdf.exists():
            temporary_pdf.unlink()

        source_paths = dict(discovered)
        source_paths["run_directory"] = normalized_run_directory

        build_pdf(
            output_path=temporary_pdf,
            config=report_config,
            farm_name=result.farm_name,
            producer=result.producer,
            author=result.author,
            target_density=float(target_density_plants_ha),
            report_date=(
                report_date
                or datetime.now().strftime("%d/%m/%Y")
            ),
            statistics=statistics,
            hex_summary=hex_summary,
            opportunities=opportunities,
            priority=priority,
            kde=kde,
            maps=maps,
            source_paths=source_paths,
        )

        if not temporary_pdf.is_file() or temporary_pdf.stat().st_size <= 0:
            raise RuntimeError("El PDF temporal no se generó correctamente.")

        temporary_pdf.replace(pdf_path)
        generated_paths.append(pdf_path)
        result.report_pdf = str(pdf_path)

        summary_record = build_summary_record(
            statistics,
            opportunities,
            priority,
            kde,
            float(target_density_plants_ha),
        )
        write_summary_csv(summary_record, summary_csv_path)
        generated_paths.append(summary_csv_path)
        result.summary_csv = str(summary_csv_path)

        elapsed_seconds = round(time.perf_counter() - start_time, 3)

        result.metadata = {
            "config_path": str(resolved_config_path),
            "report_title": report_config.get("title"),
            "page_size": report_config.get("page_size", "A4"),
            "maps_included": len(maps),
            "map_files": [item["filename"] for item in maps],
            "inventory_plants": as_int(
                statistics.get("plantas_dentro_limite")
            ),
            "area_hectares": as_float(statistics.get("area_ha")),
            "current_density_plants_ha": as_float(
                statistics.get("plantas_por_hectarea")
            ),
            "target_density_plants_ha": float(target_density_plants_ha),
            "recommended_field_checks": as_int(
                priority.get("recommended_field_checks_total")
            ),
            "qgis_required": False,
            "elapsed_seconds": elapsed_seconds,
        }

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible generar el informe técnico: "
            f"{type(error).__name__}: {error}"
        )

        for generated_path in generated_paths:
            if generated_path.exists():
                try:
                    generated_path.unlink()
                except OSError:
                    result.warnings.append(
                        "No fue posible eliminar una salida incompleta: "
                        f"{generated_path}"
                    )

    result.finished_at = datetime.now().isoformat(timespec="seconds")

    if resolved_output_directory.exists():
        save_manifest(result, manifest_path)

    return result


def print_technical_report_summary(result: TechnicalReportResult) -> None:
    """Muestra el resumen del proceso en la terminal."""

    print("=" * 72)
    print("GENERACIÓN DEL INFORME TÉCNICO PDF")
    print("=" * 72)
    print(f"Ejecución: {result.run_directory}")
    print(f"Finca: {result.farm_name}")
    print(
        "Densidad objetivo: "
        f"{result.target_density_plants_ha} plantas/ha"
    )
    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        print(
            "Plantas inventariadas: "
            f"{result.metadata['inventory_plants']}"
        )
        print(
            "Mapas incorporados: "
            f"{result.metadata['maps_included']}"
        )
        print(
            "Inspecciones sugeridas: "
            f"{result.metadata['recommended_field_checks']}"
        )
        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} segundos"
        )

    if result.report_pdf:
        print(f"Informe PDF: {result.report_pdf}")

    if result.summary_csv:
        print(f"Resumen CSV: {result.summary_csv}")

    if result.errors:
        print("\nERRORES:")
        for error in result.errors:
            print(f"  - {error}")

    if result.warnings:
        print("\nADVERTENCIAS:")
        for warning in result.warnings:
            print(f"  - {warning}")

    if result.manifest_path:
        print(f"\nManifiesto: {result.manifest_path}")

    print("=" * 72)


def run_technical_report(
    run_directory: str | Path,
    target_density_plants_ha: float,
    farm_name: str,
    producer: str = "",
    author: str = DEFAULT_AUTHOR,
    report_date: str | None = None,
    maps_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta la generación del informe desde main.py."""

    result = generate_technical_report(
        run_directory=run_directory,
        target_density_plants_ha=target_density_plants_ha,
        farm_name=farm_name,
        producer=producer,
        author=author,
        report_date=report_date,
        maps_dir=maps_dir,
        config_path=config_path,
        output_dir=output_dir,
    )

    print_technical_report_summary(result)
    return 0 if result.success else 1
