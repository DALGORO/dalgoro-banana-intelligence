# Fase 11 — Configuración reutilizable para una finca nueva

## Archivos

- `crear_config_finca.py`: asistente interactivo.
- `pipeline_config_PLANTILLA.yaml`: modelo editable manualmente.

## Ubicación recomendada

```text
automatizacion_banano/
├── crear_config_finca.py
└── config/
    └── pipeline_config_PLANTILLA.yaml
```

## Método recomendado: asistente interactivo

Desde la raíz del proyecto y con `.venv` activa:

```powershell
python .\crear_config_finca.py
```

El asistente solicitará:

1. Nombre de finca o lote.
2. Productor o empresa.
3. Ortofoto `.tif` o `.tiff`.
4. Excel de coordenadas `.xls` o `.xlsx`.
5. Hoja del Excel.
6. Densidad objetivo.
7. Modelo `best.pt`.
8. Fecha del informe o fecha automática.
9. Capa de exclusiones, cuando exista.
10. Nombre del YAML de salida.

Antes de escribir el archivo valida:

- Existencia de la ortofoto.
- Existencia del Excel.
- Existencia del modelo.
- Densidad mayor que cero.
- `spatial_analysis.yaml` versión 6 o superior.
- `cartography.yaml` versión 2 con identidad gráfica.
- `report.yaml` versión 2 con identidad gráfica.
- Correspondencia entre GeoPackage y capa de exclusiones.

## Primera validación

Después de crear el YAML:

```powershell
python main.py run-full-analysis `
".\config\pipeline_config_NOMBRE_FINCA.yaml" `
--dry-run
```

## Procesamiento completo

```powershell
python main.py run-full-analysis `
".\config\pipeline_config_NOMBRE_FINCA.yaml"
```

## Reanudación

```powershell
python main.py run-full-analysis `
".\config\pipeline_config_NOMBRE_FINCA.yaml" `
--resume-run "$runDir"
```

## Regla de conservación

Cada finca debe tener su propio archivo:

```text
pipeline_config_FINCA_A.yaml
pipeline_config_FINCA_B.yaml
pipeline_config_LOTE_03.yaml
```

No reutilice el YAML de otra finca cambiando solo una ruta después de que una
ejecución ya haya comenzado. La reanudación compara los parámetros críticos y
evita mezclar ortofotos, modelos, densidades o límites diferentes.
