# -*- coding: utf-8 -*-
"""
Léxico base DALGORO S.A.S. - V8.2

Centraliza palabras, frases, errores comunes y modismos para mejorar el
reconocimiento de intención en WhatsApp sin cambiar la arquitectura del bot.

Regla de mantenimiento:
- Agregar nuevas frases aquí.
- No modificar webhook.py ni google_sheets_utils.py para nuevos reconocimientos.
- Evitar términos demasiado genéricos cuando puedan causar falsos positivos.
"""

# ======================================================
# ACTIVIDADES DE SERVICIO
# ======================================================
# Claves usadas por el sistema:
# bananera, camaronera, mineria, cacaotera, cultivo_ciclo_corto,
# granja_porcina, granja_avicola, hotel, industria.

ACTIVIDADES_LEXICO = {
    "bananera": [
        # Formales
        "banano", "bananera", "bananero", "bananeras", "finca bananera",
        "hacienda bananera", "predio bananero", "finca de banano", "hacienda de banano",
        "plantacion de banano", "plantación de banano", "cultivo de banano",
        "produccion de banano", "producción de banano", "productor bananero",
        "productora bananera", "empresa bananera", "exportadora bananera",
        "empacadora bananera", "unidad productiva bananera", "cultivo bananero",
        # Locales/coloquiales
        "guineo", "guineal", "banana", "platanera", "platanero", "platano", "plátano",
        "verde", "finca de verde", "hacienda de verde", "sembrio de banano", "sembrío de banano",
        "sembrio de guineo", "sembrío de guineo", "bananito", "orito",
        # Errores comunes
        "bananra", "bananeraa", "bananeraa", "bananna", "bannano", "bananoo",
        "bananeraa", "guinio", "gineo", "gineal", "platano", "plantacion bananera",
    ],

    "camaronera": [
        # Formales
        "camaron", "camarón", "camarones", "camaronera", "camaroneras", "camaronero",
        "actividad camaronera", "sector camaronero", "produccion camaronera",
        "producción camaronera", "cultivo de camaron", "cultivo de camarón",
        "camaronicultura", "camaronicola", "camaronícola", "finca camaronera",
        "piscina camaronera", "piscinas camaroneras", "piscina de camaron",
        "piscina de camarón", "piscinas de camaron", "piscinas de camarón",
        "piscinas de camarones", "criadero de camaron", "criadero de camarón",
        "engorde de camaron", "engorde de camarón", "precriadero", "pre criadero",
        "laboratorio de larvas", "laboratorio de larva", "larvicultura", "larvas de camaron",
        "larvas de camarón",
        # Locales/coloquiales
        "piscinas", "piscina", "camaronera pequeña", "camaronera chica",
        "camaronera artesanal", "camaronera industrial",
        # Errores comunes
        "camarnra", "camaornera", "camaronra", "camaroneraa", "camarn", "camarnera",
        "camaromera", "camarónra", "camaronicola", "camaronikola", "camaroniculturaa",
    ],

    "mineria": [
        # Formales
        "mineria", "minería", "minera", "minero", "actividad minera", "proyecto minero",
        "concesion minera", "concesión minera", "area minera", "área minera", "mina",
        "material petreo", "material pétreo", "extraccion minera", "extracción minera",
        "explotacion minera", "explotación minera", "libre aprovechamiento", "aridos", "áridos",
        "cantera", "canteras", "planta de trituracion", "planta de trituración", "trituradora",
        "zaranda", "clasificadora de material", "material de construccion", "material de construcción",
        "lavado de material", "cribado de material", "chancadora", "concesion", "concesión",
        # Materiales
        "grava", "ripio", "lastre", "arena", "piedra bola", "piedra triturada", "piedra azul",
        "piedra de rio", "piedra de río", "material de rio", "material de río", "material granular",
        # Errores comunes
        "minria", "meneria", "mineriaa", "materia petreo", "material petreo", "arido", "aridos",
        "consecion minera", "conseción minera", "triturasora", "triturasion",
    ],

    "cacaotera": [
        # Formales
        "cacao", "cacaotera", "cacaotero", "finca cacaotera", "finca de cacao",
        "hacienda cacaotera", "predio cacaotero", "plantacion de cacao", "plantación de cacao",
        "cultivo de cacao", "produccion de cacao", "producción de cacao", "productor cacaotero",
        "centro de acopio de cacao", "beneficio de cacao", "secado de cacao", "fermentacion de cacao",
        "fermentación de cacao", "pepa de cacao", "cacao nacional", "cacao fino de aroma",
        # Locales/coloquiales
        "cacaotal", "trabajo con cacao", "finca cacao", "sembrio de cacao", "sembrío de cacao",
        # Errores comunes
        "kakao", "cacaco", "cacatero", "cacaotera", "cacaotero", "cacaoo", "kacaotera",
    ],

    "cultivo_ciclo_corto": [
        # Formales
        "ciclo corto", "cultivo de ciclo corto", "cultivos de ciclo corto", "cultivo corto",
        "cultivos cortos", "actividad agricola", "actividad agrícola", "produccion agricola",
        "producción agrícola", "finca agricola", "finca agrícola", "predio agricola", "predio agrícola",
        "agricultura", "agricola", "agrícola", "cultivo agricola", "cultivo agrícola",
        "siembra", "sembrio", "sembrío", "cultivos", "cultivo",
        # Cultivos frecuentes
        "maiz", "maíz", "arroz", "yuca", "mani", "maní", "frijol", "frejol", "frejoles",
        "hortaliza", "hortalizas", "legumbres", "tomate", "cebolla", "pimiento", "pepino",
        "sandia", "sandía", "melon", "melón", "soya", "soja", "papa", "camote", "cilantro",
        "lechuga", "col", "brocoli", "brócoli", "zanahoria", "verduras", "zapallo", "pepinillo",
        "habichuela", "arveja", "haba", "maracuya", "maracuyá", "papaya", "piña", "pina",
        # Frases comunes
        "cultivo de maiz", "cultivo de maíz", "cultivo de arroz", "siembra de arroz",
        "siembra de maiz", "siembra de maíz", "sembrio de arroz", "sembrío de arroz",
        # Errores comunes
        "cultvo", "cultibo", "cultivoo", "hortalisa", "hortalisas", "mais", "maís", "fresol",
        "frejoless", "legunbres",
    ],

    "granja_porcina": [
        # Formales
        "porcina", "porcino", "granja porcina", "actividad porcina", "produccion porcina",
        "producción porcina", "cria de cerdos", "cría de cerdos", "engorde de cerdos",
        "criadero de cerdos", "plantel porcino", "explotacion porcina", "explotación porcina",
        "granja de cerdos", "cerdos de engorde", "madres porcinas", "maternidad porcina",
        # Locales/coloquiales
        "cerdo", "cerdos", "chancho", "chanchos", "chanchera", "granja de chanchos",
        "marranos", "porqueriza", "lechon", "lechón", "lechones", "cochinos", "chancheria", "chanchería",
        # Errores comunes
        "chankera", "chanquera", "porquiza", "porquerisa", "serdos", "sherdos", "granja porsina",
        "porsina", "porsino",
    ],

    "granja_avicola": [
        # Formales
        "avicola", "avícola", "granja avicola", "granja avícola", "actividad avicola",
        "actividad avícola", "produccion avicola", "producción avícola", "plantel avicola",
        "plantel avícola", "cria de aves", "cría de aves", "engorde de pollos",
        "pollos de engorde", "gallinas ponedoras", "aves de corral", "criadero de aves",
        "criadero de pollos", "plantel de aves",
        # Infraestructura y términos comunes
        "aves", "pollo", "pollos", "gallina", "gallinas", "galpon", "galpón", "galpones",
        "galpon de pollos", "galpón de pollos", "gallinero", "pollera", "ponedoras", "granja de aves",
        # Errores comunes
        "avikola", "avicolaa", "abicola", "abícola", "gayinas", "gallenero", "galpones de pollo",
        "granja avikola", "abikolaa",
    ],

    "hotel": [
        # Formales
        "hotel", "hoteles", "hosteria", "hostería", "hostal", "actividad turistica",
        "actividad turística", "establecimiento turistico", "establecimiento turístico",
        "servicio de hospedaje", "alojamiento", "alojamiento turistico", "alojamiento turístico",
        "hospedaje", "turismo", "turistico", "turístico", "servicio turistico", "servicio turístico",
        # Términos comunes
        "cabanas", "cabañas", "quinta turistica", "quinta turística", "resort", "eco lodge", "ecolodge",
        "casa de hospedaje", "hosteria campestre", "hostería campestre", "centro turistico",
        "centro turístico", "lodge", "paradero turistico", "paradero turístico",
        # Errores comunes
        "osteria", "hoteleria", "hotelería", "cavanas", "cabannas", "hosteriaa", "hostaal",
    ],

    "industria": [
        # Formales
        "industria", "industrial", "empresa industrial", "actividad industrial", "planta",
        "planta industrial", "planta de procesamiento", "procesadora", "planta procesadora",
        "procesamiento", "agroindustria", "centro de acopio", "fabrica", "fábrica", "manufactura",
        "bodega industrial", "taller industrial", "proceso industrial",
        # Actividades frecuentes
        "empacadora", "empakadora", "empacadora de banano", "empacadora de camaron",
        "empacadora de camarón", "piladora", "piladora de arroz", "taller mecanico", "taller mecánico",
        "lavadora", "lavadora de vehiculos", "lavadora de vehículos", "lubricadora", "aserradero",
        "maderera", "metal mecanica", "metalmecanica", "metalmecánica", "procesadora de alimentos",
        "planta de balanceado", "balanceadora", "faenadora", "centro de faenamiento", "embotelladora",
        "recicladora", "textil", "panificadora industrial", "frigorifico", "frigorífico", "camal",
        # Errores comunes
        "enpacadora", "fabrika", "procesaminto", "procesadoraa", "agroindustriaa", "piladoraa",
    ],

    "otra": [
        # Cuando el cliente sí indica que tiene una actividad, pero aún no clasifica
        "actividad productiva", "otra actividad", "actividad comercial", "actividad agricola",
        "actividad agrícola", "negocio rural", "negocio productivo", "empresa pequena",
        "empresa pequeña", "empresa familiar", "emprendimiento", "proyecto productivo",
        "proyecto agricola", "proyecto agrícola", "unidad productiva", "predio productivo",
        "actividad en el campo", "trabajo en el campo", "actividad rural", "productor",
        "productores", "asociacion de productores", "asociación de productores",
        "asociacion", "asociación", "pequena empresa", "pequeña empresa",
        "no se que categoria", "no sé qué categoría", "no se que aplica",
        "no sé qué aplica", "no se donde entra", "no sé dónde entra",
        "negocio pequeno", "negocio pequeño", "actividad pequena", "actividad pequeña",
    ],
}

