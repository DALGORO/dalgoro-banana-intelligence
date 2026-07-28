# Fase 12 — Interfaz amigable DALGORO

## Objetivo

Permitir que una persona sin conocimientos de programación pueda:

1. Seleccionar la ortofoto.
2. Seleccionar el Excel de coordenadas.
3. Escribir finca, productor y densidad.
4. Validar los datos.
5. Ejecutar todo el análisis.
6. Reanudar una ejecución interrumpida.
7. Abrir el reporte PDF final.
8. Abrir la carpeta de resultados.

## Archivos

```text
interfaz_banano.py
INICIAR_ANALIZADOR_BANANO.bat
```

## Ubicación

Ambos archivos deben colocarse en:

```text
F:\PROY_CONTEO_BANANO_1\automatizacion_banano
```

## Inicio normal

Haga doble clic en:

```text
INICIAR_ANALIZADOR_BANANO.bat
```

También puede abrirse desde PowerShell:

```powershell
python .\interfaz_banano.py
```

## Diagnóstico de instalación

```powershell
python .\interfaz_banano.py --validate-installation
```

## Flujo de trabajo

### Pestaña 1: Datos de la finca

Complete los campos obligatorios y seleccione las rutas.

### Pestaña 2: Parámetros técnicos

Mantenga inicialmente los valores validados:

```text
tile_size = 640
overlap = 128
confidence = 0.40
IoU = 0.70
deduplicación = 1.00 m
píxel KDE = 0.50 m
```

### Pestaña 3: Ejecutar y obtener PDF

- `Guardar configuración`: crea el YAML de la finca.
- `Validar sin procesar`: ejecuta `--dry-run`.
- `Ejecutar análisis completo`: procesa todas las etapas.
- `Reanudar ejecución`: continúa una carpeta con `estado_pipeline.json`.
- `Detener`: interrumpe el árbol de procesos y conserva lo terminado.
- `Abrir informe PDF`: abre el reporte final.
- `Abrir carpeta de resultados`: abre la ejecución seleccionada.

## Identificador

```text
DALGORO_BANANA_GUI_V1_20260717
```
