# DBI-SAMPLING-001 — prueba local reproducible

Esta guía permite comprobar visualmente el planificador Sampling desde un equipo local **sin PostgreSQL, PostGIS, Docker, credenciales ni conexión a servicios externos**.

La prueba usa un lote sintético en Ecuador. Genera 26 puntos principales, 10 reservas, una exclusión y el límite del lote en un archivo GeoJSON listo para abrir en QGIS.

> Esta prueba valida el motor de planificación y su salida geoespacial. La persistencia PostgreSQL/PostGIS, concurrencia, ciclo de campo y ACL ya se validan en GitHub Actions. Todavía no existe una pantalla Sampling/PWA productiva en el frontend.

## 1. Abrir el repositorio correcto en VS Code

Abra en VS Code la carpeta raíz:

```text
dalgoro-banana-intelligence
```

En **Terminal > New Terminal**, compruebe que la terminal está ubicada en esa carpeta raíz.

## 2. Actualizar `main`

En PowerShell:

```powershell
git switch main
git pull origin main
```

La rama debe contener `DBI-SAMPLING-001` y la migración `dbi_0016_sampling_plans`.

## 3. Crear el entorno Python

Recomendado para Windows con Python 3.11:

```powershell
py -3.11 -m venv apps/platform-web/backend/.venv
```

No es obligatorio activar el entorno. Los comandos siguientes usan directamente el Python de `.venv`, evitando problemas de política de PowerShell.

## 4. Instalar dependencias backend

```powershell
.\apps\platform-web\backend\.venv\Scripts\python.exe -m pip install --upgrade pip
.\apps\platform-web\backend\.venv\Scripts\python.exe -m pip install -r apps/platform-web/backend/requirements.txt
```

La instalación debe terminar sin errores.

## 5. Ejecutar la demo Sampling

Desde la raíz del repositorio:

```powershell
.\apps\platform-web\backend\.venv\Scripts\python.exe apps/platform-web/backend/scripts/dbi_sampling_local_demo.py
```

La salida esperada contiene:

```text
DBI-SAMPLING-001 · demo local generado correctamente
principales: 26
reservas: 10
estado_presupuesto: within_target
```

También mostrará un `plan_id` determinista y la ruta completa del archivo generado.

El archivo por defecto es:

```text
tmp/dbi_sampling_demo.geojson
```

La carpeta `tmp` está excluida de Git, por lo que esta prueba no ensucia el repositorio con resultados versionados.

### Elegir otra ruta de salida

Opcionalmente:

```powershell
.\apps\platform-web\backend\.venv\Scripts\python.exe apps/platform-web/backend/scripts/dbi_sampling_local_demo.py --output C:\TEMP\sampling_demo.geojson
```

## 6. Abrir el resultado en QGIS

1. Abra QGIS.
2. Vaya a **Layer > Add Layer > Add Vector Layer**.
3. En `Source`, seleccione `tmp/dbi_sampling_demo.geojson`.
4. Pulse **Add**.
5. En la tabla de atributos verá la propiedad `feature_kind`:
   - `boundary`: límite sintético del lote;
   - `exclusion`: zona que el planificador debe evitar;
   - `sampling_point`: punto de muestreo.
6. Para los puntos, la propiedad `role` diferencia:
   - `primary`: punto principal;
   - `reserve`: punto reserva.
7. `route_order` indica el orden sugerido para principales.
8. `reserve_for_sequence` indica a qué principal está asociada cada reserva.

La inspección visual debe confirmar que los puntos están dentro del lote, evitan la exclusión y se distribuyen de forma balanceada.

## 7. Ejecutar las pruebas locales adicionales

Estas pruebas no necesitan base de datos:

```powershell
.\apps\platform-web\backend\.venv\Scripts\python.exe .github/scripts/ci_dbi_sampling_contracts.py
.\apps\platform-web\backend\.venv\Scripts\python.exe .github/scripts/ci_dbi_sampling_http.py
.\apps\platform-web\backend\.venv\Scripts\python.exe .github/scripts/ci_dbi_sampling_local_demo.py
```

Las tres deben terminar con mensajes de aprobación.

## 8. Qué NO se necesita para esta primera prueba

No configure todavía:

- `DBI_DATABASE_URL`;
- PostgreSQL/PostGIS local;
- Render;
- Google Sheets;
- Green API;
- almacenamiento S3/GCS;
- pesos YOLO;
- frontend/PWA Sampling.

Esto es deliberado: la primera comprobación local debe aislar el motor Sampling ya validado y permitir revisar inmediatamente la geometría en QGIS sin debilitar las barreras de migración DBI.

## 9. Resultado esperado de esta etapa

Al finalizar debe tener:

- entorno Python local funcional;
- motor Sampling ejecutándose desde `main`;
- un plan reproducible de 26 principales + 10 reservas;
- `tmp/dbi_sampling_demo.geojson` abierto y visible en QGIS;
- pruebas puras/HTTP/demo aprobadas.

El siguiente nivel de prueba, cuando se requiera, será levantar un entorno PostgreSQL/PostGIS de desarrollo aislado y probar las operaciones API persistentes; eso debe hacerse con un harness de desarrollo dedicado, sin reutilizar ni relajar el mecanismo de migración controlado de producción/CI.
