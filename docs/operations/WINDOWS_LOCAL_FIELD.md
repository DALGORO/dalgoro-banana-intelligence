# DBI Local Ops en Windows y flujo de campo offline

Este documento describe el modo local de DALGORO Banana Intelligence para pruebas y operación de campo controlada desde una laptop Windows.

## 1. Qué instala el Control Center

`infra/windows-local/Install-DBI-ControlCenter.ps1` realiza una instalación local de una sola vez para el usuario actual de Windows:

- conserva PostgreSQL/PostGIS en el contenedor `dbi-postgis-development`;
- protege la contraseña del rol `dbi_development_api` con DPAPI de Windows;
- genera y protege un `JWT_SECRET` local;
- crea una SQLite persistente bajo `%LOCALAPPDATA%\DALGORO\DBI\dbi_auth.sqlite3` para autenticación heredada local;
- crea las tablas heredadas locales necesarias mediante `Base.metadata.create_all`;
- crea/actualiza el usuario local `dbi.local@dalgoro.ec` con contraseña elegida por el operador;
- instala un acceso directo de inicio automático en la carpeta Startup del usuario;
- crea `DALGORO DBI Control Center` en el escritorio;
- inicia Docker/PostGIS, FastAPI, PWA y Cloudflare Tunnel.

Los secretos no se escriben en el repositorio. Los archivos DPAPI sólo pueden descifrarse con la misma cuenta de Windows que los creó.

## 2. Inicio, pausa y reanudación

El acceso directo de Startup ejecuta:

```powershell
DBI-ControlCenter.ps1 -Action Start
```

Al iniciar sesión en Windows, el Control Center deja operativo el stack local. No es necesario abrir PowerShell manualmente.

El acceso directo `DALGORO DBI Control Center` muestra botones para:

- **Iniciar / Reanudar**: inicia lo que esté detenido;
- **Detener temporalmente**: detiene frontend, backend, túnel y contenedor PostGIS, sin borrar datos;
- **Reiniciar sistema**: detiene y vuelve a iniciar el stack;
- **Abrir DBI**: abre la URL pública actual;
- **Actualizar estado**: verifica PostGIS, FastAPI, frontend y túnel.

Cerrar únicamente la ventana del Control Center no detiene DBI.

Los logs locales se escriben en:

```text
%LOCALAPPDATA%\DALGORO\DBI\logs
```

## 3. Quick Tunnel vs. URL estable

El instalador usa inicialmente `tunnel_mode = "quick"` para desarrollo. Un Quick Tunnel genera una URL `trycloudflare.com` distinta cuando se crea un túnel nuevo.

Esto **no es suficiente para una operación de campo permanente** porque Service Worker, localStorage e IndexedDB están aislados por origen. Si cambia el hostname, el iPad lo trata como otra aplicación/origen y no comparte automáticamente el caché ni la cola offline del hostname anterior.

Antes de usar DBI como sistema operativo de campo debe configurarse un **Cloudflare Named Tunnel con hostname fijo** (o desplegar el backend/frontend en una infraestructura cloud estable). El Control Center ya admite:

```json
{
  "tunnel_mode": "named",
  "tunnel_name": "NOMBRE_DEL_TUNNEL",
  "public_hostname": "dbi.corporativo.example"
}
```

El Named Tunnel debe estar previamente autenticado/configurado en `cloudflared` y enrutar ese hostname a `http://127.0.0.1:4173`.

Nunca se expone PostgreSQL directamente a Internet.

## 4. Qué debe cargarse antes de quedarse sin Internet

La PWA guarda cada plan Sampling en IndexedDB. Cuando el plan se abre con conexión, `refreshAndCacheSamplingPlan()` descarga el plan del servidor y `cacheSamplingPlan()` lo guarda bajo el store `sampling_plans`.

Si el dispositivo pierde conexión, `SamplingFieldPage` intenta recuperar `getCachedSamplingPlan()`. Si no existe una copia local, la aplicación falla cerrado con el mensaje:

> No existe una copia offline de este plan. Ábralo al menos una vez con conexión.

Por tanto, con la arquitectura local actual:

1. La laptop debe estar encendida y DBI debe estar `RUNNING` mientras se prepara el trabajo de campo.
2. El iPad debe tener Internet y acceso al hostname DBI.
3. Debe abrirse **cada plan Sampling que se vaya a usar en campo** al menos una vez mientras hay conexión.
4. Antes de salir, se recomienda poner el iPad brevemente en modo avión y recargar el plan para confirmar que abre desde caché.
5. Ya en campo, la laptop no necesita acompañar al operador ni permanecer conectada al iPad. Las acciones Sampling y las observaciones INSPECT se conservan en IndexedDB/outbox.
6. Cuando el iPad recupere conexión con el mismo origen DBI, las colas se sincronizan con PostgreSQL.

Actualmente el caché se realiza por **plan Sampling**, no por “toda la finca” de forma automática. Si una finca tiene varios planes que se usarán en la visita, deben prepararse todos.

## 5. Mejora recomendada para operación real

Para eliminar el paso manual de abrir cada plan, la evolución natural es añadir en la PWA un botón **Preparar finca para campo** que:

- descargue los planes activos seleccionados;
- guarde boundary, exclusions, puntos principales y reservas en IndexedDB;
- verifique que el shell PWA esté disponible;
- muestre un estado `LISTA PARA OFFLINE` con fecha/hora de la última preparación;
- advierta si existe una cola pendiente de sincronización antes de salir.

Ese botón debe ser una mejora de producto independiente; no debe sustituir la necesidad de un hostname estable.

## 6. Alcance de seguridad

Este mecanismo es para el entorno local/controlado de DBI. No modifica Render, WhatsApp, Green API, Google Sheets ni despliega producción. No guarda contraseñas en Git y no abre el puerto 55432 de PostgreSQL hacia Internet.