# ======================================================
# MOTIVOS / NECESIDADES
# ======================================================

MOTIVOS_LEXICO = {
    "credito_bancario": [
        "banco", "bco", "bnco", "credito", "crédito", "credto", "crdito", "crediticio",
        "prestamo", "préstamo", "prestmo", "financiamiento", "financiar", "banecuador", "banca",
        "cooperativa", "cooperativa de ahorro", "corporacion financiera", "institucion financiera",
        "me piden para credito", "me piden para crédito", "credito agricola", "crédito agrícola",
        "credito productivo", "crédito productivo", "para credito", "para crédito", "para el banco",
        "papeles para el banco", "documentos para el banco", "requisito del banco",
        "requisitos del banco", "me estan pidiendo en el banco", "me están pidiendo en el banco",
        "el banco me pide", "el banco me solicito", "el banco me solicitó", "para un prestamo",
        "para un préstamo", "para acceder a credito", "para acceder a crédito", "credito bananero",
        "crédito bananero", "credito camaronero", "crédito camaronero",
    ],
    "certificacion": [
        "certificacion", "certificación", "sertificacion", "certifiacion", "certi", "certificadora",
        "globalgap", "global ga", "global gap", "rainforest", "rain forest", "auditoria", "auditoría",
        "auditoria externa", "auditoría externa", "auditor", "auditores", "exportacion", "exportación",
        "exportar", "exportadora", "certificado", "certificar", "cliente internacional", "cliente extranjero",
        "sello", "norma de certificacion", "norma de certificación", "bpa", "buenas practicas agricolas",
        "buenas prácticas agrícolas", "certificacion agricola", "certificación agrícola", "requisito de exportacion",
        "requisito de exportación",
    ],
    "regularizacion": [
        "regularizar", "regularizacion", "regularización", "regulaizar", "licencia", "licensia",
        "licencia ambiental", "registro ambiental", "permiso ambiental", "permizo ambiental",
        "autorizacion ambiental", "autorización ambiental", "certificado ambiental", "licenciamiento",
        "licenciamiento ambiental", "sui", "suia", "suy", "sistema ambiental", "tramite ambiental",
        "trámite ambiental", "sacar permiso", "sacar el permiso", "obtener permiso", "obtener licencia",
        "no tengo permiso", "no cuento con permiso", "no tengo licencia", "no tengo registro",
        "aun no tengo", "aún no tengo", "todavia no tengo", "todavía no tengo", "no tengo papeles",
        "necesito sacar la licencia", "eso de la licencia ambiental", "me falta licencia", "me falta permiso",
        "quiero regularizar", "quiero sacar permiso", "quiero sacar la licencia", "tramitar licencia",
        "tramitar permiso", "empezar el tramite", "empezar el trámite", "desde cero", "no he sacado nada",
        "que tramite me corresponde", "qué trámite me corresponde", "que permiso me corresponde",
        "qué permiso me corresponde", "que debo tramitar", "qué debo tramitar",
        "que debo sacar", "qué debo sacar", "que necesito tramitar", "qué necesito tramitar",
        "no se que tramite", "no sé qué trámite", "no se que permiso", "no sé qué permiso",
    ],
    "seguimiento": [
        "seguimiento", "seguimiento ambiental", "cumplimiento", "cumplimiento ambiental", "informe",
        "informe ambiental", "obligaciones", "obligaciones ambientales", "plan de manejo", "pma",
        "auditoria ambiental", "auditoría ambiental", "monitoreo", "monitoreos", "informes ambientales",
        "reporte ambiental", "reportes ambientales", "ya tengo permiso", "ya tengo registro", "tengo permiso",
        "tengo licencia", "tengo registro", "mantener al dia", "mantener al día", "mantener actualizado",
        "actualizar", "actualizacion", "actualización", "acompañamiento mensual", "auditorias", "auditorías",
        "control mensual", "seguimiento mensual", "cumplir obligaciones", "presentar informe", "presentar informes",
        "renovar permiso", "renovacion", "renovación", "actualizar pma", "actualizar plan de manejo",
    ],
    "autoridad": [
        "ministerio", "minitrio", "maate", "ambiente", "ambnte", "gad", "municipio", "autoridad",
        "autoridad ambiental", "notificacion", "notificación", "notificasion", "inspeccion", "inspección",
        "control", "oficio", "requerimiento", "me notificaron", "me llego un oficio", "me llegó un oficio",
        "sancion", "sanción", "multa", "proceso administrativo", "comisaria", "comisaría", "gobierno municipal",
        "prefectura", "arcsa", "agrocalidad", "revisión de autoridad", "observacion de autoridad",
        "observación de autoridad", "me hicieron observaciones", "me observaron", "tengo plazo",
    ],
    "precio": [
        "precio", "presio", "cuanto", "cuánto", "cuanto vale", "cuánto vale", "cuanto cobra",
        "cuánto cobra", "costo", "valor", "cobran", "tarifa", "cotizacion", "cotización",
        "proforma", "barato", "sale", "cuanto sale", "cuánto sale", "mensualidad", "cuanto cuesta",
        "cuánto cuesta", "que cuesta", "qué cuesta", "cuanto me sale", "cuánto me sale", "valor mensual",
        "costo mensual", "cuanto cobran mensual", "cuánto cobran mensual", "precio mensual",
        "me puede cotizar", "me puede dar una proforma", "cuanto seria", "cuánto sería",
    ],
}

