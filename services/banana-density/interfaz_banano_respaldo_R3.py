from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import yaml


BUILD_ID = "DALGORO_BANANA_GUI_V1_20260718_R3_EXCLUSIONES"

PROJECT_ROOT = Path(__file__).resolve().parent
MAIN_FILE = PROJECT_ROOT / "main.py"
CONFIG_DIRECTORY = PROJECT_ROOT / "config"
RUNS_DIRECTORY = PROJECT_ROOT / "runs"
SETTINGS_FILE = CONFIG_DIRECTORY / "interfaz_ultimo_uso.json"

SPATIAL_CONFIG = CONFIG_DIRECTORY / "spatial_analysis.yaml"
CARTOGRAPHY_CONFIG = CONFIG_DIRECTORY / "cartography.yaml"
REPORT_CONFIG = CONFIG_DIRECTORY / "report.yaml"

DEFAULT_MODEL_PATH = (
    PROJECT_ROOT.parent
    / "runs"
    / "detect"
    / "banano_v3"
    / "weights"
    / "best.pt"
)

BRAND_PRIMARY = "#21393F"
BRAND_SECONDARY = "#192B2F"
BRAND_ACCENT = "#B57548"
BRAND_LIGHT = "#F3F5F4"
BRAND_WHITE = "#FFFFFF"
BRAND_ERROR = "#9E2A2B"
BRAND_SUCCESS = "#2E6B57"

ALL_EXCLUSION_LAYERS = "COMBINAR TODAS LAS CAPAS"
GENERATED_EXCLUSIONS_DIRECTORY = (
    PROJECT_ROOT / "resources" / "exclusiones_generadas"
)

STAGE_TITLES = [
    "Verificación del entorno",
    "Validación de la ortofoto",
    "Validación del límite",
    "Recorte de la ortofoto",
    "Generación de tiles",
    "Inferencia YOLO",
    "Georreferenciación",
    "Exportación GIS preliminar",
    "Deduplicación",
    "Estadísticas espaciales",
    "Análisis del patrón espacial",
    "Densidad por hexágonos",
    "Oportunidades geométricas de siembra",
    "Priorización operativa",
    "Mapa continuo KDE",
    "Paquete cartográfico",
    "Informe técnico PDF",
]


def sanitize_name(value: str) -> str:
    """Convierte un nombre en una identificación segura."""

    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        normalized,
    )
    normalized = normalized.strip("_")
    return normalized or "NUEVA_FINCA"


def normalize_existing_file(value: str) -> Path:
    """Normaliza una ruta de archivo proporcionada por el usuario."""

    cleaned = value.strip().strip('"').strip("'")

    if not cleaned:
        raise ValueError("La ruta no puede estar vacía.")

    return Path(cleaned).expanduser().resolve(strict=False)


def normalize_directory(value: str) -> Path:
    """Normaliza una carpeta absoluta o relativa al proyecto."""

    cleaned = value.strip().strip('"').strip("'")

    if not cleaned:
        raise ValueError(
            "La carpeta de ejecuciones no puede estar vacía."
        )

    candidate = Path(cleaned).expanduser()

    if candidate.is_absolute():
        return candidate.resolve(strict=False)

    return (PROJECT_ROOT / candidate).resolve(strict=False)


def read_yaml(path: Path) -> dict[str, Any]:
    """Lee un YAML y exige un objeto raíz."""

    loaded = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(loaded, dict):
        raise ValueError(
            f"El archivo YAML no contiene un objeto válido: {path}"
        )

    return loaded


def validate_support_config(
    path: Path,
    *,
    minimum_version: int,
    section: str | None = None,
    require_branding: bool = False,
) -> None:
    """Valida configuraciones técnicas ya instaladas."""

    if not path.is_file():
        raise FileNotFoundError(
            f"No existe la configuración: {path}"
        )

    loaded = read_yaml(path)
    version = int(loaded.get("version", 0) or 0)

    if version < minimum_version:
        raise ValueError(
            f"{path.name} debe ser versión {minimum_version} "
            f"o superior. Versión encontrada: {version}."
        )

    if section is None:
        return

    section_data = loaded.get(section)

    if not isinstance(section_data, dict):
        raise ValueError(
            f"{path.name} debe contener la sección '{section}'."
        )

    if require_branding and not isinstance(
        section_data.get("branding"),
        dict,
    ):
        raise ValueError(
            f"{path.name} debe contener '{section}.branding'."
        )


def validate_installation() -> list[str]:
    """Valida archivos indispensables sin abrir la interfaz."""

    messages: list[str] = []

    if not MAIN_FILE.is_file():
        raise FileNotFoundError(
            f"No existe el archivo principal: {MAIN_FILE}"
        )

    orchestrator = (
        PROJECT_ROOT
        / "src"
        / "banana_analyzer"
        / "pipeline_orchestrator.py"
    )

    if not orchestrator.is_file():
        raise FileNotFoundError(
            f"No existe el orquestador: {orchestrator}"
        )

    validate_support_config(
        SPATIAL_CONFIG,
        minimum_version=6,
    )
    validate_support_config(
        CARTOGRAPHY_CONFIG,
        minimum_version=2,
        section="cartography",
        require_branding=True,
    )
    validate_support_config(
        REPORT_CONFIG,
        minimum_version=2,
        section="report",
        require_branding=True,
    )

    messages.extend(
        [
            f"main.py: {MAIN_FILE}",
            f"orquestador: {orchestrator}",
            "spatial_analysis.yaml: versión compatible",
            "cartography.yaml: versión 2 con branding",
            "report.yaml: versión 2 con branding",
        ]
    )
    return messages


def validate_date(value: str) -> str | None:
    """Valida DD/MM/AAAA o devuelve None para fecha automática."""

    text = value.strip()

    if not text:
        return None

    try:
        datetime.strptime(text, "%d/%m/%Y")
    except ValueError as error:
        raise ValueError(
            "La fecha debe escribirse como DD/MM/AAAA."
        ) from error

    return text


def project_relative_or_absolute(path: Path) -> str:
    """Conserva rutas técnicas relativas cuando están dentro del proyecto."""

    try:
        relative = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return path.as_posix()

    return relative.as_posix()


def list_gpkg_feature_layers(path: Path) -> list[str]:
    """Lista únicamente las capas espaciales de un GeoPackage."""

    try:
        with sqlite3.connect(path) as connection:
            rows = connection.execute(
                """
                SELECT table_name
                FROM gpkg_contents
                WHERE data_type = 'features'
                ORDER BY table_name
                """
            ).fetchall()
    except sqlite3.Error as error:
        raise ValueError(
            f"No se pudo leer el GeoPackage: {error}"
        ) from error

    return [str(row[0]) for row in rows]


