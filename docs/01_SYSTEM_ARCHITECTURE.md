# 01 — Arquitectura inicial

## Módulos importados
- Plataforma web: `apps/platform-web`
- Bot de WhatsApp: `apps/whatsapp-bot`
- Densidad de banano: `services/banana-density`

## Integración futura
1. API central FastAPI.
2. PostgreSQL/PostGIS.
3. Worker de análisis geoespacial.
4. Dashboard React.
5. PWA de campo.
6. Adaptador WhatsApp.
7. Almacenamiento externo para ortofotos, modelos y documentos.

## Restricciones de seguridad aprobadas en DBI-SEC-001

- Los sistemas actuales y sus bases PostgreSQL permanecen protegidos y fuera del
  alcance de las migraciones de DALGORO Banana Intelligence.
- `apps/platform-web/backend` es el candidato a API central. La decisión de
  límites y adaptación se completará en `DBI-ARC-001`; este ticket no integra
  módulos.
- La nueva plataforma utilizará una conexión exclusiva denominada
  `DBI_DATABASE_URL`. La variable `DATABASE_URL` existente no será reutilizada
  ni reemplazada durante la transición.
- Desarrollo, pruebas, staging y producción tendrán bases independientes.
  Staging y producción deberán usar servicios PostgreSQL/PostGIS separados de
  los sistemas actuales.
- Las migraciones DBI tendrán configuración e historial independientes y
  validarán el entorno y el nombre autorizado de la base antes de operar.
- La aplicación, las migraciones y los informes utilizarán roles PostgreSQL
  separados y con privilegios mínimos.

## Bases futuras previstas

| Entorno | Base prevista | Regla |
|---|---|---|
| Desarrollo | `dalgoro_banana_intelligence_dev` | Uso local exclusivo |
| Pruebas | `dalgoro_banana_intelligence_test` | Temporal y descartable |
| Staging | `dalgoro_banana_intelligence_staging` | Servicio nuevo |
| Producción | `dalgoro_banana_intelligence_prod` | Servicio nuevo y aprobación previa |

Estas bases no se crean en `DBI-SEC-001`. Su implementación corresponde a
`DBI-DATA-001` después de aprobar seguridad, CI y arquitectura.
