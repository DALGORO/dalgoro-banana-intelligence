# DBI-H11-DEC-002 · Doble aprobación INSPECT antes de publicación a cliente

**Decisión explícitamente confirmada:** para hacer visible una observación INSPECT al cliente son **obligatorias dos firmas distintas y sucesivas**, validación técnica + autorización administrativa, ambas sobre **la misma versión de INSPECT y la misma Campaign MULTI verificada**.

## Reglas operativas obligatorias

1. **Borrador o pendiente**: técnico y administrador autorizados pueden consultar, capturar, corregir y vincular INSPECT dentro del ámbito DBI real. Cliente no puede consultar ni observar versiones pendientes, incluso con UUID directo.
2. **Validación técnica**: un principal técnico acreditado revisa verdad-terreno, Fouré/estados missing-aware, fecha de observación, UP/punto, Campaign, protocolo, evidencia e integridad; firma la **versión vigente**. Requiere autorización de escritura scoped. Es una decisión de revisión, no un diagnóstico derivado.
3. **Autorización administrativa**: **otra identidad** con `APPROVE_AGRONOMIC` y `MANAGE` scoped verifica la Campaign/procedencia, la identidad y la versión vigente. La firma administrativa solo ocurre tras la técnica; ningún actor puede firmar ambos pasos.
4. **Visibilidad del cliente**: la API externa solo debe devolver la versión exacta que tiene ambas firmas, Campaign acreditada y autorización del lote. `READ` por sí solo **no habilita** un registro pendiente. Si se corrige el registro, la versión nueva vuelve a `pending`; la anterior no puede pasar inadvertidamente como vigente. Respuesta de denegación uniforme (sin confirmar existencia de otros lotes/tenants).
5. **Historial y auditoría**: las observaciones originales no se sobrescriben; cada firma conserva actor, instante, versión, Campaign, alcance y huella para comprobar la cadena. Revocación y rechazo deben ser auditados. Los informes y datasets dependen de la misma versión firmada y pierden elegibilidad si la versión fue sustituida.
6. **Doble rol no es doble persona**: que una misma cuenta tenga `WRITE`, `MANAGE` y `APPROVE_AGRONOMIC` **no es suficiente**. Se requieren dos principales distintos; técnicos/admin deben ser personal autorizado DALGORO, verificado en las membresías backend, no un parámetro `role` del navegador.

## Código de este microhito: política pura, no publicación efectiva

`app/dbi/inspection/dual_approval.py` modela un estado inmutable y las transiciones `pending → technical_validated → dual_approved`, con comprobación de scope, privilegios, firma separada, momento, Campaign acreditada y versión actual. `eligible_for_client_read` es un predicado de preparación cuya entrada **solo puede provenir de validación del servidor**.

`.github/scripts/ci_dbi_inspection_dual_approval.py` valida sin DB ni red:
- Cliente READ no valida ni autoriza.
- Un ámbito de otro tenant o lote no puede validar.
- No puede aprobar administrador sin técnico.
- El mismo principal no puede firmar dos veces, aun teniendo todos los permisos.
- Un administrador requiere BOTH `APPROVE_AGRONOMIC` y `MANAGE` scoped.
- No se publica con Campaign no verificada, otra Campaign, versión anterior o corrección pendiente.
- Estados incompletos y fechas inválidas se rechazan.
- El backend CI ejecuta el contrato de forma automática.

**Este commit no añade tablas, firmas persistidas, endpoints ni verificaciones de visibilidad a la API.**
En particular, actualmente `GET /field-observations/{id}` y `GET /versions` usan `READ` y **todavía no filtran por doble aprobación**; por ello **no se debe ofrecer esta API al cliente externo en producción como fuente de registros publicables**. El acceso cliente efectivo exige implementar el gate del servidor, verificar membresías y probar 403/404, 2 roles, cambios de versión y concurrencia. La política pura por sí sola **NO garantiza todavía la confidencialidad**.

## Próximos microhitos de implementación real

A. **Identidades, vínculo Campaign–INSPECT y publicación**: diseñar migración aislada append-only con FK de Campaign, observación y versión, transiciones auditadas y control de concurrencia/idempotencia. Distinguir técnico DALGORO de otro usuario con permisos `WRITE` antes de procesar firma.

B. **Separación efectiva de consultas**: rutas administrativas/técnicas internas para READ de borradores e historial; rutas READ cliente filtradas por versión aprobada y publicada, tenant/finca/lote/Campaign, sin acceso por ID a pendientes. Bloquear acceso legacy que pase `READ` sin gate. Pruebas HTTP de autorización reales.

C. **UX por permisos**: mapa y pestaña `Seguimiento` de cliente *solo consulta*, sin controles de escritura. Técnico ve captura/corrección/revisión; admin revisa, autoriza y publica. Ninguna decisión depende de ocultar un botón.

D. **Pares para aprendizaje**: la publicación al cliente y la elegibilidad de dataset son controles **distintos**: un INSPECT puede publicarse tras doble firma pero no ser ejemplo entrenable si falla QA de COPA_UP, sensores, evidencia, correspondencia temporal o valores faltantes. No entrenar ni inferir Sigatoka automáticamente sin aprobación de modelo y validación externa.

**Criterio de aceptación completo posterior:** el cliente no puede ver registros sin ambas firmas ni siquiera mediante HTTP manipulado; técnico/admin sí pueden consultar y corregir con permisos scoped, y cada nueva versión exige dos nuevas firmas. UAT móvil/navegador, entorno autorizado y despliegue quedan pendientes.