PERMISOS_SI = [
    "sí tengo", "si tengo", "ya tengo", "ya lo tengo", "ya lo hice", "ya está listo", "ya esta listo",
    "cuento con permiso", "cuento con el permiso", "cuento con el registro", "cuento con licencia",
    "ya tengo el registro", "tengo permiso", "tengo el permiso", "tengo la licencia", "tengo licencia",
    "ya tengo licencia", "ya tengo permiso", "ya tengo registro", "mis papeles están en regla",
    "mis papeles estan en regla", "ya tengo todo", "ya está aprobado", "ya esta aprobado",
    "ya está legalizado", "ya esta legalizado", "está vigente", "esta vigente", "está al día",
    "esta al dia", "todo está en orden", "todo esta en orden", "ya tengo todo en regla",
    "todo esta legal", "todo está legal", "tengo los documentos", "tengo los papeles", "eso ya esta",
    "eso ya está", "ya lo tramite", "ya lo tramité", "ya me aprobaron", "me lo aprobaron",
]

PERMISOS_NO = [
    "no tengo", "no tengo todavía", "no tengo todavia", "todavía no", "todavia no", "aún no",
    "aun no", "no contamos", "ninguno", "no tengo ninguno", "no cuento con", "aún no he sacado",
    "aun no he sacado", "todavía no lo tramito", "todavia no lo tramito", "no he tramitado",
    "no he hecho nada", "no tengo los papeles", "no tengo ese permiso", "no tengo el registro",
    "no tengo licencia", "no tengo permiso", "me falta sacar eso", "me falta eso", "me falta el permiso",
    "me falta licencia", "no lo he gestionado", "nunca he hecho ese trámite", "nunca he hecho ese tramite",
    "estoy por comenzar", "recién voy a empezar", "recien voy a empezar", "recién estoy averiguando",
    "recien estoy averiguando", "estoy averiguando", "no tengo nada", "no tengo nada de eso",
]

