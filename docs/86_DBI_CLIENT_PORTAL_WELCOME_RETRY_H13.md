# DBI-CLIENT-UX-001 — Portal productor: marca consistente y errores recuperables

## Alcance de esta iteración visual

Se mejora **únicamente la página `/portal`** que enumera fincas y lotes
autorizados por el backend `GET /api/v1/dbi/portal/accounts`.
La paleta de bienvenida se alinea con la marca DALGORO petróleo/cobre
aprobada en Hito 11 (`#152e32` y `#b57b50`) y el resto del visor
cartográfico permanece intacto.

- Los indicadores de fincas y lotes se computan a partir del **mismo catálogo
  filtrado por el buscador**. No confundir recuentos antes/después de filtrar.
- Al fallar la carga (401, 503 u otros errores), se ocultan los contadores,
  se muestra la causa disponible y un botón **Reintentar consulta**.
  El botón sólo repite la solicitud READ autorizada; no crea registros,
  nunca fuerza recarga de página y no borra la búsqueda seleccionada.
- Durante cada consulta se muestra un estado de carga accesible;
  `aria-live` y `role=alert` exponen el estado sin datos fabricados.
  Focos visibles y altura táctil mínima para reintento.
- El enlace de cada lote sigue apuntando al mapa DBI con la misma identidad
  tenant/organización/finca/lote obtenida del servidor; no se crean enlaces
  a registros INSPECT aún no aprobados ni menús sin backend.

## Pruebas y límites

Se amplía `frontend/tests/dbiClientVisualLayout.test.mjs` para verificar
contrato de endpoint, filtros, retry, estados accesibles, marca y ausencia
de escrituras o datos simulados. Deben aprobarse lint, TypeScript/Vite y CI.

No se modifica backend, identidad, migraciones, Cloud/Render, cálculos
agronómicos, INSPECT ni el visor MapLibre. La equivalencia visual real
requiere todavía una captura de navegador con distintas resoluciones y
roles, **no** se declara UAT ni despliegue a producción.
