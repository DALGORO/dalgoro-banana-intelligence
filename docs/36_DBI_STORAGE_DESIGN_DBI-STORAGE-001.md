# 36 — Diseño de almacenamiento privado DBI-STORAGE-001

## Identificación

- Ticket: `DBI-STORAGE-001`.
- Issue: #51.
- Hito: #30.
- Rama: `feat/DBI-STORAGE-001-almacenamiento-privado-objetos`.
- Base auditada: `main` en `c576fd041f819c3c796d93bdfb7a30a70f522429`.
- Estado: diseño inicial; código funcional todavía no iniciado.

## Objetivo

Definir una frontera proveedor-neutral para objetos privados que asegure claves
relativas, aislamiento por tenant, integridad, idempotencia, retiro lógico y
acceso temporal, sin convertir una URL, credencial o ruta local en autoridad.

## Evidencia existente

`DBI-ASSET-001` ya persiste metadatos de activos y artefactos:

- clave relativa;
- tipo MIME;
- tamaño positivo;
- SHA-256;
- tenant, finca, lote, trabajo e intento según corresponda;
- estados y trazabilidad transaccional.

Ese ticket excluyó deliberadamente bucket, SDK, URLs firmadas, resolución de
objetos, endpoints y worker. `DBI-STORAGE-001` implementará la frontera binaria,
pero no escribirá esas tablas ni cambiará estados de activos.

## Decisiones vigentes

- PostgreSQL/PostGIS conserva metadatos y relaciones.
- El almacenamiento de objetos conserva binarios privados e inmutables.
- Los contratos usan claves internas, nunca rutas locales o URLs permanentes.
- Todo acceso de carga o lectura será temporal y autorizado.
- El worker seguirá separado del backend.
- No se seleccionará un proveedor sin aprobación explícita.

## Etapa A autorizada

- Tipos de dominio inmutables.
- Política pura de claves y namespaces.
- Validación de SHA-256, tamaño, MIME y TTL.
- Puerto proveedor-neutral.
- Adaptador en memoria para pruebas offline.
- Barreras estáticas contra SDK, secretos, URLs persistidas y rutas locales.
- Matriz de capacidades exigidas al futuro adaptador real.

## Etapa B bloqueada

Hasta aprobar proveedor no se incorporarán:

- SDK;
- imagen o contenedor de almacenamiento;
- credenciales o variables específicas;
- bucket real;
- red externa;
- integración de cifrado o URLs firmadas específicas del proveedor.

## Límites

No pertenecen a este ticket:

- creación o verificación de `AnalysisInputAsset`;
- endpoints de activos;
- cola, trabajos o worker;
- publicación de artefactos;
- producción o staging remoto;
- eliminación física;
- CDN o acceso público;
- modelos de IA o procesamiento geoespacial.

## Condición de avance

El Draft PR se abrirá con este documento antes del código funcional. Cada
incremento posterior deberá tener diff acotado, pruebas focalizadas y GitHub
Actions verdes sobre el SHA correspondiente.
