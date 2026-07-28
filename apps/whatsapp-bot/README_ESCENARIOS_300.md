# Escenarios de simulación DALGORO S.A.S. - 300 conversaciones

Incluye escenarios de:
- Redes sociales/Facebook/Instagram.
- Referidos.
- Respuestas a campañas automáticas por WhatsApp.
- Clientes interesados, desconfiados, no interesados o groseros.
- Preguntas por precio.
- Clientes que ya tienen permiso o consultor.
- Mensajes fragmentados.
- Cambios, cancelaciones y nuevas fincas después de agendar.
- Errores ortográficos y modismos locales.

Archivos:
- `escenarios_simulacion_300_dalgoro.json`: dataset estructurado.
- `escenarios_simulacion_300_dalgoro.py`: script ejecutable de simulación.

Recomendación:
Antes de probar en producción, ejecuta:
`python escenarios_simulacion_300_dalgoro.py`

Si el script muestra errores, revisa los IDs de escenario reportados y ajusta `lexico_base.py`, `ia_intenciones.py` o `respuestas_comerciales.py`.