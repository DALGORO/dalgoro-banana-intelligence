# DBI-PORTAL-001 — Portal cliente y base satelital Google

## Alcance implementado
- Entrada `/portal` por defecto tras el login: fincas y lotes autorizados del usuario autenticado.
- Endpoint `GET /api/v1/dbi/portal/accounts`: descubre membresías DBI activas del principal enlazado al usuario legacy; verifica permiso `read`; consulta exclusivamente fincas/lotes autorizados. No crea datos ficticios.
- La navegación enlaza al visor Plot/Timeline existente; cada petición a Campaign y cada PNG XYZ conserva reautorización por sesión DBI.
- Con `VITE_GOOGLE_MAPS_API_KEY` configurada, el visor utiliza Google Maps JavaScript API (`satellite`) como mapa base y coloca encima los mosaicos RGB privados que sean reales. Fuera de la cobertura RGB permanece visible Google. El navegador sólo recibe PNG XYZ autorizado, no rutas privadas ni el COG.
- Sin clave, se conserva el motor de visualización MapLibre anterior. El visor no extrae información científica del mapa base de Google.

## Activar Google Maps
1. En Google Cloud crear/seleccionar proyecto con cuenta de facturación, habilitar **Maps JavaScript API** y crear una **API key** restringida por **HTTP referrers** (URL del frontend público y origen local para pruebas).
2. Limitar la key en la consola de Google Cloud a **Maps JavaScript API**. No reutilizar una credencial privada de backend.
3. En el archivo `apps/platform-web/frontend/.env.local` añadir `VITE_GOOGLE_MAPS_API_KEY=VALOR_DE_LA_API_KEY_RESTRINGIDA`.
4. Reiniciar Vite o reconstruir el frontend (Vite incorpora las variables `VITE_*` durante la compilación).
5. Iniciar sesión con un usuario que posea principal/membresía DBI activos, permiso `read`, finca y lote autorizados. Abrir `Mis fincas` → `Ver mapa`.

**Costos y términos:** la visualización de Google Maps requiere habilitación de API/facturación y se rige por las tarifas y términos vigentes de Google Maps Platform. Su imagen base sólo puede emplearse para visualización, no como entrada de los motores de análisis, entrenamiento, detección o descarga offline. Mantener atribuciones intactas.

## Restricciones deliberadas y próximos bloques
- El catálogo no muestra fincas sin membresía DBI; las empresas legacy por sí solas no conceden acceso.
- El contrato del timeline actual publica la ortofoto RGB verificada; NDVI, Density y otros índices no aparecerán hasta que exista producto y adaptador de publicación/visualización autorizados.
- No existe aún en este incremento un cargador persistente genérico de SHP/GeoPackage/GeoJSON; no se deben convertir, publicar ni compartir directamente desde el navegador. Requiere ingestión servidor/worker aislada, validación CRS, tamaño, contenido, geometría, ámbito de tenant, almacenamiento privado y vinculaciones Campaign/producto.
- Ortofotos reales requieren prueba UAT #155 antes de afirmar funcionamiento E2E con datos comerciales.
- Límite inicial de 32 memberships, 100 fincas y 300 lotes por membresía; deben introducirse paginación y controles de exceso si se supera ese volumen.

## Referencias
- Google Maps JavaScript API: https://developers.google.com/maps/documentation/javascript/maptypes
- Políticas Map Tiles: https://developers.google.com/maps/documentation/tile/policies
