# DBI-PORTAL-GIS-006 · Estados de importación GIS actualizados

En **Mis fincas → Lote → Añadir resultado cartográfico**, el gestor con permiso MANAGE puede consultar los archivos originales recibidos y su estado:

- **Recibido:** esperando ejecución del worker independiente.
- **En conversión:** el worker tiene reclamado el archivo.
- **Convertido / pendiente de aprobación:** existe vista previa privada disponible para revisión.
- **Publicado:** el gestor aprobó explícitamente el derivado.
- **Fallido:** revisar el proceso; no se muestra al cliente.

Mientras haya al menos un original en estado **recibido** o **en conversión**, la página consulta cada **15 segundos** el endpoint privado de ese lote. Al terminar o cambiar de lote se detiene la consulta. El botón **Actualizar** también permite solicitar el estado manualmente, incluso si no existen archivos o ya no hay tareas pendientes.

Las respuestas se mantienen asociadas a una clave de contexto `tenant + organización + finca + lote`, por lo que un resultado atrasado de otra página no se dibuja como resultado del lote actual. La consulta periódica se desactiva para usuarios sin capacidad de publicación.

**Este refresco no arranca workers, no valida GIS, no reemplaza el procedimiento de revisión y no supone que el despliegue tenga el worker de S3 activado.** Si el trabajo permanece en `received`, debe verificarse la infraestructura operativa del worker y no la interfaz.

CI requerida: Frontend lint/build y todos los gates del PR en el commit exacto antes de fusionar.