# ======================================================
# INTENCIONES GENERALES
# ======================================================

AFIRMACIONES = [
    "si", "sí", "claro", "correcto", "de acuerdo", "listo", "ok", "okay", "perfecto", "ya",
    "dale", "de una", "está bien", "esta bien", "ta bien", "confirmo", "confirmado", "hagamos",
    "coordine", "coordinemos", "me parece", "proceda", "procedamos", "hágale", "hagale",
    "ya pues", "bueno", "aja", "ajá", "sí deseo", "si deseo", "sí quiero", "si quiero",
    "me interesa", "estoy interesado", "me puede ayudar", "ayúdeme", "ayudeme", "quiero avanzar",
    "vamos", "sigamos", "continuemos", "me parece bien", "esta correcto", "está correcto", "sí me interesa",
    "si me interesa", "deme haciendo", "deme ayudando", "de ley", "seria bueno", "sería bueno",
]

NEGACIONES = [
    "no", "negativo", "ahora no", "por ahora no", "no deseo", "no necesito", "no gracias",
    "déjelo", "dejelo", "después veo", "despues veo", "luego veo", "por ahora nada",
    "no por ahora", "otro día", "otro dia", "más adelante", "mas adelante", "no tengo tiempo",
    "no me interesa", "no insista", "no molesten", "deje nomas", "deje no mas", "por el momento no",
    "ahorita no", "luego le aviso", "yo le aviso", "le aviso despues", "le aviso después", "no quiero",
    "no deseo informacion", "no deseo información", "no deseo continuar", "no me escriba", "borre mi numero",
]

