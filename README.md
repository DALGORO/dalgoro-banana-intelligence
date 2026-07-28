# DALGORO Banana Intelligence

Plataforma integrada para gestión de fincas bananeras que combinará:

- Dashboard ejecutivo y mapas cronológicos.
- Densidad de siembra y análisis geoespacial.
- Imágenes RGB y multiespectrales.
- Inspecciones de campo y seguimiento de actividades.
- Datos agrometeorológicos.
- SST aplicado a labores agrícolas.
- Bot de WhatsApp.
- Cosecha, racimos, cintas, clústeres y cajas.
- Biblioteca técnica y recomendaciones trazables.
- Aprendizaje automático controlado y versionado.

## Estructura inicial

- `apps/platform-web`: base web SST Compliance.
- `apps/whatsapp-bot`: bot DALGORO existente.
- `services/banana-density`: sistema de densidad de banano.
- `docs`: memoria técnica y estado oficial.
- `.github/workflows`: automatización de pruebas.

## Estado

Esta primera importación conserva los tres sistemas como módulos separados.
No implica todavía que estén integrados entre sí.