def build_combined_exclusions(
    source_path: Path,
    layer_names: list[str],
    farm_name: str,
) -> tuple[Path, str]:
    """
    Combina todas las capas espaciales en una sola capa persistente.

    El archivo resultante se conserva dentro del proyecto para que
    una ejecución interrumpida pueda reanudarse con la misma entrada.
    """

    if not layer_names:
        raise ValueError(
            "El GeoPackage no contiene capas espaciales."
        )

    try:
        import geopandas as gpd
        import pandas as pd
    except ImportError as error:
        raise RuntimeError(
            "Para combinar varias capas se requieren geopandas "
            "y pandas en el entorno virtual."
        ) from error

    source_signature = (
        f"{source_path.resolve(strict=False)}|"
        f"{source_path.stat().st_size}|"
        f"{source_path.stat().st_mtime_ns}|"
        + "|".join(layer_names)
    )
    digest = hashlib.sha256(
        source_signature.encode("utf-8")
    ).hexdigest()[:12]

    GENERATED_EXCLUSIONS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_path = (
        GENERATED_EXCLUSIONS_DIRECTORY
        / (
            f"{sanitize_name(farm_name)}_"
            f"exclusiones_{digest}.gpkg"
        )
    )
    output_layer = "exclusiones"

    if output_path.is_file():
        existing_layers = list_gpkg_feature_layers(
            output_path
        )

        if output_layer in existing_layers:
            return output_path, output_layer

        output_path.unlink()

    frames: list[Any] = []
    target_crs: Any = None

    for layer_name in layer_names:
        layer = gpd.read_file(
            source_path,
            layer=layer_name,
        )

        if target_crs is None:
            target_crs = layer.crs
        elif layer.crs != target_crs:
            layer = layer.to_crs(target_crs)

        layer = layer.copy()
        layer["tipo_exclusion"] = layer_name

        if "id" in layer.columns:
            layer["id_origen"] = layer["id"]
        else:
            layer["id_origen"] = range(
                1,
                len(layer) + 1,
            )

        frames.append(
            layer[
                [
                    "tipo_exclusion",
                    "id_origen",
                    "geometry",
                ]
            ]
        )

    combined = gpd.GeoDataFrame(
        pd.concat(
            frames,
            ignore_index=True,
        ),
        geometry="geometry",
        crs=target_crs,
    )
    combined = combined[
        combined.geometry.notna()
        & ~combined.geometry.is_empty
    ].copy()

    if combined.empty:
        raise ValueError(
            "Las capas seleccionadas no contienen geometrías."
        )

    temporary_path = output_path.with_name(
        output_path.stem + "_partial.gpkg"
    )

    if temporary_path.exists():
        temporary_path.unlink()

    try:
        combined.to_file(
            temporary_path,
            layer=output_layer,
            driver="GPKG",
        )
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return output_path, output_layer


def build_pipeline_config(values: dict[str, Any]) -> dict[str, Any]:
    """Construye el YAML que consume el orquestador."""

    density = float(values["target_density"])
    density_value: int | float = (
        int(density)
        if density.is_integer()
        else density
    )

    exclusions_gpkg = values.get("exclusions_gpkg")
    exclusions_layer = values.get("exclusions_layer")

    return {
        "version": 1,
        "analysis": {
            "farm_name": values["farm_name"],
            "producer": values.get("producer", ""),
            "author": "Ing. Darwin A. González Romero",
            "report_date": values.get("report_date"),
            "orthophoto_path": Path(
                values["orthophoto"]
            ).as_posix(),
            "boundary_excel_path": Path(
                values["boundary_excel"]
            ).as_posix(),
            "boundary_sheet": values["boundary_sheet"],
            "target_density_plants_ha": density_value,
            "model_path": Path(
                values["model_path"]
            ).as_posix(),
            "output_root": values["output_root"],
            "exclusions_gpkg": (
                Path(exclusions_gpkg).as_posix()
                if exclusions_gpkg
                else None
            ),
            "exclusions_layer": (
                exclusions_layer or None
            ),
        },
        "parameters": {
            "tile_size": int(values["tile_size"]),
            "overlap": int(values["overlap"]),
            "min_valid_percent": float(
                values["min_valid_percent"]
            ),
            "yolo_confidence": float(
                values["yolo_confidence"]
            ),
            "yolo_iou": float(values["yolo_iou"]),
            "yolo_imgsz": int(values["yolo_imgsz"]),
            "yolo_device": values["yolo_device"],
            "max_detections": int(
                values["max_detections"]
            ),
            "yolo_limit": None,
            "deduplication_distance_m": float(
                values["deduplication_distance"]
            ),
            "kde_radius_m": None,
            "kde_pixel_size_m": float(
                values["kde_pixel_size"]
            ),
        },
        "configs": {
            "spatial_analysis": (
                project_relative_or_absolute(
                    SPATIAL_CONFIG
                )
            ),
            "cartography": (
                project_relative_or_absolute(
                    CARTOGRAPHY_CONFIG
                )
            ),
            "report": project_relative_or_absolute(
                REPORT_CONFIG
            ),
        },
        "pipeline": {
            "run_system_check": True,
            "run_boundary_validation": True,
        },
    }


def validate_values(values: dict[str, Any]) -> None:
    """Valida todos los campos antes de generar el YAML."""

    farm_name = str(values["farm_name"]).strip()

    if not farm_name:
        raise ValueError(
            "Ingrese el nombre de la finca o lote."
        )

    orthophoto = normalize_existing_file(
        str(values["orthophoto"])
    )

    if (
        not orthophoto.is_file()
        or orthophoto.suffix.lower()
        not in {".tif", ".tiff"}
    ):
        raise FileNotFoundError(
            "La ortofoto debe ser un archivo "
            f".tif o .tiff existente: {orthophoto}"
        )

    boundary_excel = normalize_existing_file(
        str(values["boundary_excel"])
    )

    if (
        not boundary_excel.is_file()
        or boundary_excel.suffix.lower()
        not in {".xls", ".xlsx"}
    ):
        raise FileNotFoundError(
            "El límite debe ser un Excel "
            f".xls o .xlsx existente: {boundary_excel}"
        )

    model_path = normalize_existing_file(
        str(values["model_path"])
    )

    if (
        not model_path.is_file()
        or model_path.suffix.lower() != ".pt"
    ):
        raise FileNotFoundError(
            "El modelo debe ser un archivo .pt "
            f"existente: {model_path}"
        )

    if not str(values["boundary_sheet"]).strip():
        raise ValueError(
            "Indique la hoja del Excel."
        )

    target_density = float(values["target_density"])

    if target_density <= 0:
        raise ValueError(
            "La densidad objetivo debe ser mayor que cero."
        )

    tile_size = int(values["tile_size"])
    overlap = int(values["overlap"])

    if tile_size <= 0:
        raise ValueError(
            "El tamaño de tile debe ser mayor que cero."
        )

    if overlap < 0 or overlap >= tile_size:
        raise ValueError(
            "El solape debe ser igual o mayor que cero "
            "y menor que el tamaño del tile."
        )

    for key, label in (
        ("yolo_confidence", "confianza YOLO"),
        ("yolo_iou", "IoU YOLO"),
    ):
        numeric = float(values[key])

        if not 0 <= numeric <= 1:
            raise ValueError(
                f"El valor de {label} debe estar entre 0 y 1."
            )

    if float(
        values["deduplication_distance"]
    ) <= 0:
        raise ValueError(
            "La distancia de deduplicación debe ser "
            "mayor que cero."
        )

    if float(values["kde_pixel_size"]) <= 0:
        raise ValueError(
            "El tamaño de píxel KDE debe ser mayor que cero."
        )

    exclusions_gpkg = str(
        values.get("exclusions_gpkg", "")
    ).strip()
    exclusions_layer = str(
        values.get("exclusions_layer", "")
    ).strip()

    if bool(exclusions_gpkg) != bool(exclusions_layer):
        raise ValueError(
            "Seleccione nuevamente el GeoPackage de exclusiones "
            "para que la interfaz detecte sus capas."
        )

    if exclusions_gpkg:
        exclusions_path = normalize_existing_file(
            exclusions_gpkg
        )

        if (
            not exclusions_path.is_file()
            or exclusions_path.suffix.lower() != ".gpkg"
        ):
            raise FileNotFoundError(
                "Las exclusiones deben corresponder a un "
                f"GeoPackage existente: {exclusions_path}"
            )

        available_layers = list_gpkg_feature_layers(
            exclusions_path
        )

        if not available_layers:
            raise ValueError(
                "El GeoPackage no contiene capas espaciales."
            )

        if exclusions_layer == ALL_EXCLUSION_LAYERS:
            generated_path, generated_layer = (
                build_combined_exclusions(
                    source_path=exclusions_path,
                    layer_names=available_layers,
                    farm_name=farm_name,
                )
            )
            values["exclusions_gpkg"] = str(
                generated_path
            )
            values["exclusions_layer"] = (
                generated_layer
            )
        elif exclusions_layer not in available_layers:
            raise ValueError(
                "La capa seleccionada no existe en el "
                f"GeoPackage. Capas disponibles: "
                + ", ".join(available_layers)
            )
        else:
            values["exclusions_gpkg"] = str(
                exclusions_path
            )
            values["exclusions_layer"] = (
                exclusions_layer
            )

    values["report_date"] = validate_date(
        str(values.get("report_date", ""))
    )
    values["orthophoto"] = str(orthophoto)
    values["boundary_excel"] = str(boundary_excel)
    values["model_path"] = str(model_path)
    values["farm_name"] = farm_name
    values["boundary_sheet"] = str(
        values["boundary_sheet"]
    ).strip()

    if exclusions_gpkg:
        values["exclusions_gpkg"] = str(
            normalize_existing_file(
                exclusions_gpkg
            )
        )
        values["exclusions_layer"] = (
            exclusions_layer
        )

    normalize_directory(
        str(values["output_root"])
    )
    validate_installation()