DESPEDIDAS = [
    "gracias", "muchas gracias", "listo gracias", "ok gracias", "nos vemos", "hasta luego",
    "bendiciones", "buen día", "buen dia", "chao", "chau", "estamos", "vale gracias",
    "gracias ingeniero", "gracias ing", "muy amable", "perfecto gracias", "ya gracias", "listo muchas gracias",
]

PALABRAS_VISITA = [
    "visita", "viste", "vengan", "venir", "pueden venir", "que venga", "q venga", "reunion",
    "reunión", "reunirse", "ir a la finca", "ir al sitio", "ir al predio", "ir a la camaronera",
    "dése una vuelta", "dese una vuelta", "péguese una vuelta", "pegese una vuelta", "véngase", "vengase",
    "caiga", "que lo revise en sitio", "que revise en sitio", "que revise en campo", "lo puedo recibir",
    "lo recibo en la finca", "lo recibo en el sitio", "en la finca para que revise", "prefiero algo personal",
    "prefiero algo más personal", "prefiero algo mas personal", "presencial", "presencialmente",
    "diagnóstico en campo", "diagnostico en campo", "revisión en campo", "revision en campo",
    "diagnóstico completo", "diagnostico completo", "visita tecnica", "visita técnica", "evaluacion en campo",
    "evaluación en campo", "evaluacion presencial", "evaluación presencial", "venir a ver", "que venga a ver",
    "que venga a revisar", "que revise la finca", "que revise la camaronera", "recibirlo en finca",
]

PALABRAS_LLAMADA = [
    "llamada", "llamda", "llámeme", "llameme", "me llama", "puede llamar", "conversemos",
    "por teléfono", "por telefono", "telefono", "teléfono", "fono", "llamar", "llámame", "llamame",
    "yame", "yamar", "me llamen", "que me llamen", "quiero que me llamen", "quisiera que me llamen",
    "me pueden llamar", "pueden llamarme", "llámenme", "llamenme", "llamen", "pégueme una llamada",
    "pegueme una llamada", "mejor llamada", "solo llamada", "no mas llamada", "nomás llamada",
    "primero llamada", "llamada primero", "por llamada", "por celular", "por el celular", "mejor me llama",
    "que me llame el ingeniero", "que me llame darwin", "coordinar llamada", "hacer llamada",
]

PALABRAS_CAMBIO = [
    "cambiar", "cambio", "mejor a", "mejor el", "otra hora", "otro día", "otro dia", "reagendar",
    "reprogramar", "mover", "pasar para", "cambiemos", "mejor mañana", "mejor pasado", "cambiemos para",
    "cambiar la hora", "cambiar el dia", "cambiar el día", "pasemos", "pasar la cita", "reagendemos",
    "no puedo a esa hora", "puede ser mas tarde", "puede ser más tarde", "puede ser mas temprano",
    "puede ser más temprano",
]

PALABRAS_CANCELACION = [
    "cancelar", "cancele", "ya no", "anular", "sin efecto", "suspenda", "no voy a poder",
    "ya no puedo", "dejemos ahí", "dejemos ahi", "dejelo ahi", "déjelo ahí", "ya no hace falta",
    "ya resolvi", "ya resolví", "no se va a poder", "dejemos para despues", "dejemos para después",
]

PALABRAS_NUEVA_FINCA = [
    "otra finca", "otra camaronera", "otra actividad", "también tengo", "tambien tengo", "tengo otra",
    "otra propiedad", "segunda finca", "otra hacienda", "otro predio", "otra granja", "otra planta",
    "tengo varias fincas", "manejo varias fincas", "asociación", "asociacion", "varios socios",
    "varios productores", "tambien manejo", "también manejo", "tengo otro", "tengo otros predios",
    "hay otra finca", "son varias fincas", "soy de una asociacion", "soy de una asociación",
]

