# H14 · Seguridad GIS: congelar ediciones después de APPROVED

## Riesgo que se cierra
La ruta GIS `_editable_campaign()` impedía cambios únicamente cuando
`Campaign.status == PUBLISHED`. Durante el intervalo entre `APPROVED` y
`PUBLISHED`, un gestor con `MANAGE` podía crear otro GeoJSON o aprobar una
importación GIS previamente preparada. Esa capa nueva **no había formado parte
del conjunto existente al momento de la aprobación de Campaign**.

## Corrección mínima
En `apps/platform-web/backend/app/api/v1/dbi_portal_vectors.py`,
`_editable_campaign()` conserva el SELECT con row lock y el mismo scope
tenant/organización/finca/lote. Rechaza con HTTP 409 cualquier edición cuando:

- `status` es `APPROVED` o `PUBLISHED`;
- `approved_at` o `published_at` ya tienen valor, incluso con estado incoherente.

No se modifican rutas READ ni la transición institucional a `PUBLISHED`.
No se conceden permisos ni se habilitan cargas de archivos científicos.
Los workflows en preparación continúan admitiendo acciones antes de
`APPROVED`, con las restricciones existentes.

El guard se reutiliza en registro GeoJSON, recepción/selección de importación
GIS y aprobación de capas GIS derivadas. No representa una aprobación
individual de cada producto; esta última debe diseñarse en otro incremento.

## Verificación
Se amplió `.github/scripts/ci_dbi_portal_vectors.py` con un doble offline
que exige cláusula `FOR UPDATE`, scope completo y pruebas para:
`DRAFT`, `PROCESSING`, `ANALYZED`, `TECHNICAL_REVIEW`,
`FIELD_COMPLETED`, `APPROVED`, `PUBLISHED`, marcas temporales
incoherentes y Campaign inexistente. Se ejecuta desde el mismo job CI
backend existente. No necesita migraciones.

## Operación segura
No editar capas aprobadas como atajo. Para una capa corregida se requiere
un nuevo ciclo autorizado de revisión/aprobación, con identidad de
Campaign/versionamiento que corresponda; no se abre una excepción temporal
a este guard.

No hubo despliegue Render, migración SQL ni publicación al cliente.