def atomic_write_yaml(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Guarda el YAML mediante archivo temporal."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = path.with_suffix(
        path.suffix + ".partial"
    )

    try:
        temporary.write_text(
            yaml.safe_dump(
                payload,
                allow_unicode=True,
                sort_keys=False,
                width=110,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def open_path(path: Path) -> None:
    """Abre un archivo o carpeta con la aplicación predeterminada."""

    if not path.exists():
        raise FileNotFoundError(
            f"No existe la ruta: {path}"
        )

    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return

    command = (
        ["open", str(path)]
        if sys.platform == "darwin"
        else ["xdg-open", str(path)]
    )
    subprocess.Popen(command)


class BananaAnalyzerApp(tk.Tk):
    """Interfaz gráfica del sistema DALGORO."""

    def __init__(self) -> None:
        super().__init__()

        self.title(
            "DALGORO — Análisis automatizado de banano"
        )
        self.geometry("1180x820")
        self.minsize(1030, 720)
        self.configure(bg=BRAND_LIGHT)

        self.process: subprocess.Popen[str] | None = None
        self.worker: threading.Thread | None = None
        self.events: queue.Queue[
            tuple[str, Any]
        ] = queue.Queue()
        self.current_config_path: Path | None = None
        self.current_run_directory: Path | None = None
        self.current_report_pdf: Path | None = None
        self.process_mode: str | None = None
        self.before_run_directories: set[Path] = set()
        self.logo_image: Any = None

        self._configure_styles()
        self._create_variables()
        self._build_interface()
        self._load_last_settings()
        self._update_date_state()

        self.after(100, self._consume_events)
        self.protocol(
            "WM_DELETE_WINDOW",
            self._on_close,
        )

    def _configure_styles(self) -> None:
        style = ttk.Style(self)

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Brand.TNotebook",
            background=BRAND_LIGHT,
            borderwidth=0,
        )
        style.configure(
            "Brand.TNotebook.Tab",
            font=("Segoe UI", 10, "bold"),
            padding=(18, 10),
        )
        style.map(
            "Brand.TNotebook.Tab",
            background=[
                ("selected", BRAND_WHITE),
                ("!selected", "#DCE3E0"),
            ],
            foreground=[
                ("selected", BRAND_PRIMARY),
                ("!selected", BRAND_SECONDARY),
            ],
        )
        style.configure(
            "Brand.Horizontal.TProgressbar",
            troughcolor="#D8DEDC",
            background=BRAND_ACCENT,
            bordercolor="#D8DEDC",
            lightcolor=BRAND_ACCENT,
            darkcolor=BRAND_ACCENT,
        )
        style.configure(
            "Field.TEntry",
            padding=6,
        )
        style.configure(
            "Field.TCombobox",
            padding=5,
        )

    def _create_variables(self) -> None:
        self.farm_name = tk.StringVar()
        self.producer = tk.StringVar()
        self.orthophoto = tk.StringVar()
        self.boundary_excel = tk.StringVar()
        self.boundary_sheet = tk.StringVar(
            value="Hoja1"
        )
        self.target_density = tk.StringVar(
            value="1400"
        )
        self.model_path = tk.StringVar(
            value=(
                str(DEFAULT_MODEL_PATH)
                if DEFAULT_MODEL_PATH.is_file()
                else ""
            )
        )
        self.output_root = tk.StringVar(
            value="runs"
        )
        self.auto_report_date = tk.BooleanVar(
            value=True
        )
        self.report_date = tk.StringVar()
        self.exclusions_gpkg = tk.StringVar()
        self.exclusions_layer = tk.StringVar()
        self.exclusions_info = tk.StringVar(
            value=(
                "Sin exclusiones. Seleccione un GeoPackage "
                "solamente cuando corresponda."
            )
        )

        self.tile_size = tk.StringVar(value="640")
        self.overlap = tk.StringVar(value="128")
        self.min_valid_percent = tk.StringVar(
            value="0.0"
        )
        self.yolo_confidence = tk.StringVar(
            value="0.40"
        )
        self.yolo_iou = tk.StringVar(value="0.70")
        self.yolo_imgsz = tk.StringVar(value="640")
        self.yolo_device = tk.StringVar(
            value="auto"
        )
        self.max_detections = tk.StringVar(
            value="1000"
        )
        self.deduplication_distance = tk.StringVar(
            value="1.00"
        )
        self.kde_pixel_size = tk.StringVar(
            value="0.50"
        )

        self.status_text = tk.StringVar(
            value="Listo para configurar un análisis."
        )
        self.stage_text = tk.StringVar(
            value="Sin ejecución activa"
        )
        self.progress_value = tk.DoubleVar(
            value=0.0
        )

    def _build_interface(self) -> None:
        header = tk.Frame(
            self,
            bg=BRAND_PRIMARY,
            height=96,
        )
        header.pack(
            fill="x",
            side="top",
        )
        header.pack_propagate(False)

        logo_container = tk.Frame(
            header,
            bg=BRAND_PRIMARY,
        )
        logo_container.pack(
            side="left",
            padx=(24, 18),
            pady=14,
        )
        self._add_logo(logo_container)

        title_container = tk.Frame(
            header,
            bg=BRAND_PRIMARY,
        )
        title_container.pack(
            side="left",
            fill="y",
            pady=14,
        )

        tk.Label(
            title_container,
            text="ANÁLISIS AUTOMATIZADO DE BANANO",
            bg=BRAND_PRIMARY,
            fg=BRAND_WHITE,
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")

        tk.Label(
            title_container,
            text=(
                "Configure la finca, ejecute el análisis "
                "y abra el informe PDF desde una sola ventana."
            ),
            bg=BRAND_PRIMARY,
            fg="#DCE7E3",
            font=("Segoe UI", 10),
        ).pack(
            anchor="w",
            pady=(5, 0),
        )

        tk.Frame(
            self,
            bg=BRAND_ACCENT,
            height=4,
        ).pack(fill="x")

        content = tk.Frame(
            self,
            bg=BRAND_LIGHT,
        )
        content.pack(
            fill="both",
            expand=True,
            padx=18,
            pady=14,
        )

        self.notebook = ttk.Notebook(
            content,
            style="Brand.TNotebook",
        )
        self.notebook.pack(
            fill="both",
            expand=True,
        )

        self.data_tab = tk.Frame(
            self.notebook,
            bg=BRAND_WHITE,
        )
        self.technical_tab = tk.Frame(
            self.notebook,
            bg=BRAND_WHITE,
        )
        self.execution_tab = tk.Frame(
            self.notebook,
            bg=BRAND_WHITE,
        )

        self.notebook.add(
            self.data_tab,
            text="1. Datos de la finca",
        )
        self.notebook.add(
            self.technical_tab,
            text="2. Parámetros técnicos",
        )
        self.notebook.add(
            self.execution_tab,
            text="3. Ejecutar y obtener PDF",
        )

        self._build_data_tab()
        self._build_technical_tab()
        self._build_execution_tab()

        footer = tk.Frame(
            self,
            bg=BRAND_SECONDARY,
            height=30,
        )
        footer.pack(fill="x")
        footer.pack_propagate(False)

        tk.Label(
            footer,
            text=(
                "Desarrollado por el Ing. Darwin A. González Romero "
                f"· {BUILD_ID}"
            ),
            bg=BRAND_SECONDARY,
            fg=BRAND_WHITE,
            font=("Segoe UI", 8),
        ).pack(
            side="right",
            padx=14,
            pady=6,
        )

    def _add_logo(self, parent: tk.Widget) -> None:
        logo_path = (
            PROJECT_ROOT
            / "resources"
            / "branding"
            / "dalgoro_logo_horizontal.jpg"
        )

        if logo_path.is_file():
            try:
                from PIL import Image, ImageTk

                image = Image.open(logo_path)
                image.thumbnail((225, 62))
                self.logo_image = ImageTk.PhotoImage(
                    image
                )
                tk.Label(
                    parent,
                    image=self.logo_image,
                    bg=BRAND_PRIMARY,
                ).pack()
                return
            except Exception:
                pass

        tk.Label(
            parent,
            text="DALGORO",
            bg=BRAND_PRIMARY,
            fg=BRAND_WHITE,
            font=("Segoe UI", 22, "bold"),
        ).pack()

        tk.Label(
            parent,
            text="Innovación y Sostenibilidad",
            bg=BRAND_PRIMARY,
            fg=BRAND_ACCENT,
            font=("Segoe UI", 8, "bold"),
        ).pack()

    def _section_title(
        self,
        parent: tk.Widget,
        title: str,
        description: str,
    ) -> tk.Frame:
        container = tk.Frame(
            parent,
            bg=BRAND_WHITE,
        )
        container.pack(
            fill="x",
            padx=24,
            pady=(20, 10),
        )

        tk.Label(
            container,
            text=title,
            bg=BRAND_WHITE,
            fg=BRAND_PRIMARY,
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")

        tk.Label(
            container,
            text=description,
            bg=BRAND_WHITE,
            fg="#52615D",
            font=("Segoe UI", 9),
            justify="left",
        ).pack(
            anchor="w",
            pady=(4, 0),
        )
        return container

    def _field_row(
        self,
        parent: tk.Widget,
        row: int,
        label: str,
        variable: tk.StringVar,
        *,
        browse_command: Any = None,
        width: int = 58,
        entry_state: str = "normal",
    ) -> ttk.Entry:
        tk.Label(
            parent,
            text=label,
            bg=BRAND_WHITE,
            fg=BRAND_SECONDARY,
            font=("Segoe UI", 9, "bold"),
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=7,
        )

        entry = ttk.Entry(
            parent,
            textvariable=variable,
            width=width,
            style="Field.TEntry",
            state=entry_state,
        )
        entry.grid(
            row=row,
            column=1,
            sticky="ew",
            pady=7,
        )

        if browse_command is not None:
            button = tk.Button(
                parent,
                text="Examinar…",
                command=browse_command,
                bg="#E6ECE9",
                fg=BRAND_PRIMARY,
                activebackground="#D5DEDA",
                activeforeground=BRAND_PRIMARY,
                relief="flat",
                padx=12,
                pady=5,
                cursor="hand2",
            )
            button.grid(
                row=row,
                column=2,
                padx=(10, 0),
                pady=7,
            )

        return entry

    def _build_data_tab(self) -> None:
        self._section_title(
            self.data_tab,
            "Información principal",
            (
                "Complete los datos de la finca. Los campos de rutas "
                "pueden seleccionarse con el botón Examinar."
            ),
        )

        form = tk.Frame(
            self.data_tab,
            bg=BRAND_WHITE,
        )
        form.pack(
            fill="x",
            padx=28,
            pady=(0, 14),
        )
        form.columnconfigure(1, weight=1)

        self._field_row(
            form,
            0,
            "Nombre de finca o lote *",
            self.farm_name,
        )
        self._field_row(
            form,
            1,
            "Productor o empresa",
            self.producer,
        )
        self._field_row(
            form,
            2,
            "Ortofoto GeoTIFF *",
            self.orthophoto,
            browse_command=self._browse_orthophoto,
        )
        self._field_row(
            form,
            3,
            "Excel de coordenadas *",
            self.boundary_excel,
            browse_command=self._browse_boundary_excel,
        )
        self._field_row(
            form,
            4,
            "Hoja del Excel *",
            self.boundary_sheet,
        )
        self._field_row(
            form,
            5,
            "Densidad objetivo (plantas/ha) *",
            self.target_density,
        )
        self._field_row(
            form,
            6,
            "Modelo YOLO best.pt *",
            self.model_path,
            browse_command=self._browse_model,
        )
        self._field_row(
            form,
            7,
            "Carpeta de ejecuciones *",
            self.output_root,
            browse_command=self._browse_output_root,
        )

        date_frame = tk.Frame(
            form,
            bg=BRAND_WHITE,
        )
        date_frame.grid(
            row=8,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=7,
        )

        tk.Label(
            form,
            text="Fecha del informe",
            bg=BRAND_WHITE,
            fg=BRAND_SECONDARY,
            font=("Segoe UI", 9, "bold"),
        ).grid(
            row=8,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=7,
        )

        self.report_date_entry = ttk.Entry(
            date_frame,
            textvariable=self.report_date,
            width=22,
            style="Field.TEntry",
        )
        self.report_date_entry.pack(
            side="left",
        )

        tk.Checkbutton(
            date_frame,
            text="Usar fecha automática",
            variable=self.auto_report_date,
            command=self._update_date_state,
            bg=BRAND_WHITE,
            fg=BRAND_SECONDARY,
            activebackground=BRAND_WHITE,
            selectcolor=BRAND_WHITE,
            font=("Segoe UI", 9),
        ).pack(
            side="left",
            padx=(16, 0),
        )

        exclusion = tk.LabelFrame(
            self.data_tab,
            text="Exclusiones opcionales",
            bg=BRAND_WHITE,
            fg=BRAND_PRIMARY,
            font=("Segoe UI", 10, "bold"),
            padx=14,
            pady=8,
        )
        exclusion.pack(
            fill="x",
            padx=28,
            pady=(0, 18),
        )
        exclusion.columnconfigure(1, weight=1)

        self._field_row(
            exclusion,
            0,
            "GeoPackage de vías/canales",
            self.exclusions_gpkg,
            browse_command=self._browse_exclusions,
        )

        tk.Label(
            exclusion,
            textvariable=self.exclusions_info,
            bg=BRAND_WHITE,
            fg="#52615D",
            font=("Segoe UI", 8, "bold"),
            justify="left",
            wraplength=1000,
        ).grid(
            row=1,
            column=1,
            columnspan=2,
            sticky="w",
            pady=(2, 4),
        )

    def _technical_field(
        self,
        parent: tk.Widget,
        row: int,
        label: str,
        variable: tk.StringVar,
        help_text: str,
    ) -> None:
        tk.Label(
            parent,
            text=label,
            bg=BRAND_WHITE,
            fg=BRAND_SECONDARY,
            font=("Segoe UI", 9, "bold"),
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=7,
        )

        ttk.Entry(
            parent,
            textvariable=variable,
            width=18,
            style="Field.TEntry",
        ).grid(
            row=row,
            column=1,
            sticky="w",
            pady=7,
        )

        tk.Label(
            parent,
            text=help_text,
            bg=BRAND_WHITE,
            fg="#697672",
            font=("Segoe UI", 8),
            anchor="w",
        ).grid(
            row=row,
            column=2,
            sticky="w",
            padx=(14, 0),
            pady=7,
        )

    def _build_technical_tab(self) -> None:
        self._section_title(
            self.technical_tab,
            "Parámetros técnicos",
            (
                "Los valores mostrados corresponden a la configuración "
                "validada. Manténgalos durante las primeras ejecuciones."
            ),
        )

        form = tk.Frame(
            self.technical_tab,
            bg=BRAND_WHITE,
        )
        form.pack(
            fill="x",
            padx=34,
            pady=(4, 18),
        )
        form.columnconfigure(2, weight=1)

        self._technical_field(
            form,
            0,
            "Tamaño de tile",
            self.tile_size,
            "640 píxeles",
        )
        self._technical_field(
            form,
            1,
            "Solape",
            self.overlap,
            "128 píxeles",
        )
        self._technical_field(
            form,
            2,
            "Área válida mínima",
            self.min_valid_percent,
            "0 omite únicamente tiles completamente vacíos",
        )
        self._technical_field(
            form,
            3,
            "Confianza YOLO",
            self.yolo_confidence,
            "0.40",
        )
        self._technical_field(
            form,
            4,
            "IoU YOLO",
            self.yolo_iou,
            "0.70",
        )
        self._technical_field(
            form,
            5,
            "Tamaño de inferencia",
            self.yolo_imgsz,
            "640 píxeles",
        )

        tk.Label(
            form,
            text="Dispositivo",
            bg=BRAND_WHITE,
            fg=BRAND_SECONDARY,
            font=("Segoe UI", 9, "bold"),
        ).grid(
            row=6,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=7,
        )

        ttk.Combobox(
            form,
            textvariable=self.yolo_device,
            values=("auto", "cpu", "cuda", "0"),
            state="readonly",
            width=16,
            style="Field.TCombobox",
        ).grid(
            row=6,
            column=1,
            sticky="w",
            pady=7,
        )

        tk.Label(
            form,
            text=(
                "auto selecciona CPU cuando CUDA no está disponible"
            ),
            bg=BRAND_WHITE,
            fg="#697672",
            font=("Segoe UI", 8),
        ).grid(
            row=6,
            column=2,
            sticky="w",
            padx=(14, 0),
            pady=7,
        )

        self._technical_field(
            form,
            7,
            "Máximo de detecciones",
            self.max_detections,
            "1000 por tile",
        )
        self._technical_field(
            form,
            8,
            "Deduplicación",
            self.deduplication_distance,
            "1.00 metros",
        )
        self._technical_field(
            form,
            9,
            "Píxel KDE",
            self.kde_pixel_size,
            "0.50 metros",
        )

        warning = tk.Frame(
            self.technical_tab,
            bg="#FFF7EB",
            highlightbackground="#E4C897",
            highlightthickness=1,
        )
        warning.pack(
            fill="x",
            padx=34,
            pady=(0, 18),
        )

        tk.Label(
            warning,
            text="Recomendación",
            bg="#FFF7EB",
            fg="#7B4D20",
            font=("Segoe UI", 10, "bold"),
        ).pack(
            anchor="w",
            padx=14,
            pady=(10, 2),
        )

        tk.Label(
            warning,
            text=(
                "Cambie estos valores solamente cuando exista una "
                "evaluación técnica documentada. La interfaz guarda "
                "cada finca en una configuración independiente."
            ),
            bg="#FFF7EB",
            fg="#6F553D",
            font=("Segoe UI", 9),
            justify="left",
            wraplength=930,
        ).pack(
            anchor="w",
            padx=14,
            pady=(0, 10),
        )

    def _build_execution_tab(self) -> None:
        self._section_title(
            self.execution_tab,
            "Ejecución del análisis",
            (
                "Primero puede validar los datos sin procesar. Luego "
                "ejecute el flujo completo y abra el PDF resultante."
            ),
        )

        control = tk.Frame(
            self.execution_tab,
            bg=BRAND_WHITE,
        )
        control.pack(
            fill="x",
            padx=26,
            pady=(0, 10),
        )

        self.save_button = self._action_button(
            control,
            "Guardar configuración",
            self._save_configuration_only,
            BRAND_PRIMARY,
        )
        self.save_button.pack(
            side="left",
            padx=(0, 8),
        )

        self.validate_button = self._action_button(
            control,
            "Validar sin procesar",
            self._start_dry_run,
            "#44645C",
        )
        self.validate_button.pack(
            side="left",
            padx=8,
        )

        self.run_button = self._action_button(
            control,
            "Ejecutar análisis completo",
            self._start_full_run,
            BRAND_ACCENT,
        )
        self.run_button.pack(
            side="left",
            padx=8,
        )

        self.resume_button = self._action_button(
            control,
            "Reanudar ejecución",
            self._choose_resume_run,
            "#546A7B",
        )
        self.resume_button.pack(
            side="left",
            padx=8,
        )

        self.stop_button = self._action_button(
            control,
            "Detener",
            self._stop_process,
            BRAND_ERROR,
        )
        self.stop_button.pack(
            side="right",
        )
        self.stop_button.configure(state="disabled")

        status_card = tk.Frame(
            self.execution_tab,
            bg="#EEF2F0",
            highlightbackground="#CFD8D4",
            highlightthickness=1,
        )
        status_card.pack(
            fill="x",
            padx=26,
            pady=(2, 10),
        )

        tk.Label(
            status_card,
            textvariable=self.stage_text,
            bg="#EEF2F0",
            fg=BRAND_PRIMARY,
            font=("Segoe UI", 11, "bold"),
        ).pack(
            anchor="w",
            padx=14,
            pady=(10, 4),
        )

        ttk.Progressbar(
            status_card,
            variable=self.progress_value,
            maximum=100,
            style="Brand.Horizontal.TProgressbar",
        ).pack(
            fill="x",
            padx=14,
            pady=(0, 7),
        )

        tk.Label(
            status_card,
            textvariable=self.status_text,
            bg="#EEF2F0",
            fg="#4E5C58",
            font=("Segoe UI", 9),
            wraplength=1020,
            justify="left",
        ).pack(
            anchor="w",
            padx=14,
            pady=(0, 10),
        )

        log_frame = tk.Frame(
            self.execution_tab,
            bg=BRAND_WHITE,
        )
        log_frame.pack(
            fill="both",
            expand=True,
            padx=26,
            pady=(0, 10),
        )

        self.log_text = tk.Text(
            log_frame,
            bg="#172522",
            fg="#E7F0ED",
            insertbackground=BRAND_WHITE,
            font=("Consolas", 9),
            wrap="word",
            relief="flat",
            padx=10,
            pady=8,
            height=17,
        )
        scrollbar = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_text.yview,
        )
        self.log_text.configure(
            yscrollcommand=scrollbar.set
        )
        self.log_text.pack(
            side="left",
            fill="both",
            expand=True,
        )
        scrollbar.pack(
            side="right",
            fill="y",
        )

        result_controls = tk.Frame(
            self.execution_tab,
            bg=BRAND_WHITE,
        )
        result_controls.pack(
            fill="x",
            padx=26,
            pady=(0, 16),
        )

        self.open_report_button = (
            self._action_button(
                result_controls,
                "Abrir informe PDF",
                self._open_report,
                BRAND_SUCCESS,
            )
        )
        self.open_report_button.pack(
            side="left",
            padx=(0, 8),
        )
        self.open_report_button.configure(
            state="disabled"
        )

        self.open_run_button = self._action_button(
            result_controls,
            "Abrir carpeta de resultados",
            self._open_run_directory,
            "#536B64",
        )
        self.open_run_button.pack(
            side="left",
            padx=8,
        )
        self.open_run_button.configure(
            state="disabled"
        )

        self.clear_log_button = self._action_button(
            result_controls,
            "Limpiar registro",
            self._clear_log,
            "#7C8582",
        )
        self.clear_log_button.pack(
            side="right",
        )

    def _action_button(
        self,
        parent: tk.Widget,
        text: str,
        command: Any,
        background: str,
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=BRAND_WHITE,
            activebackground=background,
            activeforeground=BRAND_WHITE,
            disabledforeground="#CED5D2",
            relief="flat",
            padx=13,
            pady=8,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )

    def _browse_orthophoto(self) -> None:
        path = filedialog.askopenfilename(
            title="Seleccionar ortofoto",
            filetypes=[
                (
                    "GeoTIFF",
                    "*.tif *.tiff",
                ),
                ("Todos los archivos", "*.*"),
            ],
        )

        if path:
            self.orthophoto.set(path)

    def _browse_boundary_excel(self) -> None:
        path = filedialog.askopenfilename(
            title="Seleccionar Excel de coordenadas",
            filetypes=[
                (
                    "Excel",
                    "*.xls *.xlsx",
                ),
                ("Todos los archivos", "*.*"),
            ],
        )

        if path:
            self.boundary_excel.set(path)

    def _browse_model(self) -> None:
        path = filedialog.askopenfilename(
            title="Seleccionar modelo YOLO",
            filetypes=[
                ("Modelo PyTorch", "*.pt"),
                ("Todos los archivos", "*.*"),
            ],
        )

        if path:
            self.model_path.set(path)

    def _browse_output_root(self) -> None:
        path = filedialog.askdirectory(
            title="Seleccionar carpeta de ejecuciones",
        )

        if path:
            self.output_root.set(path)

    def _browse_exclusions(self) -> None:
        path = filedialog.askopenfilename(
            title="Seleccionar GeoPackage de exclusiones",
            filetypes=[
                ("GeoPackage", "*.gpkg"),
                ("Todos los archivos", "*.*"),
            ],
        )

        if not path:
            return

        self.exclusions_gpkg.set(path)
        self._detect_exclusion_layers(
            show_message=True
        )

    def _detect_exclusion_layers(
        self,
        *,
        show_message: bool,
    ) -> None:
        raw_path = self.exclusions_gpkg.get().strip()

        if not raw_path:
            self.exclusions_layer.set("")
            self.exclusions_info.set(
                "Sin exclusiones. Seleccione un GeoPackage "
                "solamente cuando corresponda."
            )
            return

        try:
            path = normalize_existing_file(
                raw_path
            )

            if (
                not path.is_file()
                or path.suffix.lower() != ".gpkg"
            ):
                raise FileNotFoundError(
                    f"GeoPackage no válido: {path}"
                )

            layers = list_gpkg_feature_layers(
                path
            )

            if not layers:
                raise ValueError(
                    "El archivo no contiene capas espaciales."
                )

            if len(layers) == 1:
                self.exclusions_layer.set(
                    layers[0]
                )
                self.exclusions_info.set(
                    "Capa espacial detectada: "
                    f"{layers[0]}."
                )
            else:
                self.exclusions_layer.set(
                    ALL_EXCLUSION_LAYERS
                )
                self.exclusions_info.set(
                    "Se detectaron varias capas y se combinarán "
                    "automáticamente en una sola exclusión: "
                    + ", ".join(layers)
                    + "."
                )

            if show_message:
                messagebox.showinfo(
                    "Exclusiones detectadas",
                    self.exclusions_info.get(),
                    parent=self,
                )

        except Exception as error:
            self.exclusions_layer.set("")
            self.exclusions_info.set(
                "No fue posible detectar las capas."
            )

            if show_message:
                messagebox.showerror(
                    "GeoPackage no válido",
                    f"{type(error).__name__}: {error}",
                    parent=self,
                )

    def _update_date_state(self) -> None:
        if self.auto_report_date.get():
            self.report_date.set("")
            self.report_date_entry.configure(
                state="disabled"
            )
        else:
            self.report_date_entry.configure(
                state="normal"
            )

    def _collect_values(self) -> dict[str, Any]:
        return {
            "farm_name": self.farm_name.get().strip(),
            "producer": self.producer.get().strip(),
            "orthophoto": self.orthophoto.get().strip(),
            "boundary_excel": (
                self.boundary_excel.get().strip()
            ),
            "boundary_sheet": (
                self.boundary_sheet.get().strip()
            ),
            "target_density": (
                self.target_density.get().strip()
            ),
            "model_path": self.model_path.get().strip(),
            "output_root": self.output_root.get().strip(),
            "report_date": (
                ""
                if self.auto_report_date.get()
                else self.report_date.get().strip()
            ),
            "exclusions_gpkg": (
                self.exclusions_gpkg.get().strip()
            ),
            "exclusions_layer": (
                self.exclusions_layer.get().strip()
            ),
            "tile_size": self.tile_size.get().strip(),
            "overlap": self.overlap.get().strip(),
            "min_valid_percent": (
                self.min_valid_percent.get().strip()
            ),
            "yolo_confidence": (
                self.yolo_confidence.get().strip()
            ),
            "yolo_iou": self.yolo_iou.get().strip(),
            "yolo_imgsz": self.yolo_imgsz.get().strip(),
            "yolo_device": (
                self.yolo_device.get().strip()
            ),
            "max_detections": (
                self.max_detections.get().strip()
            ),
            "deduplication_distance": (
                self.deduplication_distance.get().strip()
            ),
            "kde_pixel_size": (
                self.kde_pixel_size.get().strip()
            ),
        }

    def _save_configuration(
        self,
        *,
        ask_overwrite: bool,
    ) -> Path:
        values = self._collect_values()
        validate_values(values)
        config = build_pipeline_config(values)

        safe_name = sanitize_name(
            str(values["farm_name"])
        )
        path = (
            CONFIG_DIRECTORY
            / f"pipeline_config_{safe_name}.yaml"
        )

        if path.exists() and ask_overwrite:
            replace = messagebox.askyesno(
                "Configuración existente",
                (
                    "Ya existe una configuración para esta "
                    "finca.\n\n"
                    f"{path}\n\n"
                    "¿Desea reemplazarla?"
                ),
                parent=self,
            )

            if not replace:
                alternative = (
                    CONFIG_DIRECTORY
                    / (
                        f"pipeline_config_{safe_name}_"
                        + datetime.now().strftime(
                            "%Y%m%d_%H%M%S"
                        )
                        + ".yaml"
                    )
                )
                path = alternative

        atomic_write_yaml(path, config)
        self.current_config_path = path
        self._save_last_settings()
        return path

    def _save_configuration_only(self) -> None:
        try:
            path = self._save_configuration(
                ask_overwrite=True
            )
        except Exception as error:
            messagebox.showerror(
                "No se guardó la configuración",
                f"{type(error).__name__}: {error}",
                parent=self,
            )
            return

        self.status_text.set(
            f"Configuración guardada: {path}"
        )
        messagebox.showinfo(
            "Configuración guardada",
            (
                "La configuración fue validada y guardada "
                f"correctamente.\n\n{path}"
            ),
            parent=self,
        )

    def _start_dry_run(self) -> None:
        self._start_pipeline(mode="dry_run")

    def _start_full_run(self) -> None:
        confirmed = messagebox.askyesno(
            "Iniciar análisis completo",
            (
                "Se ejecutarán todas las etapas, incluida la "
                "inferencia YOLO y la generación del PDF.\n\n"
                "El proceso puede demorar y debe mantenerse "
                "el equipo encendido.\n\n"
                "¿Desea continuar?"
            ),
            parent=self,
        )

        if confirmed:
            self._start_pipeline(mode="full")

    def _choose_resume_run(self) -> None:
        directory = filedialog.askdirectory(
            title="Seleccionar ejecución para reanudar",
            initialdir=(
                str(RUNS_DIRECTORY)
                if RUNS_DIRECTORY.is_dir()
                else str(PROJECT_ROOT)
            ),
        )

        if not directory:
            return

        run_directory = Path(directory).resolve(
            strict=False
        )

        if not (
            run_directory / "estado_pipeline.json"
        ).is_file():
            messagebox.showerror(
                "Ejecución no válida",
                (
                    "La carpeta seleccionada no contiene "
                    "estado_pipeline.json."
                ),
                parent=self,
            )
            return

        self._start_pipeline(
            mode="resume",
            resume_directory=run_directory,
        )

    def _start_pipeline(
        self,
        *,
        mode: str,
        resume_directory: Path | None = None,
    ) -> None:
        if self.process is not None:
            messagebox.showwarning(
                "Proceso activo",
                "Ya existe una ejecución en curso.",
                parent=self,
            )
            return

        try:
            if mode == "resume":
                assert resume_directory is not None
                snapshot = (
                    resume_directory
                    / "configuracion_analisis.yaml"
                )

                if not snapshot.is_file():
                    raise FileNotFoundError(
                        "La ejecución no contiene "
                        "configuracion_analisis.yaml. "
                        "No es seguro reanudarla desde la interfaz."
                    )

                config_path = snapshot
                output_root = resume_directory.parent
                self.before_run_directories = {
                    path.resolve(strict=False)
                    for path in output_root.iterdir()
                    if path.is_dir()
                }
            else:
                config_path = self._save_configuration(
                    ask_overwrite=False
                )
                values = self._collect_values()
                output_root = normalize_directory(
                    values["output_root"]
                )
                output_root.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                self.before_run_directories = {
                    path.resolve(strict=False)
                    for path in output_root.iterdir()
                    if path.is_dir()
                }
        except Exception as error:
            messagebox.showerror(
                "Datos incompletos o inválidos",
                f"{type(error).__name__}: {error}",
                parent=self,
            )

            if mode != "resume":
                self.notebook.select(self.data_tab)

            return

        command = [
            sys.executable,
            str(MAIN_FILE),
            "run-full-analysis",
            str(config_path),
        ]

        if mode == "dry_run":
            command.append("--dry-run")
        elif mode == "resume":
            assert resume_directory is not None
            command.extend(
                [
                    "--resume-run",
                    str(resume_directory),
                ]
            )
            self.current_run_directory = (
                resume_directory
            )

        self.current_report_pdf = None
        self.process_mode = mode
        self.progress_value.set(0.0)
        self._clear_log()
        self.notebook.select(self.execution_tab)

        label = {
            "dry_run": "Validando configuración",
            "full": "Iniciando análisis completo",
            "resume": "Reanudando ejecución",
        }[mode]

        self.stage_text.set(label)
        self.status_text.set(
            "Preparando el proceso…"
        )
        self._set_running_state(True)

        self.worker = threading.Thread(
            target=self._run_subprocess_worker,
            args=(
                command,
                mode,
                resume_directory,
                output_root,
            ),
            daemon=True,
        )
        self.worker.start()

    def _run_subprocess_worker(
        self,
        command: list[str],
        mode: str,
        resume_directory: Path | None,
        output_root: Path,
    ) -> None:
        creationflags = 0

        if os.name == "nt":
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
            )

        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"

        try:
            self.process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                env=environment,
            )

            assert self.process.stdout is not None

            for line in self.process.stdout:
                self.events.put(("line", line))

            return_code = self.process.wait()

            detected_run = resume_directory

            if mode == "full":
                detected_run = self._detect_new_run(
                    output_root
                )

            report_pdf = None

            if detected_run is not None:
                report_pdf = self._find_report_pdf(
                    detected_run
                )

            self.events.put(
                (
                    "finished",
                    {
                        "return_code": return_code,
                        "mode": mode,
                        "run_directory": detected_run,
                        "report_pdf": report_pdf,
                    },
                )
            )

        except Exception as error:
            self.events.put(
                (
                    "worker_error",
                    (
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                )
            )
        finally:
            self.process = None

    def _detect_new_run(
        self,
        output_root: Path,
    ) -> Path | None:
        if not output_root.is_dir():
            return None

        current = {
            path.resolve(strict=False)
            for path in output_root.iterdir()
            if path.is_dir()
        }
        new_directories = list(
            current.difference(
                self.before_run_directories
            )
        )

        candidates = (
            new_directories
            if new_directories
            else list(current)
        )
        candidates = [
            path
            for path in candidates
            if (
                path / "estado_pipeline.json"
            ).is_file()
        ]

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda path: path.stat().st_mtime,
        )

    def _find_report_pdf(
        self,
        run_directory: Path,
    ) -> Path | None:
        manifest = (
            run_directory / "manifiesto_pipeline.json"
        )

        if manifest.is_file():
            try:
                loaded = json.loads(
                    manifest.read_text(
                        encoding="utf-8"
                    )
                )
                report_value = (
                    loaded.get("artifacts", {})
                    .get("technical_report_pdf")
                )

                if report_value:
                    report_path = Path(
                        str(report_value)
                    )

                    if report_path.is_file():
                        return report_path
            except Exception:
                pass

        matches = sorted(
            (
                run_directory / "07_reporte"
            ).rglob("informe_tecnico_*.pdf"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return matches[0] if matches else None

    def _consume_events(self) -> None:
        try:
            while True:
                event, payload = (
                    self.events.get_nowait()
                )

                if event == "line":
                    self._handle_output_line(
                        str(payload)
                    )
                elif event == "finished":
                    self._handle_finished(
                        dict(payload)
                    )
                elif event == "worker_error":
                    self._handle_worker_error(
                        str(payload)
                    )
        except queue.Empty:
            pass

        self.after(100, self._consume_events)

    def _handle_output_line(self, line: str) -> None:
        self.log_text.insert("end", line)
        self.log_text.see("end")

        stripped = line.strip()

        if stripped.startswith("ETAPA:"):
            title = stripped.split(
                "ETAPA:",
                1,
            )[1].strip()
            self._update_stage_progress(title)
            return

        if stripped.startswith("[OMITIDA]"):
            self.status_text.set(stripped)
            return

        if stripped.startswith("[COMPLETADA]"):
            self.status_text.set(stripped)
            return

        if (
            "ANÁLISIS AUTOMÁTICO COMPLETADO"
            in stripped
        ):
            self.progress_value.set(100.0)
            self.stage_text.set(
                "Análisis completo"
            )
            return

        if stripped.startswith("PIPELINE DETENIDO"):
            self.stage_text.set(
                "Proceso detenido por un error"
            )
            return

        if stripped.startswith("Resultado:"):
            self.status_text.set(stripped)

    def _update_stage_progress(
        self,
        title: str,
    ) -> None:
        index = None

        for position, expected in enumerate(
            STAGE_TITLES,
            start=1,
        ):
            if (
                expected.lower() == title.lower()
                or expected.lower() in title.lower()
                or title.lower() in expected.lower()
            ):
                index = position
                break

        if index is None:
            self.stage_text.set(title)
            self.status_text.set(
                "Etapa en ejecución…"
            )
            return

        percent = (
            (index - 1)
            / len(STAGE_TITLES)
            * 100
        )
        self.progress_value.set(percent)
        self.stage_text.set(
            f"Etapa {index} de "
            f"{len(STAGE_TITLES)}: {title}"
        )
        self.status_text.set(
            "Procesando. No cierre la aplicación."
        )

    def _handle_finished(
        self,
        payload: dict[str, Any],
    ) -> None:
        self._set_running_state(False)

        return_code = int(
            payload["return_code"]
        )
        mode = str(payload["mode"])
        run_directory = payload.get(
            "run_directory"
        )
        report_pdf = payload.get("report_pdf")

        if run_directory:
            self.current_run_directory = Path(
                run_directory
            )
            self.open_run_button.configure(
                state="normal"
            )

        if report_pdf:
            self.current_report_pdf = Path(
                report_pdf
            )
            self.open_report_button.configure(
                state="normal"
            )

        if return_code == 0:
            if mode == "dry_run":
                self.progress_value.set(100.0)
                self.stage_text.set(
                    "Validación completada"
                )
                self.status_text.set(
                    "Los datos y configuraciones fueron "
                    "validados sin procesar la ortofoto."
                )
                messagebox.showinfo(
                    "Validación correcta",
                    (
                        "La configuración está lista para "
                        "ejecutar el análisis completo."
                    ),
                    parent=self,
                )
                return

            self.progress_value.set(100.0)
            self.stage_text.set(
                "Proceso finalizado"
            )

            if self.current_report_pdf:
                self.status_text.set(
                    "El análisis terminó y el informe PDF "
                    "está disponible."
                )
                open_now = messagebox.askyesno(
                    "Informe generado",
                    (
                        "El análisis terminó correctamente y "
                        "se encontró el informe PDF.\n\n"
                        "¿Desea abrirlo ahora?"
                    ),
                    parent=self,
                )

                if open_now:
                    self._open_report()
            else:
                self.status_text.set(
                    "El proceso terminó, pero la interfaz no "
                    "localizó automáticamente el PDF. Revise "
                    "la carpeta de resultados."
                )
                messagebox.showwarning(
                    "Proceso terminado",
                    (
                        "El proceso devolvió código 0, pero no "
                        "se localizó automáticamente el PDF."
                    ),
                    parent=self,
                )
            return

        self.stage_text.set(
            "Proceso detenido"
        )
        self.status_text.set(
            "La ejecución se detuvo. Revise las últimas "
            "líneas del registro y reanude después de "
            "corregir la causa."
        )
        messagebox.showerror(
            "El análisis no terminó",
            (
                f"El proceso finalizó con código "
                f"{return_code}.\n\n"
                "Los resultados ya completados se conservan. "
                "Puede utilizar Reanudar ejecución."
            ),
            parent=self,
        )

    def _handle_worker_error(
        self,
        message: str,
    ) -> None:
        self._set_running_state(False)
        self.stage_text.set(
            "Error de la interfaz"
        )
        self.status_text.set(message)
        messagebox.showerror(
            "No fue posible iniciar el proceso",
            message,
            parent=self,
        )

    def _set_running_state(
        self,
        running: bool,
    ) -> None:
        normal = "disabled" if running else "normal"

        for button in (
            self.save_button,
            self.validate_button,
            self.run_button,
            self.resume_button,
        ):
            button.configure(state=normal)

        self.stop_button.configure(
            state=(
                "normal"
                if running
                else "disabled"
            )
        )

        if running:
            self.open_report_button.configure(
                state="disabled"
            )

    def _stop_process(self) -> None:
        process = self.process

        if process is None:
            return

        confirmed = messagebox.askyesno(
            "Detener procesamiento",
            (
                "La etapa actual será interrumpida. Las "
                "etapas completadas se conservarán y podrá "
                "reanudar posteriormente.\n\n"
                "¿Desea detenerla?"
            ),
            parent=self,
        )

        if not confirmed:
            return

        try:
            if os.name == "nt":
                subprocess.run(
                    [
                        "taskkill",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ],
                    capture_output=True,
                    text=True,
                )
            else:
                os.killpg(
                    os.getpgid(process.pid),
                    signal.SIGTERM,
                )

            self.status_text.set(
                "Se solicitó detener el proceso…"
            )
        except Exception as error:
            messagebox.showerror(
                "No se pudo detener",
                f"{type(error).__name__}: {error}",
                parent=self,
            )

    def _open_report(self) -> None:
        if self.current_report_pdf is None:
            return

        try:
            open_path(self.current_report_pdf)
        except Exception as error:
            messagebox.showerror(
                "No se pudo abrir el PDF",
                f"{type(error).__name__}: {error}",
                parent=self,
            )

    def _open_run_directory(self) -> None:
        if self.current_run_directory is None:
            return

        try:
            open_path(self.current_run_directory)
        except Exception as error:
            messagebox.showerror(
                "No se pudo abrir la carpeta",
                f"{type(error).__name__}: {error}",
                parent=self,
            )

    def _clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    def _save_last_settings(self) -> None:
        CONFIG_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )
        settings = self._collect_values()
        settings["auto_report_date"] = (
            self.auto_report_date.get()
        )

        temporary = SETTINGS_FILE.with_suffix(
            ".json.partial"
        )

        try:
            temporary.write_text(
                json.dumps(
                    settings,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            temporary.replace(SETTINGS_FILE)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _load_last_settings(self) -> None:
        if not SETTINGS_FILE.is_file():
            return

        try:
            settings = json.loads(
                SETTINGS_FILE.read_text(
                    encoding="utf-8"
                )
            )

            mapping = {
                "farm_name": self.farm_name,
                "producer": self.producer,
                "orthophoto": self.orthophoto,
                "boundary_excel": (
                    self.boundary_excel
                ),
                "boundary_sheet": (
                    self.boundary_sheet
                ),
                "target_density": (
                    self.target_density
                ),
                "model_path": self.model_path,
                "output_root": self.output_root,
                "report_date": self.report_date,
                "exclusions_gpkg": (
                    self.exclusions_gpkg
                ),
                "exclusions_layer": (
                    self.exclusions_layer
                ),
                "tile_size": self.tile_size,
                "overlap": self.overlap,
                "min_valid_percent": (
                    self.min_valid_percent
                ),
                "yolo_confidence": (
                    self.yolo_confidence
                ),
                "yolo_iou": self.yolo_iou,
                "yolo_imgsz": self.yolo_imgsz,
                "yolo_device": self.yolo_device,
                "max_detections": (
                    self.max_detections
                ),
                "deduplication_distance": (
                    self.deduplication_distance
                ),
                "kde_pixel_size": (
                    self.kde_pixel_size
                ),
            }

            for key, variable in mapping.items():
                value = settings.get(key)

                if value not in (None, ""):
                    variable.set(str(value))

            self.auto_report_date.set(
                bool(
                    settings.get(
                        "auto_report_date",
                        True,
                    )
                )
            )
            if self.exclusions_gpkg.get().strip():
                self._detect_exclusion_layers(
                    show_message=False
                )
        except Exception:
            return

    def _on_close(self) -> None:
        if self.process is not None:
            messagebox.showwarning(
                "Proceso en ejecución",
                (
                    "Detenga el proceso desde la interfaz "
                    "antes de cerrar la ventana."
                ),
                parent=self,
            )
            return

        try:
            self._save_last_settings()
        except Exception:
            pass

        self.destroy()


def build_parser() -> argparse.ArgumentParser:
    """Argumentos auxiliares para diagnóstico."""

    parser = argparse.ArgumentParser(
        description=(
            "Interfaz gráfica DALGORO para el análisis "
            "automatizado de plantaciones de banano."
        )
    )
    parser.add_argument(
        "--show-build",
        action="store_true",
    )
    parser.add_argument(
        "--validate-installation",
        action="store_true",
    )
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.show_build:
        print(BUILD_ID)
        return 0

    if arguments.validate_installation:
        try:
            messages = validate_installation()
        except Exception as error:
            print(
                f"ERROR: {type(error).__name__}: "
                f"{error}"
            )
            return 1

        print("INSTALACIÓN VÁLIDA")

        for message in messages:
            print(f"- {message}")

        return 0

    app = BananaAnalyzerApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