PALABRAS_DESCONFIANZA = [
    "estafa", "delincuente", "extorsión", "extorsion", "extorsionador", "bloqueo", "bloquear",
    "mensaje raro", "quién les dio mi número", "quien les dio mi numero", "de dónde sacaron mi número",
    "de donde sacaron mi numero", "no molesten", "quién es usted", "quien es usted", "no sé quién es",
    "no se quien es", "sospechoso", "fraude", "esto es real", "son reales", "dónde están ubicados",
    "donde estan ubicados", "qué empresa es", "que empresa es", "de donde son", "de dónde son",
    "quien le dio mi contacto", "quién le dio mi contacto", "por que me escribe", "por qué me escribe",
    "por que tienen mi numero", "por qué tienen mi número", "quien autorizo", "quién autorizó",
]

PALABRAS_INFORMACION = [
    "información", "informacion", "info", "quisiera saber", "quiero saber", "cómo funciona", "como funciona",
    "qué hacen", "que hacen", "qué ofrecen", "que ofrecen", "explique", "explíqueme", "expliqueme",
    "ayuda", "asesoría", "asesoria", "orientación", "orientacion", "requisitos", "más información",
    "mas informacion", "envíeme información", "envieme informacion", "cuénteme", "cuenteme", "a ver",
    "en qué consiste", "en que consiste", "de que se trata", "de qué se trata", "que es eso",
    "qué es eso", "para que sirve", "para qué sirve", "que incluye", "qué incluye", "que debo hacer",
    "qué debo hacer", "como me ayudan", "cómo me ayudan", "necesito saber", "deme detalles",
]

PALABRAS_INTERES_REVISION = [
    "quiero que lo revise", "quiero q lo revise", "revisar", "revise", "revisión", "revision",
    "diagnóstico", "diagnostico", "ayúdeme", "ayudeme", "me interesa", "necesito revisar",
    "qué necesito", "que necesito", "qué me falta", "que me falta", "evaluación", "evaluacion",
    "evaluación primaria", "evaluacion primaria", "revisión gratis", "revision gratis", "diagnóstico gratis",
    "diagnostico gratis", "evaluación gratuita", "evaluacion gratuita", "sin compromiso", "acompañamiento mensual",
    "que papeles necesito", "qué papeles necesito", "que documentos necesito", "qué documentos necesito",
    "que me revisen", "qué me revisen", "revisen mis papeles", "ver mis documentos", "ver la documentacion",
    "ver la documentación", "quiero orientacion", "quiero orientación",
]

# ======================================================
# RESPUESTAS A CAMPAÑA AUTOMÁTICA
# ======================================================

CAMPANA_INTERES_GENERAL = [
    "sí", "si", "claro", "ok", "listo", "me interesa", "quiero información", "quiero informacion",
    "más información", "mas informacion", "envíeme información", "envieme informacion", "mande info",
    "páseme información", "paseme informacion", "cuénteme", "cuenteme", "a ver", "explíqueme",
    "expliqueme", "me puede explicar", "necesito información", "necesito informacion", "deseo saber",
    "quiero saber", "me interesa saber", "cómo es", "como es", "cómo sería", "como seria",
    "de que se trata", "de qué se trata", "que ofrecen", "qué ofrecen", "que hacen", "qué hacen",
    "me podria indicar", "me podría indicar", "deme informacion", "deme información", "envie nomas",
    "envíe nomás", "mande nomas", "mande nomás",
]

CAMPANA_EVALUACION_GRATIS = [
    "evaluación gratis", "evaluacion gratis", "evaluación primaria", "evaluacion primaria",
    "evaluación gratuita", "evaluacion gratuita", "diagnóstico gratis", "diagnostico gratis",
    "diagnóstico gratuito", "diagnostico gratuito", "revisión gratis", "revision gratis",
    "quiero la evaluación", "quiero la evaluacion", "quiero la revisión", "quiero la revision",
    "eso gratis cómo es", "eso gratis como es", "sin compromiso", "evaluacion sin compromiso",
    "evaluación sin compromiso", "revision sin compromiso", "revisión sin compromiso", "diagnostico inicial",
    "diagnóstico inicial", "revision primaria", "revisión primaria",
]

