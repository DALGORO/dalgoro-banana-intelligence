# PostgreSQL/PostGIS DBI por ambiente

Esta carpeta define infraestructura declarativa para la base aislada de DALGORO Banana Intelligence. No ejecuta despliegues, no contiene secretos y no autoriza el uso de la base heredada.

## Matriz de ambientes

| Contexto operativo | `DBI_ENVIRONMENT` | Base autorizada | Ejecución remota desde CI |
|---|---|---|---|
| Local | `development` | `dbi_development` | Prohibida |
| CI | `test` | `dbi_test` | Prohibida |
| Staging | `staging` | `dbi_staging` | Prohibida |
| Producción | `production` | `dbi_production` | Prohibida |

La fuente verificable de esta matriz es `environments.json`.

## Roles

Cada ambiente usa nombres independientes:

- **owner**: rol `NOLOGIN` propietario lógico de la base y del esquema `dbi`.
- **migrator**: rol de inicio de sesión autorizado para Alembic DBI y cambios de esquema. No es superusuario, no crea bases ni roles.
- **api**: lectura y escritura funcional sobre tablas y secuencias del esquema `dbi`; no puede crear o alterar el esquema.
- **worker**: lectura, inserción y actualización para procesamiento geoespacial; no recibe `DELETE` ni DDL.
- **observer**: solo lectura para observabilidad y soporte.

Ninguno de los roles de aplicación es superusuario, propietario global o usuario de la base heredada. El rol `migrator` no hereda ni puede asumir el rol `owner`; recibe únicamente `CONNECT` sobre la base y `USAGE, CREATE` sobre el esquema `dbi`.

PostGIS se instala de forma predeterminada en `public`. Por ello, migrator, api, worker y observer reciben únicamente `USAGE` sobre ese esquema para resolver el tipo `geometry` y las funciones `ST_*`. No reciben `CREATE` sobre `public`. El `search_path` operativo es:

```text
search_path = dbi, public
```

`dbi` permanece primero para que los objetos no cualificados se creen allí. `pg_catalog` no se declara explícitamente porque PostgreSQL lo busca de forma implícita antes de los esquemas configurados.

## Variables

Las únicas variables de conexión aceptadas por DBI son:

```text
DBI_ENVIRONMENT
DBI_DATABASE_URL
```

`DATABASE_URL` pertenece al sistema heredado y está prohibida para operaciones DBI. Las contraseñas, hosts y certificados deben almacenarse en el gestor de secretos del ambiente y nunca versionarse.

## Aprovisionamiento controlado

1. Seleccionar el ambiente en `environments.json`.
2. Renderizar `bootstrap.sql.tmpl` sustituyendo únicamente sus tokens por los identificadores declarados para ese ambiente.
3. Obtener la credencial de un operador de infraestructura capaz de crear la base y la extensión PostGIS. Esa credencial no se reutiliza por la API, worker o migrador.
4. Revisar el SQL renderizado y confirmar que apunta a la base DBI autorizada.
5. Ejecutar manualmente con `psql` desde una estación administrativa aprobada.
6. Asignar o rotar las contraseñas de los roles `LOGIN` mediante el gestor de secretos.
7. Construir `DBI_DATABASE_URL` con el rol correspondiente al componente:
   - Alembic DBI: migrator.
   - FastAPI DBI: api.
   - Worker geoespacial: worker.
   - Observabilidad: observer.
8. Verificar privilegios y resolución de PostGIS antes de habilitar cualquier componente.

Este procedimiento no forma parte de CI y requiere autorización específica para cada ambiente.

## Verificación mínima

Ejecutar como operador autorizado:

```sql
SELECT extname, extnamespace::regnamespace
FROM pg_extension
WHERE extname = 'postgis';
SELECT nspname FROM pg_namespace WHERE nspname = 'dbi';
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole
FROM pg_roles
WHERE rolname LIKE 'dbi\_%' ESCAPE '\\';
```

Después, comprobar con cada credencial:

```sql
SHOW search_path;
SELECT postgis_full_version();
SELECT ST_IsValid(ST_GeomFromText('POINT(0 0)', 4326));
```

También se debe confirmar que:

- migrator puede crear y alterar objetos únicamente en `dbi`;
- migrator no puede ejecutar `SET ROLE` al propietario de la base;
- api puede seleccionar, insertar, actualizar y eliminar datos, pero no ejecutar DDL;
- worker no puede eliminar tablas ni filas;
- observer no puede modificar datos;
- ninguno de los roles puede crear objetos dentro de `public`;
- ningún rol puede acceder a la base heredada.

## Reversión

La plantilla no incluye `DROP DATABASE`, `DROP ROLE`, `DROP SCHEMA` ni borrado automático. Una reversión requiere:

1. deshabilitar conexiones de los componentes;
2. revocar temporalmente `CONNECT` al rol afectado;
3. restaurar privilegios desde una copia previamente auditada;
4. restaurar la base desde respaldo cuando exista daño de datos;
5. documentar y aprobar cualquier eliminación manual en un ticket independiente.

## Rotación de credenciales

1. generar una contraseña nueva en el gestor de secretos;
2. aplicar `ALTER ROLE ... PASSWORD` mediante un canal administrativo seguro;
3. actualizar la variable `DBI_DATABASE_URL` del componente;
4. reiniciar únicamente el componente afectado;
5. validar conexión y permisos;
6. invalidar la credencial anterior y registrar la evidencia.

Nunca se copian secretos en Issues, PR, logs, archivos `.env` versionados o documentación.

## Límites actuales

Esta carpeta prepara PostgreSQL, PostGIS, el esquema `dbi` y roles mínimos. No ejecuta migraciones funcionales, tiles, despliegues reales ni aplicación remota de cambios.
