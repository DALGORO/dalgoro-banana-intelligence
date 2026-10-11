# DBI-H11-SEC-001 · Aislamiento provisional de lecturas INSPECT pendientes

## Motivo
La aprobación técnica + administrativa independiente se confirmó en #215,
pero no hay firmas persistidas ni rutas de lectura pública con doble aprobación.
Antes de incorporarlas se debe impedir que una cuenta cliente con permiso
`READ` consulte observaciones de campo no aprobadas usando UUID conocido.

## Cambio limitado

- `GET .../field-observations/{observation_id}` y
  `GET .../field-observations/{observation_id}/versions` requieren ahora
  **ambos permisos scoped `READ` y `WRITE`**, en frontera FastAPI y
  servicio INSPECT, sobre tenant/organización/finca/lote autorizados.
  READ-only recibe el **mismo 404 no enumerativo** que un recurso no accesible.
- Se conserva el permiso `WRITE` en altas, correcciones y asociación
  de UP, el versionado inmutable y la protección por scope existente.
- La pestaña de cliente `Seguimiento del lote` ya no presenta la búsqueda
  provisional por UUID; indica que las inspecciones estarán disponibles
  después de doble aprobación. No se inventan publicaciones o conteos.
- La consulta UUID de soporte existe como componente aislado, pero no
  aparece en la pestaña pública. El GET actual es un mecanismo **interno**,
  NO una ruta de publicación.
- Se agregan pruebas para prohibir GET directo y GET de historial
  con `READ` sin `WRITE`, y conservar acceso interno con ambos permisos.

## Advertencias y condición de seguridad

Esta barrera es **temporal y conservadora**. `WRITE` scoped se usa aquí como
capacidad de trabajo interno, **no como certificado de identidad DALGORO**.
Debe auditarse que ninguna membresía cliente posea `WRITE`, y que
técnicos y administradores estén dados de alta con ambos permisos `READ`+
`WRITE` en sus ámbitos; un usuario con `MANAGE` sin `WRITE` no podrá
usar el GET interno.

No existe todavía un listado seguro por Campaign, firma persistida, revisión
de roles reales ni publicación por doble aprobación. Estos endpoints
**nunca deben devolverse sin un gate efectivo a clientes `READ`**, y no
pueden considerarse «publicados» aunque el código de política pura devuelva
`dual_approved` en memoria.

## Próximo PR

Diseñar una migración append-only aislada con vínculo Campaign–INSPECT y
las dos firmas por **versión exacta**, validación de pertenencia efectiva de
técnico/admin, auditoría e idempotencia/concurrencia, y después separar
GET administrativo interno de GET cliente filtrado por versión publicable
con pruebas de integración PostGIS y HTTP (cliente, técnico, admin).
Solo tras ello enlazar observaciones aprobadas a la pestaña del lote.

Sin cambios en algoritmos, densidad, modelado de Sigatoka, PostGIS real
ni despliegues de producción. Las pruebas offline/CI no sustituyen UAT
con cuentas reales y revisión de roles.