CAMPANA_QUIENES_SON = [
    "quiénes son", "quienes son", "quién es usted", "quien es usted", "qué empresa es", "que empresa es",
    "esto es real", "son reales", "dónde están", "donde estan", "dónde están ubicados", "donde estan ubicados",
    "de dónde son", "de donde son", "dalgo", "dalgoro", "quien me escribe", "quién me escribe",
    "que empresa representa", "qué empresa representa", "donde queda", "dónde queda",
]

CAMPANA_YA_TIENE_PERMISO = [
    "ya tengo permiso", "ya tengo licencia", "ya tengo registro", "tengo permiso", "tengo licencia",
    "tengo registro", "ya estoy al día", "ya estoy al dia", "todo está en regla", "todo esta en regla",
    "ya tengo todo", "ya tengo papeles", "tengo papeles", "ya estoy legal", "ya esta legal",
    "ya está legal", "ya estoy regularizado", "ya estoy regularizada",
]

CAMPANA_YA_TIENE_CONSULTOR = [
    "ya tengo consultor", "tengo consultor", "ya tengo quien me ayuda", "ya me llevan eso",
    "eso me lo ve otra persona", "ya tengo técnico", "ya tengo tecnico", "mi ingeniero ve eso",
    "tengo un ingeniero", "ya tengo asesor", "ya tengo asesoria", "ya tengo asesoría", "otro consultor me ayuda",
]

CAMPANA_SANCIONES_AUDITORIA = [
    "sanción", "sancion", "multa", "auditoría", "auditoria", "me van a auditar", "tengo auditoría",
    "tengo auditoria", "me observaron", "observación", "observacion", "me hicieron observaciones",
    "me notificaron", "me llego oficio", "me llegó oficio", "tengo inspeccion", "tengo inspección",
    "me pidieron corregir", "tengo plazo", "tengo requerimiento",
]

# ======================================================
# TIEMPO Y UBICACIÓN
# ======================================================

REEMPLAZOS_TIEMPO = {
    "pasado mañana después del medio día": "pasado mañana a las 13:00",
    "pasado mañana al medio día": "pasado mañana a las 12:00",
    "mañana después del medio día": "mañana a las 13:00",
    "mañana al medio día": "mañana a las 12:00",
    "hoy después del medio día": "hoy a las 13:00",
    "hoy al medio día": "hoy a las 12:00",
    "al amanecer": "a las 06:00",
    "al anochecer": "a las 18:00",
    "temprano en la mañana": "a las 08:00",
    "esta noche": "hoy a las 20:00",
    "esta mañana": "hoy a las 08:00",
    "esta tarde": "hoy a las 15:00",
    "en la madrugada": "hoy a las 05:00",
    "en la mañana": "a las 09:00",
    "por la mañana": "a las 09:00",
    "en la tarde": "a las 15:00",
    "por la tarde": "a las 15:00",
    "en la noche": "a las 20:00",
    "por la noche": "a las 20:00",
    "después del almuerzo": "a las 14:00",
    "despues del almuerzo": "a las 14:00",
    "luego del almuerzo": "a las 14:00",
    "a la hora del almuerzo": "a las 12:30",
    "a primera hora": "a las 07:00",
    "media mañana": "a las 10:30",
    "a media mañana": "a las 10:30",
    "media tarde": "a las 16:00",
    "a media tarde": "a las 16:00",
    "antes del medio día": "a las 11:00",
    "antes del medio dia": "a las 11:00",
    "tipo ": "a las ",
    "como a las ": "a las ",
    "como a ": "a las ",
    "a eso de las ": "a las ",
    "a eso de ": "a las ",
    "más o menos a las ": "a las ",
    "mas o menos a las ": "a las ",
    "más o menos a ": "a las ",
    "mas o menos a ": "a las ",
    "mñn": "mañana",
    "mnn": "mañana",
}

FRASES_UBICACION_GENERICA = {
    "en mi finca": "su finca",
    "en la finca": "la finca",
    "en la hacienda": "la hacienda",
    "en el sitio": "el sitio de trabajo",
    "en mi oficina": "su oficina",
    "en la oficina": "la oficina",
    "en el galpón": "el galpón",
    "en el galpon": "el galpón",
    "en la camaronera": "la camaronera",
    "en las piscinas": "las piscinas",
    "en el plantel": "el plantel",
    "en las instalaciones": "las instalaciones",
    "en mi planta": "su planta",
    "en la planta": "la planta",
    "aquí mismo": "el sitio indicado",
    "aqui mismo": "el sitio indicado",
    "en mi propiedad": "su propiedad",
    "en campo": "campo",
    "en sitio": "sitio",
    "en el predio": "el predio",
    "en el terreno": "el terreno",
    "donde están los cultivos": "donde están los cultivos",
    "donde estan los cultivos": "donde están los cultivos",
    "donde están las piscinas": "donde están las piscinas",
    "donde estan las piscinas": "donde están las piscinas",
    "en el criadero": "el criadero",
    "en el proyecto": "el proyecto",
}

