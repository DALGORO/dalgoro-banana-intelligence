# -*- coding: utf-8 -*-
"""
Escenarios de simulación DALGORO S.A.S. - 300 conversaciones

USO:
1. Copia este archivo dentro de la carpeta principal del bot.
2. Ejecuta:
   python escenarios_simulacion_300_dalgoro.py

Este archivo ya corrige el problema de `null`, usando JSON interno válido.
"""

import json

ESCENARIOS = json.loads(r"""[
  {
    "id": "ESC-001",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "bananera",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo una finca bananera",
      "quiero más información"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-002",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "bananera",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "soy productor bananero",
      "de qué se trata"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-003",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo una camaronera",
      "quiero más información"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-004",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "manejo piscinas de camarón",
      "de qué se trata"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-005",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "mineria",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo una concesión minera",
      "quiero más información"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-006",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "mineria",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "trabajo con material pétreo",
      "de qué se trata"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-007",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo cacao",
      "quiero más información"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-008",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "manejo una finca cacaotera",
      "de qué se trata"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-009",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo cultivo de ciclo corto",
      "quiero más información"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-010",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "siembro maíz",
      "de qué se trata"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-011",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo una granja porcina",
      "quiero más información"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-012",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo chanchera",
      "de qué se trata"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-013",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo una granja avícola",
      "quiero más información"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-014",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "manejo galpones de pollos",
      "de qué se trata"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-015",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "hotel",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo una hostería",
      "quiero más información"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-016",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "hotel",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "manejo un hotel",
      "de qué se trata"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-017",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "industria",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo una empacadora",
      "quiero más información"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-018",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "industria",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "manejo una planta procesadora",
      "de qué se trata"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-019",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "otra",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "tengo una actividad productiva",
      "quiero más información"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-020",
    "origen_probable": "facebook",
    "categoria_prueba": "redes_sociales_interes",
    "actividad_esperada": "otra",
    "motivo_esperado": "informacion",
    "resultado_esperado": "orientar_sin_agendar_directo",
    "mensajes_cliente": [
      "Hola, vi su anuncio en Facebook y quiero saber más",
      "manejo un negocio rural",
      "de qué se trata"
    ],
    "observaciones_prueba": "Debe reconocer origen Facebook y pedir actividad/motivo si faltan datos."
  },
  {
    "id": "ESC-021",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Sí",
      "tengo una finca bananera",
      "el banco me pide papeles"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-022",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Más información",
      "manejo piscinas de camarón",
      "es por GlobalGAP"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-023",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Me interesa",
      "tengo una cantera",
      "necesito regularizar"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-024",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "A ver",
      "soy productor cacaotero",
      "quiero mantener todo al día"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-025",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Cuénteme",
      "tengo yuca y maní",
      "me hicieron una observación"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-026",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "precio",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Cómo funciona",
      "tengo porqueriza",
      "quiero una proforma"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-027",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Envíeme información",
      "tengo una granja avícola",
      "el banco me pide papeles"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-028",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "hotel",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Quiero saber",
      "manejo un hotel",
      "es por GlobalGAP"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-029",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "industria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Está bien",
      "tengo una piladora",
      "necesito regularizar"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-030",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "otra",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Explíqueme",
      "tengo una empresa pequeña",
      "quiero mantener todo al día"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-031",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "bananera",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Sí",
      "manejo una bananera en Pasaje",
      "me hicieron una observación"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-032",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "precio",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Más información",
      "tengo una camarnra",
      "quiero una proforma"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-033",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "mineria",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Me interesa",
      "tengo una concesión minera",
      "el banco me pide papeles"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-034",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "A ver",
      "manejo una finca cacaotera",
      "es por GlobalGAP"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-035",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Cuénteme",
      "tengo arroz y maíz",
      "necesito regularizar"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-036",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Cómo funciona",
      "tengo una chankera",
      "quiero mantener todo al día"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-037",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Envíeme información",
      "tengo una avikola",
      "me hicieron una observación"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-038",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "hotel",
    "motivo_esperado": "precio",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Quiero saber",
      "tengo una quinta turística",
      "quiero una proforma"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-039",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "industria",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Está bien",
      "tengo una empacadora",
      "el banco me pide papeles"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-040",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "otra",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Explíqueme",
      "tengo una empresa pequeña",
      "es por GlobalGAP"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-041",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "bananera",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Sí",
      "tengo una hacienda bananera",
      "necesito regularizar"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-042",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Más información",
      "tengo una camaronera",
      "quiero mantener todo al día"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-043",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "mineria",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Me interesa",
      "tengo una mina pequeña",
      "me hicieron una observación"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-044",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "precio",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "A ver",
      "trabajamos con cacao nacional",
      "quiero una proforma"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-045",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "respuesta_campana_interes",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_no_ir_directo_a_cita",
    "mensajes_cliente": [
      "Cuénteme",
      "tengo cultivo de ciclo corto",
      "el banco me pide papeles"
    ],
    "observaciones_prueba": "Debe reconocer respuesta a campaña y conducir a información + diagnóstico/revisión."
  },
  {
    "id": "ESC-046",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una finca bananera",
      "el banco me pide papeles",
      "prefiero visita",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm sector La Peaña"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-047",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "manejo piscinas de camarón",
      "es por GlobalGAP",
      "llámeme mejor",
      "Soy Carlos Vera, mañana por la mañana"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-048",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una cantera",
      "necesito regularizar",
      "dese una vuelta",
      "A nombre de Marjorie Castro, viernes a las 10am por Barbones"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-049",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "soy productor cacaotero",
      "quiero mantener todo al día",
      "mejor por teléfono",
      "Regístreme como Luis Andrade, pasado mañana al mediodía"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-050",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo yuca y maní",
      "me hicieron una observación",
      "lo puedo recibir en la propiedad",
      "Don Pedro, el lunes temprano en la finca San Miguel"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-051",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo porqueriza",
      "es requisito bancario",
      "prefiero llamada",
      "Ricardo mena mañana en la tarde"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-052",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una granja avícola",
      "me pide una certificadora",
      "pueden venir a la finca",
      "Soy Ana Zambrano, hoy después del almuerzo recinto Buenavista"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-053",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "hotel",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "manejo un hotel",
      "no tengo permiso ambiental",
      "quisiera que me llamen",
      "María Solano, miércoles a eso de las 11"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-054",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una piladora",
      "necesito plan de manejo y monitoreos",
      "mejor que revisen en sitio",
      "Jorge Vera, el jueves a media tarde en mi finca"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-055",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "otra",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una empresa pequeña",
      "el municipio me pidió documentación",
      "una llamada primero",
      "Karla Jiménez, mañana tipo 10"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-056",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "manejo una bananera en Pasaje",
      "me piden licencia para préstamo",
      "prefiero visita",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm sector La Peaña"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-057",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una camarnra",
      "el cliente internacional pide cumplimiento",
      "llámeme mejor",
      "Soy Carlos Vera, mañana por la mañana"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-058",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una concesión minera",
      "quiero sacar licencia ambiental",
      "dese una vuelta",
      "A nombre de Marjorie Castro, viernes a las 10am por Barbones"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-059",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "manejo una finca cacaotera",
      "necesito informes ambientales",
      "mejor por teléfono",
      "Regístreme como Luis Andrade, pasado mañana al mediodía"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-060",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo arroz y maíz",
      "tengo inspección del MAATE",
      "lo puedo recibir en la propiedad",
      "Don Pedro, el lunes temprano en la finca San Miguel"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-061",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una chankera",
      "necesito por financiamiento",
      "prefiero llamada",
      "Ricardo mena mañana en la tarde"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-062",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una avikola",
      "Rainforest me observó eso",
      "pueden venir a la finca",
      "Soy Ana Zambrano, hoy después del almuerzo recinto Buenavista"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-063",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "hotel",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una quinta turística",
      "no tengo papeles ambientales",
      "quisiera que me llamen",
      "María Solano, miércoles a eso de las 11"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-064",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una empacadora",
      "ya tengo permiso pero quiero seguimiento",
      "mejor que revisen en sitio",
      "Jorge Vera, el jueves a media tarde en mi finca"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-065",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "otra",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una empresa pequeña",
      "me llegó un oficio",
      "una llamada primero",
      "Karla Jiménez, mañana tipo 10"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-066",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una hacienda bananera",
      "BanEcuador me está pidiendo eso",
      "prefiero visita",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm sector La Peaña"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-067",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una camaronera",
      "lo necesito para exportar",
      "llámeme mejor",
      "Soy Carlos Vera, mañana por la mañana"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-068",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una mina pequeña",
      "quiero saber qué trámite me corresponde",
      "dese una vuelta",
      "A nombre de Marjorie Castro, viernes a las 10am por Barbones"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-069",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "trabajamos con cacao nacional",
      "tengo permiso pero no sé si tengo obligaciones pendientes",
      "mejor por teléfono",
      "Regístreme como Luis Andrade, pasado mañana al mediodía"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-070",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo cultivo de ciclo corto",
      "me notificó el Ministerio",
      "lo puedo recibir en la propiedad",
      "Don Pedro, el lunes temprano en la finca San Miguel"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-071",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo chanchera",
      "es para un crédito",
      "prefiero llamada",
      "Ricardo mena mañana en la tarde"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-072",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo gallinas ponedoras",
      "es para auditoría de certificación",
      "pueden venir a la finca",
      "Soy Ana Zambrano, hoy después del almuerzo recinto Buenavista"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-073",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "hotel",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo un hostal",
      "me dijeron que saque registro ambiental",
      "quisiera que me llamen",
      "María Solano, miércoles a eso de las 11"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-074",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo un centro de acopio",
      "necesito acompañamiento mensual",
      "mejor que revisen en sitio",
      "Jorge Vera, el jueves a media tarde en mi finca"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-075",
    "origen_probable": "referido",
    "categoria_prueba": "referido_confianza",
    "actividad_esperada": "otra",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "orientar_y_proponer_revision",
    "mensajes_cliente": [
      "Buenas, me pasó su contacto el proveedor de fertilizantes",
      "tengo una empresa pequeña",
      "me preocupa una sanción",
      "una llamada primero",
      "Karla Jiménez, mañana tipo 10"
    ],
    "observaciones_prueba": "Debe usar tono de confianza, no pedir datos repetidos y registrar llamada/visita."
  },
  {
    "id": "ESC-076",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "bananera",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto cuesta",
      "tengo una finca bananera",
      "el banco me pide papeles"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-077",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "qué valor tiene",
      "manejo piscinas de camarón",
      "es por GlobalGAP"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-078",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "mineria",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto cobran",
      "tengo una cantera",
      "necesito regularizar"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-079",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "me puede dar precio",
      "soy productor cacaotero",
      "quiero mantener todo al día"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-080",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto sería mensual",
      "tengo yuca y maní",
      "me hicieron una observación"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-081",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "quiero una proforma",
      "tengo porqueriza",
      "es requisito bancario"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-082",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto cuesta",
      "tengo una granja avícola",
      "me pide una certificadora"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-083",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "hotel",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "qué valor tiene",
      "manejo un hotel",
      "no tengo permiso ambiental"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-084",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "industria",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto cobran",
      "tengo una piladora",
      "necesito plan de manejo y monitoreos"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-085",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "otra",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "me puede dar precio",
      "tengo una empresa pequeña",
      "el municipio me pidió documentación"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-086",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "bananera",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto sería mensual",
      "manejo una bananera en Pasaje",
      "me piden licencia para préstamo"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-087",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "quiero una proforma",
      "tengo una camarnra",
      "el cliente internacional pide cumplimiento"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-088",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "mineria",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto cuesta",
      "tengo una concesión minera",
      "quiero sacar licencia ambiental"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-089",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "qué valor tiene",
      "manejo una finca cacaotera",
      "necesito informes ambientales"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-090",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto cobran",
      "tengo arroz y maíz",
      "tengo inspección del MAATE"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-091",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "me puede dar precio",
      "tengo una chankera",
      "necesito por financiamiento"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-092",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto sería mensual",
      "tengo una avikola",
      "Rainforest me observó eso"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-093",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "hotel",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "quiero una proforma",
      "tengo una quinta turística",
      "no tengo papeles ambientales"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-094",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "industria",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto cuesta",
      "tengo una empacadora",
      "ya tengo permiso pero quiero seguimiento"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-095",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "otra",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "qué valor tiene",
      "tengo una empresa pequeña",
      "me llegó un oficio"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-096",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "bananera",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto cobran",
      "tengo una hacienda bananera",
      "BanEcuador me está pidiendo eso"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-097",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "me puede dar precio",
      "tengo una camaronera",
      "lo necesito para exportar"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-098",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "mineria",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto sería mensual",
      "tengo una mina pequeña",
      "quiero saber qué trámite me corresponde"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-099",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "quiero una proforma",
      "trabajamos con cacao nacional",
      "tengo permiso pero no sé si tengo obligaciones pendientes"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-100",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "pregunta_precio",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "precio",
    "resultado_esperado": "explicar_que_depende_y_pedir_actividad",
    "mensajes_cliente": [
      "cuánto cuesta",
      "tengo cultivo de ciclo corto",
      "me notificó el Ministerio"
    ],
    "observaciones_prueba": "No debe dar precio definitivo ni ir directo a agendar."
  },
  {
    "id": "ESC-101",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Quiénes son ustedes",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-102",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "De dónde sacaron mi número",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-103",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Esto es real?",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-104",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "No sé quiénes son",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-105",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Qué empresa es esa",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-106",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Dónde están ubicados",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-107",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Esto no será estafa?",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-108",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Quién les dio mi contacto",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-109",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Quiénes son ustedes",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-110",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "De dónde sacaron mi número",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-111",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Esto es real?",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-112",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "No sé quiénes son",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-113",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Qué empresa es esa",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-114",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Dónde están ubicados",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-115",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Esto no será estafa?",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-116",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Quién les dio mi contacto",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-117",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Quiénes son ustedes",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-118",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "De dónde sacaron mi número",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-119",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Esto es real?",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-120",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "No sé quiénes son",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-121",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Qué empresa es esa",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-122",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Dónde están ubicados",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-123",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Esto no será estafa?",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-124",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Quién les dio mi contacto",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-125",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Quiénes son ustedes",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-126",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "De dónde sacaron mi número",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-127",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Esto es real?",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-128",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "No sé quiénes son",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-129",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Qué empresa es esa",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-130",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Dónde están ubicados",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-131",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Esto no será estafa?",
      "ah ya, quiero saber qué ofrecen"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-132",
    "origen_probable": "desconocido",
    "categoria_prueba": "desconfianza",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "responder_identidad_y_no_presionar",
    "mensajes_cliente": [
      "Quién les dio mi contacto",
      "no gracias"
    ],
    "observaciones_prueba": "Debe manejar seguridad, no solicitar datos sensibles ni insistir."
  },
  {
    "id": "ESC-133",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No gracias"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-134",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No me interesa"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-135",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Ahora no"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-136",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Más adelante"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-137",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No molesten"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-138",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Déjelo no más"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-139",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No tengo tiempo"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-140",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Después veo"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-141",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No gracias"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-142",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No me interesa"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-143",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Ahora no"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-144",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Más adelante"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-145",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No molesten"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-146",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Déjelo no más"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-147",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No tengo tiempo"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-148",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Después veo"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-149",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No gracias"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-150",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No me interesa"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-151",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Ahora no"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-152",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Más adelante"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-153",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No molesten"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-154",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Déjelo no más"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-155",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No tengo tiempo"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-156",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Después veo"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-157",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No gracias"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-158",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No me interesa"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-159",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Ahora no"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-160",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Más adelante"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-161",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No molesten"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-162",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Déjelo no más"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-163",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "No tengo tiempo"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-164",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "rechazo",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "cerrar_sin_insistir",
    "mensajes_cliente": [
      "Después veo"
    ],
    "observaciones_prueba": "Debe cerrar con salida amable y registrar sin insistir."
  },
  {
    "id": "ESC-165",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "bananera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo permiso",
      "tengo una finca bananera",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-166",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo licencia ambiental",
      "manejo piscinas de camarón",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-167",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "mineria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "todo está al día",
      "tengo una cantera",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-168",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo consultor",
      "soy productor cacaotero",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-169",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "eso me lo ve otra persona",
      "tengo yuca y maní",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-170",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "mi ingeniero ve eso",
      "tengo porqueriza",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-171",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo permiso",
      "tengo una granja avícola",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-172",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "hotel",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo licencia ambiental",
      "manejo un hotel",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-173",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "todo está al día",
      "tengo una piladora",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-174",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "otra",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo consultor",
      "tengo una empresa pequeña",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-175",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "bananera",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "eso me lo ve otra persona",
      "manejo una bananera en Pasaje",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-176",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "mi ingeniero ve eso",
      "tengo una camarnra",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-177",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "mineria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo permiso",
      "tengo una concesión minera",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-178",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo licencia ambiental",
      "manejo una finca cacaotera",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-179",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "todo está al día",
      "tengo arroz y maíz",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-180",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo consultor",
      "tengo una chankera",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-181",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "eso me lo ve otra persona",
      "tengo una avikola",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-182",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "hotel",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "mi ingeniero ve eso",
      "tengo una quinta turística",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-183",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo permiso",
      "tengo una empacadora",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-184",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "otra",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo licencia ambiental",
      "tengo una empresa pequeña",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-185",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "bananera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "todo está al día",
      "tengo una hacienda bananera",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-186",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "ya tengo consultor",
      "tengo una camaronera",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-187",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "mineria",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "eso me lo ve otra persona",
      "tengo una mina pequeña",
      "solo quiero saber si igual revisan documentación"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-188",
    "origen_probable": "campana_whatsapp",
    "categoria_prueba": "ya_tiene_permiso_o_consultor",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "consultor",
    "resultado_esperado": "ofrecer_revision_no_invasiva",
    "mensajes_cliente": [
      "mi ingeniero ve eso",
      "trabajamos con cacao nacional",
      "quiero seguimiento mensual"
    ],
    "observaciones_prueba": "Debe no confrontar al consultor actual y proponer revisión documental/seguimiento."
  },
  {
    "id": "ESC-189",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "tengo una finca bananera",
      "el banco me pide papeles",
      "prefiero llamada",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-190",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "manejo piscinas de camarón",
      "es por GlobalGAP",
      "pueden venir a la finca",
      "Soy Carlos Vera, mañana por la mañana en El Guabo"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-191",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo una cantera",
      "necesito regularizar",
      "dese una vuelta",
      "A nombre de Marjorie Castro, viernes a las 10am por Barbones"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-192",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "soy productor cacaotero",
      "quiero mantener todo al día",
      "mejor por teléfono",
      "Regístreme como Luis Andrade, pasado mañana al mediodía"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-193",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo yuca y maní",
      "me hicieron una observación",
      "lo puedo recibir en la propiedad",
      "Don Pedro, el lunes temprano en la finca San Miguel"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-194",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo porqueriza",
      "es requisito bancario",
      "prefiero visita",
      "Ricardo mena mañana en la tarde en la camaronera Los Esteros"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-195",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "tengo una granja avícola",
      "me pide una certificadora",
      "llámeme mejor",
      "Soy Ana Zambrano, hoy después del almuerzo"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-196",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "hotel",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "manejo un hotel",
      "no tengo permiso ambiental",
      "dese una vuelta",
      "María Solano, miércoles a eso de las 11 por la vía a Machala"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-197",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo una piladora",
      "necesito plan de manejo y monitoreos",
      "mejor que revisen en sitio",
      "Jorge Vera, el jueves a media tarde en mi finca"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-198",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "otra",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "tengo una empresa pequeña",
      "el municipio me pidió documentación",
      "una llamada primero",
      "Karla Jiménez, mañana tipo 10"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-199",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "manejo una bananera en Pasaje",
      "me piden licencia para préstamo",
      "prefiero visita",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm sector La Peaña"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-200",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo una camarnra",
      "el cliente internacional pide cumplimiento",
      "pueden venir a la finca",
      "Soy Carlos Vera, mañana por la mañana en El Guabo"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-201",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "tengo una concesión minera",
      "quiero sacar licencia ambiental",
      "quisiera que me llamen",
      "A nombre de Marjorie Castro, viernes a las 10am"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-202",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "manejo una finca cacaotera",
      "necesito informes ambientales",
      "mejor que revisen en sitio",
      "Regístreme como Luis Andrade, pasado mañana al mediodía vía Tendales"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-203",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo arroz y maíz",
      "tengo inspección del MAATE",
      "lo puedo recibir en la propiedad",
      "Don Pedro, el lunes temprano en la finca San Miguel"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-204",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "tengo una chankera",
      "necesito por financiamiento",
      "prefiero llamada",
      "Ricardo mena mañana en la tarde"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-205",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo una avikola",
      "Rainforest me observó eso",
      "pueden venir a la finca",
      "Soy Ana Zambrano, hoy después del almuerzo recinto Buenavista"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-206",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "hotel",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo una quinta turística",
      "no tengo papeles ambientales",
      "dese una vuelta",
      "María Solano, miércoles a eso de las 11 por la vía a Machala"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-207",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "tengo una empacadora",
      "ya tengo permiso pero quiero seguimiento",
      "mejor por teléfono",
      "Jorge Vera, el jueves a media tarde"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-208",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "otra",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo una empresa pequeña",
      "me llegó un oficio",
      "lo puedo recibir en la propiedad",
      "Karla Jiménez, mañana tipo 10 en el predio"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-209",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo una hacienda bananera",
      "BanEcuador me está pidiendo eso",
      "prefiero visita",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm sector La Peaña"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-210",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "tengo una camaronera",
      "lo necesito para exportar",
      "llámeme mejor",
      "Soy Carlos Vera, mañana por la mañana"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-211",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo una mina pequeña",
      "quiero saber qué trámite me corresponde",
      "dese una vuelta",
      "A nombre de Marjorie Castro, viernes a las 10am por Barbones"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-212",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "trabajamos con cacao nacional",
      "tengo permiso pero no sé si tengo obligaciones pendientes",
      "mejor que revisen en sitio",
      "Regístreme como Luis Andrade, pasado mañana al mediodía vía Tendales"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-213",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "tengo cultivo de ciclo corto",
      "me notificó el Ministerio",
      "una llamada primero",
      "Don Pedro, el lunes temprano"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-214",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo chanchera",
      "es para un crédito",
      "prefiero visita",
      "Ricardo mena mañana en la tarde en la camaronera Los Esteros"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-215",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo gallinas ponedoras",
      "es para auditoría de certificación",
      "pueden venir a la finca",
      "Soy Ana Zambrano, hoy después del almuerzo recinto Buenavista"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-216",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "hotel",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "tengo un hostal",
      "me dijeron que saque registro ambiental",
      "quisiera que me llamen",
      "María Solano, miércoles a eso de las 11"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-217",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo un centro de acopio",
      "necesito acompañamiento mensual",
      "mejor que revisen en sitio",
      "Jorge Vera, el jueves a media tarde en mi finca"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-218",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "otra",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo una empresa pequeña",
      "me preocupa una sanción",
      "lo puedo recibir en la propiedad",
      "Karla Jiménez, mañana tipo 10 en el predio"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-219",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "tengo plantación de banano",
      "el banco me pide papeles",
      "prefiero llamada",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-220",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo cultivo de camarón",
      "es por GlobalGAP",
      "pueden venir a la finca",
      "Soy Carlos Vera, mañana por la mañana en El Guabo"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-221",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo una cantera",
      "necesito regularizar",
      "dese una vuelta",
      "A nombre de Marjorie Castro, viernes a las 10am por Barbones"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-222",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_llamada",
    "mensajes_cliente": [
      "Hola",
      "soy productor cacaotero",
      "quiero mantener todo al día",
      "mejor por teléfono",
      "Regístreme como Luis Andrade, pasado mañana al mediodía"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-223",
    "origen_probable": "fragmentado",
    "categoria_prueba": "mensajes_partidos",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_visita",
    "mensajes_cliente": [
      "Hola",
      "tengo yuca y maní",
      "me hicieron una observación",
      "lo puedo recibir en la propiedad",
      "Don Pedro, el lunes temprano en la finca San Miguel"
    ],
    "observaciones_prueba": "Debe agrupar mensajes si llegan seguidos y no responder cada fragmento."
  },
  {
    "id": "ESC-224",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Buenas",
      "Usted también hace créditos?",
      "tengo bananera",
      "el banco me pide licencia"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-225",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Hola",
      "y si no tengo papeles qué pasa",
      "tengo camaronera",
      "quiero revisar"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-226",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Me da miedo lo del ministerio",
      "tengo una chanchera",
      "me notificaron"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-227",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Mándeme ubicación de ustedes",
      "tengo hotel",
      "quiero saber requisitos"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-228",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Esto es para multas?",
      "manejo industria",
      "me llegó oficio"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-229",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "No entiendo nada de licencia",
      "tengo cacao",
      "quiero orientación"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-230",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Buenas",
      "Usted también hace créditos?",
      "tengo bananera",
      "el banco me pide licencia"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-231",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Hola",
      "y si no tengo papeles qué pasa",
      "tengo camaronera",
      "quiero revisar"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-232",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Me da miedo lo del ministerio",
      "tengo una chanchera",
      "me notificaron"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-233",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Mándeme ubicación de ustedes",
      "tengo hotel",
      "quiero saber requisitos"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-234",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Esto es para multas?",
      "manejo industria",
      "me llegó oficio"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-235",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "No entiendo nada de licencia",
      "tengo cacao",
      "quiero orientación"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-236",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Buenas",
      "Usted también hace créditos?",
      "tengo bananera",
      "el banco me pide licencia"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-237",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Hola",
      "y si no tengo papeles qué pasa",
      "tengo camaronera",
      "quiero revisar"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-238",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Me da miedo lo del ministerio",
      "tengo una chanchera",
      "me notificaron"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-239",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Mándeme ubicación de ustedes",
      "tengo hotel",
      "quiero saber requisitos"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-240",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Esto es para multas?",
      "manejo industria",
      "me llegó oficio"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-241",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "No entiendo nada de licencia",
      "tengo cacao",
      "quiero orientación"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-242",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Buenas",
      "Usted también hace créditos?",
      "tengo bananera",
      "el banco me pide licencia"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-243",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Hola",
      "y si no tengo papeles qué pasa",
      "tengo camaronera",
      "quiero revisar"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-244",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Me da miedo lo del ministerio",
      "tengo una chanchera",
      "me notificaron"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-245",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Mándeme ubicación de ustedes",
      "tengo hotel",
      "quiero saber requisitos"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-246",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Esto es para multas?",
      "manejo industria",
      "me llegó oficio"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-247",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "No entiendo nada de licencia",
      "tengo cacao",
      "quiero orientación"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-248",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Buenas",
      "Usted también hace créditos?",
      "tengo bananera",
      "el banco me pide licencia"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-249",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Hola",
      "y si no tengo papeles qué pasa",
      "tengo camaronera",
      "quiero revisar"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-250",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Me da miedo lo del ministerio",
      "tengo una chanchera",
      "me notificaron"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-251",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Mándeme ubicación de ustedes",
      "tengo hotel",
      "quiero saber requisitos"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-252",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "Esto es para multas?",
      "manejo industria",
      "me llegó oficio"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-253",
    "origen_probable": "redes_o_campana",
    "categoria_prueba": "confuso_desvio_tema",
    "actividad_esperada": null,
    "motivo_esperado": null,
    "resultado_esperado": "aclarar_con_naturalidad",
    "mensajes_cliente": [
      "No entiendo nada de licencia",
      "tengo cacao",
      "quiero orientación"
    ],
    "observaciones_prueba": "Debe aclarar sin regañar y volver a actividad/motivo."
  },
  {
    "id": "ESC-254",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una finca bananera",
      "el banco me pide papeles",
      "prefiero llamada",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-255",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "manejo piscinas de camarón",
      "es por GlobalGAP",
      "pueden venir a la finca",
      "Soy Carlos Vera, mañana por la mañana en El Guabo"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-256",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una cantera",
      "necesito regularizar",
      "quisiera que me llamen",
      "A nombre de Marjorie Castro, viernes a las 10am"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-257",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "soy productor cacaotero",
      "quiero mantener todo al día",
      "mejor que revisen en sitio",
      "Regístreme como Luis Andrade, pasado mañana al mediodía vía Tendales"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-258",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo yuca y maní",
      "me hicieron una observación",
      "una llamada primero",
      "Don Pedro, el lunes temprano"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-259",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo porqueriza",
      "es requisito bancario",
      "prefiero visita",
      "Ricardo mena mañana en la tarde en la camaronera Los Esteros"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-260",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una granja avícola",
      "me pide una certificadora",
      "llámeme mejor",
      "Soy Ana Zambrano, hoy después del almuerzo"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-261",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "hotel",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "manejo un hotel",
      "no tengo permiso ambiental",
      "dese una vuelta",
      "María Solano, miércoles a eso de las 11 por la vía a Machala"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-262",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una piladora",
      "necesito plan de manejo y monitoreos",
      "mejor por teléfono",
      "Jorge Vera, el jueves a media tarde"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-263",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "otra",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una empresa pequeña",
      "el municipio me pidió documentación",
      "lo puedo recibir en la propiedad",
      "Karla Jiménez, mañana tipo 10 en el predio"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-264",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "manejo una bananera en Pasaje",
      "me piden licencia para préstamo",
      "prefiero llamada",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-265",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una camarnra",
      "el cliente internacional pide cumplimiento",
      "pueden venir a la finca",
      "Soy Carlos Vera, mañana por la mañana en El Guabo"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-266",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una concesión minera",
      "quiero sacar licencia ambiental",
      "quisiera que me llamen",
      "A nombre de Marjorie Castro, viernes a las 10am"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-267",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "manejo una finca cacaotera",
      "necesito informes ambientales",
      "mejor que revisen en sitio",
      "Regístreme como Luis Andrade, pasado mañana al mediodía vía Tendales"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-268",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo arroz y maíz",
      "tengo inspección del MAATE",
      "una llamada primero",
      "Don Pedro, el lunes temprano"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-269",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una chankera",
      "necesito por financiamiento",
      "prefiero visita",
      "Ricardo mena mañana en la tarde en la camaronera Los Esteros"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-270",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una avikola",
      "Rainforest me observó eso",
      "llámeme mejor",
      "Soy Ana Zambrano, hoy después del almuerzo"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-271",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "hotel",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una quinta turística",
      "no tengo papeles ambientales",
      "dese una vuelta",
      "María Solano, miércoles a eso de las 11 por la vía a Machala"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-272",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una empacadora",
      "ya tengo permiso pero quiero seguimiento",
      "mejor por teléfono",
      "Jorge Vera, el jueves a media tarde"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-273",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "otra",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una empresa pequeña",
      "me llegó un oficio",
      "lo puedo recibir en la propiedad",
      "Karla Jiménez, mañana tipo 10 en el predio"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-274",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una hacienda bananera",
      "BanEcuador me está pidiendo eso",
      "prefiero llamada",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-275",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una camaronera",
      "lo necesito para exportar",
      "pueden venir a la finca",
      "Soy Carlos Vera, mañana por la mañana en El Guabo"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-276",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "mineria",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una mina pequeña",
      "quiero saber qué trámite me corresponde",
      "quisiera que me llamen",
      "A nombre de Marjorie Castro, viernes a las 10am"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-277",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "trabajamos con cacao nacional",
      "tengo permiso pero no sé si tengo obligaciones pendientes",
      "mejor que revisen en sitio",
      "Regístreme como Luis Andrade, pasado mañana al mediodía vía Tendales"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-278",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo cultivo de ciclo corto",
      "me notificó el Ministerio",
      "una llamada primero",
      "Don Pedro, el lunes temprano"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-279",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo chanchera",
      "es para un crédito",
      "prefiero visita",
      "Ricardo mena mañana en la tarde en la camaronera Los Esteros"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-280",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "certificacion",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo gallinas ponedoras",
      "es para auditoría de certificación",
      "llámeme mejor",
      "Soy Ana Zambrano, hoy después del almuerzo"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-281",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "hotel",
    "motivo_esperado": "regularizacion",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo un hostal",
      "me dijeron que saque registro ambiental",
      "dese una vuelta",
      "María Solano, miércoles a eso de las 11 por la vía a Machala"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-282",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "industria",
    "motivo_esperado": "seguimiento",
    "resultado_esperado": "registrar_llamada_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo un centro de acopio",
      "necesito acompañamiento mensual",
      "mejor por teléfono",
      "Jorge Vera, el jueves a media tarde"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-283",
    "origen_probable": "prueba_datos_compuestos",
    "categoria_prueba": "nombre_fecha_hora_en_mismo_mensaje",
    "actividad_esperada": "otra",
    "motivo_esperado": "autoridad",
    "resultado_esperado": "registrar_visita_sin_pedir_nombre_repetido",
    "mensajes_cliente": [
      "Quiero información",
      "tengo una empresa pequeña",
      "me preocupa una sanción",
      "lo puedo recibir en la propiedad",
      "Karla Jiménez, mañana tipo 10 en el predio"
    ],
    "observaciones_prueba": "Debe extraer nombre, fecha y hora del mismo mensaje."
  },
  {
    "id": "ESC-284",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo una finca bananera",
      "es por crédito del banco",
      "prefiero llamada",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm",
      "mejor cambiemos para el viernes a las 10am"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-285",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "manejo piscinas de camarón",
      "es por crédito del banco",
      "pueden venir a la finca",
      "Soy Carlos Vera, mañana por la mañana en El Guabo",
      "cancele la cita por ahora"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-286",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "mineria",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo una cantera",
      "es por crédito del banco",
      "quisiera que me llamen",
      "A nombre de Marjorie Castro, viernes a las 10am",
      "también tengo otra finca"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-287",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "soy productor cacaotero",
      "es por crédito del banco",
      "mejor que revisen en sitio",
      "Regístreme como Luis Andrade, pasado mañana al mediodía vía Tendales",
      "muchas gracias"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-288",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo yuca y maní",
      "es por crédito del banco",
      "una llamada primero",
      "Don Pedro, el lunes temprano",
      "tengo otra camaronera que quiero revisar"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-289",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo porqueriza",
      "es por crédito del banco",
      "prefiero visita",
      "Ricardo mena mañana en la tarde en la camaronera Los Esteros",
      "mejor cambiemos para el viernes a las 10am"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-290",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo una granja avícola",
      "es por crédito del banco",
      "llámeme mejor",
      "Soy Ana Zambrano, hoy después del almuerzo",
      "cancele la cita por ahora"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-291",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "hotel",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "manejo un hotel",
      "es por crédito del banco",
      "dese una vuelta",
      "María Solano, miércoles a eso de las 11 por la vía a Machala",
      "también tengo otra finca"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-292",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "industria",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo una piladora",
      "es por crédito del banco",
      "mejor por teléfono",
      "Jorge Vera, el jueves a media tarde",
      "muchas gracias"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-293",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "otra",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo una empresa pequeña",
      "es por crédito del banco",
      "lo puedo recibir en la propiedad",
      "Karla Jiménez, mañana tipo 10 en el predio",
      "tengo otra camaronera que quiero revisar"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-294",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "bananera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "manejo una bananera en Pasaje",
      "es por crédito del banco",
      "prefiero llamada",
      "Mi nombre es Ricardo Mena y estaría bien el jueves a las 3pm",
      "mejor cambiemos para el viernes a las 10am"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-295",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "camaronera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo una camarnra",
      "es por crédito del banco",
      "pueden venir a la finca",
      "Soy Carlos Vera, mañana por la mañana en El Guabo",
      "cancele la cita por ahora"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-296",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "mineria",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo una concesión minera",
      "es por crédito del banco",
      "quisiera que me llamen",
      "A nombre de Marjorie Castro, viernes a las 10am",
      "también tengo otra finca"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-297",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "cacaotera",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "manejo una finca cacaotera",
      "es por crédito del banco",
      "mejor que revisen en sitio",
      "Regístreme como Luis Andrade, pasado mañana al mediodía vía Tendales",
      "muchas gracias"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-298",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "cultivo_ciclo_corto",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo arroz y maíz",
      "es por crédito del banco",
      "una llamada primero",
      "Don Pedro, el lunes temprano",
      "tengo otra camaronera que quiero revisar"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-299",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "granja_porcina",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo una chankera",
      "es por crédito del banco",
      "prefiero visita",
      "Ricardo mena mañana en la tarde en la camaronera Los Esteros",
      "mejor cambiemos para el viernes a las 10am"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  },
  {
    "id": "ESC-300",
    "origen_probable": "post_cita",
    "categoria_prueba": "post_cierre",
    "actividad_esperada": "granja_avicola",
    "motivo_esperado": "credito_bancario",
    "resultado_esperado": "manejar_post_cita",
    "mensajes_cliente": [
      "Vengo de Facebook",
      "tengo una avikola",
      "es por crédito del banco",
      "llámeme mejor",
      "Soy Ana Zambrano, hoy después del almuerzo",
      "cancele la cita por ahora"
    ],
    "observaciones_prueba": "Debe no reiniciar conversación; manejar cambio/cancelación/nueva finca/despedida."
  }
]
""")