NO_UBICACIONES = {
    "facebook", "face", "fb", "instagram", "redes", "publicidad", "anuncio", "banco",
    "credito", "crédito", "banecuador", "ministerio", "maate", "licencia", "permiso", "registro",
    "mañana", "manana", "tarde", "noche", "mañana por la mañana", "por la mañana",
    "certificacion", "certificación", "auditoria", "auditoría", "precio", "costo", "valor",
}

BLOQUEADORES_NOMBRE_EXTRA = [
    "hola", "buenas", "buen día", "buen dia", "buenas tardes", "buenas noches", "facebook",
    "anuncio", "publicidad", "información", "informacion", "info", "finca", "hacienda",
    "camaronera", "granja", "hotel", "planta", "industria", "banco", "credito", "crédito",
    "certificacion", "certificación", "permiso", "licencia", "registro", "ministerio", "maate",
    "autoridad", "seguimiento", "visita", "llamada", "mañana", "mñn", "mnn", "tarde", "noche",
    "lunes", "martes", "miercoles", "miércoles", "jueves", "viernes", "sabado", "sábado", "domingo",
    "sector", "via", "vía", "recinto", "sitio", "parroquia", "canton", "cantón", "por", "cerca",
    "necesito", "quiero", "tengo", "revisen", "revisar", "precio", "cuanto", "cuánto", "costo",
    "valor", "me recomendaron", "referido", "como funciona", "cómo funciona", "ayuda", "asesoria",
    "asesoría", "orientacion", "orientación", "gracias", "muchas", "con", "gusto", "listo", "ok",
    "dalgoro", "ambiental", "regularizacion", "regularización", "licenciamiento", "auditoria", "auditoría",
    "donde", "sacaron", "numero", "número", "quien", "quién", "usted", "empresa", "real",
    "extorsion", "extorsión", "estafa", "fraude", "mensaje", "raro", "bloqueo", "bloquear",
]

# ======================================================
# REFUERZOS V10 - Auditoría de calidad
# ======================================================
# Se dejan al final para que actúen como ampliación segura del léxico
# sin reescribir la estructura anterior.

ACTIVIDADES_LEXICO.setdefault("otra", [])
ACTIVIDADES_LEXICO["otra"].extend([
    "actividad productiva", "otra actividad", "actividad comercial", "actividad agricola",
    "actividad agrícola", "negocio rural", "negocio productivo", "empresa pequena",
    "empresa pequeña", "empresa familiar", "emprendimiento", "proyecto productivo",
    "proyecto agricola", "proyecto agrícola", "unidad productiva", "predio productivo",
    "actividad en el campo", "trabajo en el campo", "actividad rural", "productor",
    "productores", "asociacion de productores", "asociación de productores",
    "asociacion", "asociación", "pequena empresa", "pequeña empresa",
    "no se que categoria", "no sé qué categoría", "no se que aplica", "no sé qué aplica",
    "no se donde entra", "no sé dónde entra", "negocio pequeno", "negocio pequeño",
    "actividad pequena", "actividad pequeña", "empresa", "negocio", "proyecto",
])

MOTIVOS_LEXICO.setdefault("credito_bancario", [])
MOTIVOS_LEXICO["credito_bancario"].extend([
    "requisito bancario", "requisitos bancarios", "requisito financiero",
    "requisito para financiamiento", "requisito de la cooperativa",
    "me piden papeles", "me piden documentos", "me solicitaron papeles",
    "me solicitaron documentos", "papeles para credito", "papeles para crédito",
    "documentos para credito", "documentos para crédito", "para crédito del banco",
    "para credito del banco", "es requisito bancario", "es para credito", "es para crédito",
])

MOTIVOS_LEXICO.setdefault("regularizacion", [])
MOTIVOS_LEXICO["regularizacion"].extend([
    "que tramite me corresponde", "qué trámite me corresponde",
    "que permiso me corresponde", "qué permiso me corresponde",
    "que debo tramitar", "qué debo tramitar", "que debo sacar", "qué debo sacar",
    "que necesito tramitar", "qué necesito tramitar", "no se que tramite", "no sé qué trámite",
    "no se que permiso", "no sé qué permiso", "quiero saber que tramite", "quiero saber qué trámite",
])

MOTIVOS_LEXICO.setdefault("autoridad", [])
MOTIVOS_LEXICO["autoridad"].extend([
    "el municipio me pidió documentación", "el municipio me pidio documentacion",
    "municipio me pidió documentación", "municipio me pidio documentacion",
    "me llegó oficio", "me llego oficio", "me llegó un oficio", "me llego un oficio",
])