def ejecutar_simulacion():
    try:
        from gestor_conversacion import manejar_conversacion
    except Exception as e:
        print("No pude importar gestor_conversacion.manejar_conversacion.")
        print("Error:", e)
        print("Total de escenarios cargados:", len(ESCENARIOS))
        print("Puedes usar ESCENARIOS como base de pruebas manuales.")
        return

    total = len(ESCENARIOS)
    conversaciones_con_cita_o_llamada = 0
    eventos_sin_respuesta = 0
    errores = []
    resumen_por_resultado = {}

    for idx, escenario in enumerate(ESCENARIOS, start=1):
        telefono = "593990" + str(idx).zfill(6)
        estado = None
        hubo_cita = False

        resultado_esperado = escenario.get("resultado_esperado", "sin_clasificar")
        resumen_por_resultado[resultado_esperado] = resumen_por_resultado.get(resultado_esperado, 0) + 1

        try:
            for mensaje in escenario["mensajes_cliente"]:
                try:
                    # Versión actual recomendada.
                    resultado = manejar_conversacion(
                        telefono=telefono,
                        mensaje=mensaje,
                        estado_actual=estado
                    )
                except TypeError:
                    # Compatibilidad con versiones antiguas.
                    resultado = manejar_conversacion(telefono, mensaje)

                if not isinstance(resultado, dict):
                    errores.append({
                        "id": escenario["id"],
                        "error": "manejar_conversacion no devolvió un diccionario",
                        "mensaje": mensaje,
                        "resultado": str(resultado),
                    })
                    continue

                estado = resultado.get("estado", estado)

                if not resultado.get("respuesta"):
                    eventos_sin_respuesta += 1

                if resultado.get("registrar_cita"):
                    hubo_cita = True

                if resultado.get("actualizar_cita") or resultado.get("cancelar_cita"):
                    hubo_cita = True

        except Exception as e:
            errores.append({
                "id": escenario["id"],
                "error": str(e),
                "mensajes_cliente": escenario.get("mensajes_cliente", []),
                "categoria_prueba": escenario.get("categoria_prueba", ""),
                "resultado_esperado": escenario.get("resultado_esperado", ""),
            })

        if hubo_cita:
            conversaciones_con_cita_o_llamada += 1

    print("=" * 70)
    print("SIMULACIÓN DALGORO - 300 ESCENARIOS")
    print("=" * 70)
    print("Total de escenarios:", total)
    print("Conversaciones con cita/llamada/cambio/cancelación detectada:", conversaciones_con_cita_o_llamada)
    print("Eventos sin respuesta:", eventos_sin_respuesta)
    print("Errores críticos:", len(errores))

    print("\nResumen por resultado esperado:")
    for clave, valor in sorted(resumen_por_resultado.items()):
        print(f"- {clave}: {valor}")

    if errores:
        print("\nPrimeros errores detectados:")
        for err in errores[:15]:
            print("-" * 50)
            print("ID:", err.get("id"))
            print("Categoría:", err.get("categoria_prueba"))
            print("Resultado esperado:", err.get("resultado_esperado"))
            print("Error:", err.get("error"))
            print("Mensajes:", err.get("mensajes_cliente", err.get("mensaje", "")))

    print("\nFin de simulación.")


if __name__ == "__main__":
    ejecutar_simulacion()
