import re
import unicodedata
from difflib import SequenceMatcher


# ======================================================
# NORMALIZACIÓN BÁSICA
# ======================================================

def normalizar(texto: str) -> str:
    texto = texto or ""
    texto = texto.lower().strip()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    texto = texto.replace("ñ", "n")
    texto = re.sub(r"[.,;:¡!¿?()\[\]{}]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _tokens(texto: str):
    return re.findall(r"[a-z0-9]+", normalizar(texto))


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def _token_parecido(token: str, patron: str) -> bool:
    token = normalizar(token)
    patron = normalizar(patron)

    if token == patron:
        return True

    if len(token) < 5 or len(patron) < 5:
        return False

    # Evita falsos positivos críticos como "mañana/manana" ≈ "banana".
    if token[0] != patron[0]:
        return False

    return _similar(token, patron) >= 0.82


def contiene(texto: str, palabras) -> bool:
    """
    Búsqueda robusta para frases, errores moderados y modismos.
    Evita usar IA externa para mantener estabilidad del bot.
    """
    t = normalizar(texto)
    toks = _tokens(t)

    for palabra in palabras:
        p = normalizar(palabra)
        if not p:
            continue

        p_toks = _tokens(p)

        # Coincidencia exacta controlada:
        # - Para palabras sueltas, exige token completo.
        # - Para frases, exige frase completa entre espacios.
        # Esto evita falsos positivos como "planta" dentro de "plantacion"
        # o "mina" dentro de otra palabra.
        if len(p_toks) == 1:
            if p_toks[0] in toks:
                return True
        else:
            if f" {p} " in f" {t} ":
                return True

            largas = [x for x in p_toks if len(x) >= 4]
            cortas = [x for x in p_toks if len(x) < 4]

            cortas_ok = all(x in toks for x in cortas)
            largas_ok = all(
                any(_token_parecido(tok, x) for tok in toks)
                for x in largas
            ) if largas else True

            if cortas_ok and largas_ok:
                return True

        # Fallback de similitud para palabras sueltas.
        if len(p_toks) == 1:
            if any(_token_parecido(tok, p_toks[0]) for tok in toks):
                return True

    return False


# ======================================================
# ACTIVIDADES DE SERVICIO DALGORO
# Basado en las actividades contempladas en respuestas_por_actividad.py:
# bananera, camaronera, minería, cacaotera, cultivo de ciclo corto,
# granja porcina, granja avícola, hotel, industria y otros.
# ======================================================

ACTIVIDADES = {
    "bananera": [
        "banano", "bananera", "bananero", "bananra", "finca bananera", "hacienda bananera",
        "plantacion de banano", "plantación de banano", "guineo", "guineal", "banana",
        "platanera", "platanero", "finca de banano"
    ],
    "camaronera": [
        "camaron", "camarón", "camaronera", "camaronero", "camarnra", "camaornera",
        "piscina camaronera", "piscinas", "piscinas de camaron", "piscinas de camarón",
        "larva", "cultivo de camaron", "cultivo de camarón", "criadero de camaron", "camaronicultura"
    ],
    "mineria": [
        "mineria", "minería", "minera", "minria", "mina", "material petreo", "material pétreo",
        "extraccion minera", "extracción minera", "aridos", "áridos", "cantera", "concesion minera",
        "grava", "ripio", "piedra"
    ],
    "cacaotera": [
        "cacao", "cacaotera", "cacaotero", "finca de cacao", "plantacion de cacao",
        "plantación de cacao", "kakao", "cacaotal", "trabajo con cacao"
    ],
    "cultivo_ciclo_corto": [
        "ciclo corto", "cultivo de ciclo corto", "cultivo corto", "maiz", "maíz", "arroz",
        "hortaliza", "hortalizas", "cultivo", "cultivos", "sembrio", "sembrío", "cultvo",
        "yuca", "mani", "maní", "frijol", "frejol", "legumbres", "tomate", "cebolla", "verde"
    ],
    "granja_porcina": [
        "porcina", "porcino", "cerdo", "cerdos", "chancho", "chanchos", "chanchera", "chankera",
        "granja porcina", "granja de chanchos", "marranos", "porqueriza", "lechon", "lechón",
        "cria de cerdos", "cría de cerdos"
    ],
    "granja_avicola": [
        "avicola", "avícola", "avikola", "aves", "pollo", "pollos", "gallina", "gallinas",
        "granja avicola", "granja avícola", "galpon", "galpón", "galpon de pollos",
        "gallinero", "pollera", "ponedoras", "granja de aves"
    ],
    "hotel": [
        "hotel", "hosteria", "hostería", "hostal", "turistico", "turístico", "turismo",
        "hospedaje", "alojamiento", "cabanas", "cabañas", "quinta turistica", "resort"
    ],
    "industria": [
        "industria", "industrial", "planta", "procesadora", "empacadora", "empakadora",
        "taller", "fabrica", "fábrica", "agroindustria", "centro de acopio", "piladora",
        "procesamiento", "empresa industrial"
    ],
}


MOTIVOS = {
    "credito_bancario": [
        "banco", "bco", "bnco", "credito", "crédito", "credto", "crdito", "prestamo", "préstamo",
        "prestmo", "financiamiento", "banecuador", "banca", "me piden para credito",
        "credito agricola", "credito productivo", "para credito", "para el banco", "bancario"
    ],
    "certificacion": [
        "certificacion", "certificación", "sertificacion", "certifiacion", "certi", "certificadora",
        "globalgap", "global ga", "global gap", "rainforest", "auditoria", "auditoría",
        "exportacion", "exportación", "exportar", "certificado", "certificar"
    ],
    "regularizacion": [
        "regularizar", "regularizacion", "regularización", "regulaizar", "licencia", "licensia",
        "registro ambiental", "permiso ambiental", "permizo ambiental", "licenciamiento", "sui", "suia",
        "suy", "sistema ambiental", "tramite ambiental", "trámite ambiental", "sacar permiso",
        "sacar el permiso", "obtener permiso", "no tengo permiso", "no cuento con permiso",
        "no tengo licencia", "aun no tengo", "aún no tengo", "todavia no tengo", "todavía no tengo"
    ],
    "seguimiento": [
        "seguimiento", "cumplimiento", "informe", "informe ambiental", "obligaciones", "plan de manejo",
        "pma", "auditoria ambiental", "auditoría ambiental", "monitoreo", "informes ambientales",
        "ya tengo permiso", "ya tengo registro", "tengo permiso", "tengo licencia", "tengo registro",
        "mantener al dia", "mantener al día", "actualizar", "actualizacion", "actualización"
    ],
    "autoridad": [
        "ministerio", "minitrio", "maate", "ambiente", "ambnte", "gad", "municipio", "autoridad",
        "notificacion", "notificación", "notificasion", "inspeccion", "inspección", "control",
        "oficio", "requerimiento", "me notificaron"
    ],
    "precio": [
        "precio", "presio", "cuanto", "cuánto", "cuanto vale", "cuanto cobra", "costo", "valor",
        "cobran", "tarifa", "cotizacion", "cotización", "proforma", "barato", "sale"
    ],
}


AFIRMACIONES = [
    "si", "sí", "claro", "correcto", "de acuerdo", "listo", "ok", "okay", "perfecto", "ya",
    "dale", "de una", "esta bien", "está bien", "ta bien", "confirmo", "confirmado", "hagamos",
    "coordine", "coordinemos", "me parece", "proceda", "procedamos", "hagale", "hágale",
    "ya pues", "bueno", "aja", "ajá", "si deseo", "sí deseo", "si quiero", "sí quiero"
]

NEGACIONES = [
    "no", "negativo", "ahora no", "por ahora no", "no deseo", "no necesito", "no gracias",
    "dejelo", "déjelo", "despues veo", "después veo", "luego veo", "por ahora nada",
    "no por ahora", "otro dia", "otro día", "mas adelante", "más adelante", "no tengo tiempo"
]

DESPEDIDAS = [
    "gracias", "muchas gracias", "listo gracias", "ok gracias", "nos vemos", "hasta luego",
    "bendiciones", "buen dia", "buen día", "chao", "chau", "estamos", "vale gracias"
]

PALABRAS_VISITA = [
    "visita", "viste", "vengan", "venir", "pueden venir", "que venga", "q venga", "reunion",
    "reunión", "reunirse", "ir a la finca", "ir al sitio", "dese una vuelta", "dése una vuelta",
    "pegese una vuelta", "péguese una vuelta", "vengase", "véngase", "caiga",
    "que lo revise en sitio", "lo puedo recibir", "lo recibo en la finca", "en la finca para que revise",
    "prefiero algo personal", "prefiero algo mas personal", "prefiero algo más personal", "presencial",
    "diagnostico en campo", "diagnóstico en campo", "revision en campo", "revisión en campo"
]

PALABRAS_LLAMADA = [
    "llamada", "llamda", "llameme", "llámeme", "me llama", "puede llamar", "conversemos",
    "por telefono", "por teléfono", "telefono", "teléfono", "fono", "llamar", "llamame", "llámame",
    "yame", "yamar", "me llamen", "que me llamen", "quiero que me llamen", "quisiera que me llamen", "me pueden llamar", "pueden llamarme", "llamenme", "llámenme", "llamen", "pegueme una llamada", "pégueme una llamada"
]

PALABRAS_CAMBIO = [
    "cambiar", "cambio", "mejor a", "mejor el", "otra hora", "otro dia", "otro día", "reagendar",
    "reprogramar", "mover", "pasar para", "cambiemos", "mejor mañana", "mejor pasado"
]

PALABRAS_CANCELACION = [
    "cancelar", "cancele", "ya no", "anular", "sin efecto", "suspenda", "no voy a poder",
    "ya no puedo", "dejemos ahi", "dejemos ahí"
]

PALABRAS_NUEVA_FINCA = [
    "otra finca", "otra camaronera", "otra actividad", "tambien tengo", "también tengo", "tengo otra",
    "otra propiedad", "segunda finca", "otra hacienda", "otro predio", "otra granja", "otra planta",
    "tengo varias fincas", "manejo varias fincas", "asociacion", "asociación"
]

PALABRAS_DESCONFIANZA = [
    "estafa", "delincuente", "extorsion", "extorsión", "extorsionador", "bloqueo", "bloquear",
    "mensaje raro", "quien les dio mi numero", "quién les dio mi número", "no molesten",
    "quien es usted", "quién es usted", "no se quien es", "no sé quién es", "sospechoso", "fraude"
]

PALABRAS_INFORMACION = [
    "informacion", "información", "info", "quisiera saber", "quiero saber", "como funciona", "cómo funciona",
    "que hacen", "qué hacen", "que ofrecen", "qué ofrecen", "explique", "explicame", "explíqueme",
    "ayuda", "asesoria", "asesoría", "orientacion", "orientación", "requisitos"
]

PALABRAS_INTERES_REVISION = [
    "quiero que lo revise", "quiero q lo revise", "revisar", "revise", "revision", "revisión",
    "diagnostico", "diagnóstico", "ayudeme", "ayúdeme", "me interesa", "necesito revisar",
    "que necesito", "qué necesito", "que me falta", "qué me falta"
]

NO_UBICACIONES = {"facebook", "face", "fb", "instagram", "redes", "publicidad", "anuncio", "banco", "credito", "crédito", "banecuador"}

FRASES_UBICACION_GENERICA = {
    "en mi finca": "su finca",
    "en la finca": "la finca",
    "en el sitio": "el sitio de trabajo",
    "en mi oficina": "su oficina",
    "en la oficina": "la oficina",
    "en el galpon": "el galpón",
    "en la camaronera": "la camaronera",
    "en el plantel": "el plantel",
    "en las instalaciones": "las instalaciones",
    "en mi planta": "su planta",
    "aqui mismo": "el sitio indicado",
    "aquí mismo": "el sitio indicado",
    "en mi propiedad": "su propiedad",
    "en campo": "campo",
    "en sitio": "sitio",
    "en el predio": "el predio",
    "en el terreno": "el terreno",
    "donde estan los cultivos": "donde están los cultivos",
    "donde están los cultivos": "donde están los cultivos",
    "donde estan las piscinas": "donde están las piscinas",
    "donde están las piscinas": "donde están las piscinas",
    "en el criadero": "el criadero",
    "en el proyecto": "el proyecto",
}



# ======================================================
# LÉXICO BASE CENTRALIZADO V8
# ======================================================
# Se sobreescriben las listas internas con el léxico centralizado.
# Esto permite agregar nuevas frases en lexico_base.py sin tocar la lógica.
from lexico_base import (
    ACTIVIDADES_LEXICO,
    MOTIVOS_LEXICO,
    PERMISOS_SI,
    PERMISOS_NO,
    AFIRMACIONES as LX_AFIRMACIONES,
    NEGACIONES as LX_NEGACIONES,
    DESPEDIDAS as LX_DESPEDIDAS,
    PALABRAS_VISITA as LX_PALABRAS_VISITA,
    PALABRAS_LLAMADA as LX_PALABRAS_LLAMADA,
    PALABRAS_CAMBIO as LX_PALABRAS_CAMBIO,
    PALABRAS_CANCELACION as LX_PALABRAS_CANCELACION,
    PALABRAS_NUEVA_FINCA as LX_PALABRAS_NUEVA_FINCA,
    PALABRAS_DESCONFIANZA as LX_PALABRAS_DESCONFIANZA,
    PALABRAS_INFORMACION as LX_PALABRAS_INFORMACION,
    PALABRAS_INTERES_REVISION as LX_PALABRAS_INTERES_REVISION,
    CAMPANA_INTERES_GENERAL,
    CAMPANA_EVALUACION_GRATIS,
    CAMPANA_QUIENES_SON,
    CAMPANA_YA_TIENE_PERMISO,
    CAMPANA_YA_TIENE_CONSULTOR,
    CAMPANA_SANCIONES_AUDITORIA,
    REEMPLAZOS_TIEMPO,
    FRASES_UBICACION_GENERICA as LX_FRASES_UBICACION_GENERICA,
    NO_UBICACIONES as LX_NO_UBICACIONES,
    BLOQUEADORES_NOMBRE_EXTRA,
)

ACTIVIDADES = ACTIVIDADES_LEXICO
MOTIVOS = MOTIVOS_LEXICO
AFIRMACIONES = LX_AFIRMACIONES
NEGACIONES = LX_NEGACIONES
DESPEDIDAS = LX_DESPEDIDAS
PALABRAS_VISITA = LX_PALABRAS_VISITA
PALABRAS_LLAMADA = LX_PALABRAS_LLAMADA
PALABRAS_CAMBIO = LX_PALABRAS_CAMBIO
PALABRAS_CANCELACION = LX_PALABRAS_CANCELACION
PALABRAS_NUEVA_FINCA = LX_PALABRAS_NUEVA_FINCA
PALABRAS_DESCONFIANZA = LX_PALABRAS_DESCONFIANZA
PALABRAS_INFORMACION = LX_PALABRAS_INFORMACION
PALABRAS_INTERES_REVISION = LX_PALABRAS_INTERES_REVISION
NO_UBICACIONES = LX_NO_UBICACIONES
FRASES_UBICACION_GENERICA = LX_FRASES_UBICACION_GENERICA

# ======================================================
# DETECTORES PRINCIPALES
# ======================================================

def _mensaje_declara_actividad(mensaje: str) -> bool:
    """
    Verifica si el cliente realmente está declarando su actividad.
    Evita falsos positivos como: "me pasó su número un proveedor de balanceado",
    donde balanceado es contexto del referido, no actividad del cliente.
    """
    t = normalizar(mensaje)

    marcadores = [
        "tengo", "tenemos", "manejo", "manejamos", "soy", "somos",
        "mi actividad", "nuestra actividad", "me dedico", "nos dedicamos",
        "trabajo con", "trabajamos con", "produzco", "producimos",
        "cuento con", "mi finca", "mi camaronera", "mi granja",
        "la actividad es", "actividad es"
    ]

    if any(m in t for m in marcadores):
        return True

    # También permitimos respuestas cortas donde solo escribe la actividad.
    toks = _tokens(t)
    if 1 <= len(toks) <= 4:
        return True

    return False


def _contexto_referido_sin_actividad(mensaje: str) -> bool:
    t = normalizar(mensaje)
    contexto_referido = contiene(t, [
        "me paso su numero", "me pasó su número", "me pasaron su numero", "me pasaron su número",
        "me dio su numero", "me dio su número", "me compartieron su contacto",
        "un proveedor", "proveedor de balanceado", "proveedor de fertilizantes",
        "me dijeron que ustedes", "me dijo que ustedes", "publicidad", "instagram", "facebook"
    ])
    return contexto_referido and not _mensaje_declara_actividad(t)


def _es_incertidumbre_sobre_permiso(mensaje: str) -> bool:
    t = normalizar(mensaje)
    return contiene(t, [
        "no se si", "no sé si", "no estoy seguro", "no estoy segura",
        "no se bien si", "no sé bien si", "quisiera saber si",
        "solo quiero saber", "solo estoy averiguando", "me dio curiosidad"
    ]) and contiene(t, [
        "necesito", "aplica", "corresponde", "permiso", "licencia",
        "tengo", "debo", "tramite", "trámite", "papeles", "todo completo"
    ])


def detectar_actividad(mensaje: str):
    # No extraer actividad desde frases de referido/publicidad si el cliente aún no dijo qué maneja.
    if _contexto_referido_sin_actividad(mensaje):
        return None

    for actividad, palabras in ACTIVIDADES.items():
        if contiene(mensaje, palabras):
            return actividad
    return None


def detectar_motivo(mensaje: str):
    t = normalizar(mensaje)

    # Si el cliente está dudando, no asumir que ya tiene permiso ni que está al día.
    if _es_incertidumbre_sobre_permiso(t):
        if contiene(t, ["ministerio", "maate", "autoridad", "inspeccion", "inspección", "revisar", "revision", "revisión"]):
            return "autoridad"
        return None

    # Primero prioriza permisos explícitos para evitar que "permiso" quede como genérico.
    if contiene(t, ["no tengo permiso", "no tengo licencia", "no tengo registro", "aun no tengo", "aún no tengo", "me falta sacar", "recién voy a tramitar"]):
        return "regularizacion"
    if contiene(t, ["ya tengo permiso", "ya tengo licencia", "ya tengo registro", "tengo permiso", "tengo licencia", "tengo registro", "ya esta aprobado", "ya está aprobado"]):
        return "seguimiento"

    for motivo, palabras in MOTIVOS.items():
        if contiene(t, palabras):
            return motivo
    return None


def detectar_origen(mensaje: str, origen_actual=None):
    if origen_actual and origen_actual not in ["", "directo"]:
        return origen_actual

    if contiene(mensaje, ["facebook", "face", "fb", "anuncio", "publicacion", "publicación", "publicidad", "redes", "instagram"]):
        return "facebook"

    if contiene(mensaje, [
        "me recomendaron", "recomendado", "referido", "me dio su numero", "me dio su número",
        "me paso su contacto", "me pasó su contacto", "me hablo de usted", "me habló de usted",
        "me dijeron que le escriba", "de parte de", "el proveedor me dio", "me pasaron su numero",
        "me pasaron su número"
    ]):
        return "referido"

    return origen_actual or "directo"


def detectar_tipo_atencion(mensaje: str):
    if contiene(mensaje, PALABRAS_LLAMADA):
        return "llamada"
    if contiene(mensaje, PALABRAS_VISITA):
        return "visita"
    return None


def es_afirmacion(mensaje: str) -> bool:
    t = normalizar(mensaje)
    afirmaciones_norm = [normalizar(x) for x in AFIRMACIONES]
    return t in afirmaciones_norm or contiene(t, ["si deseo", "sí deseo", "si quiero", "sí quiero", "me interesa", "procedamos", "hagale", "hágale", "ya pues", "coordine nomas", "coordine no mas"])


def es_negacion(mensaje: str) -> bool:
    t = normalizar(mensaje)
    negaciones_norm = [normalizar(x) for x in NEGACIONES]
    return t in negaciones_norm or contiene(t, ["no me interesa", "no insista", "no quiero", "no tengo tiempo", "no deseo continuar"])


def detectar_intencion(mensaje: str, etapa_actual=None):
    """
    Clasifica intención del mensaje.

    V8 agrega respuestas a campañas automáticas sin romper el flujo anterior.
    Retornos nuevos:
    - campana_interes_general
    - campana_evaluacion
    - campana_quienes_son
    - campana_ya_tiene_permiso
    - campana_ya_tiene_consultor
    - campana_sanciones_auditoria
    """
    t = normalizar(mensaje)
    etapa_actual = etapa_actual or "inicio"

    # Pregunta directa por servicios/documento: aquí sí corresponde explicar y, si aplica, enviar PDF.
    if contiene(t, [
        "que servicios hacen", "qué servicios hacen", "que servicios ofrecen", "qué servicios ofrecen",
        "cuales son sus servicios", "cuáles son sus servicios", "que ofrecen exactamente",
        "qué ofrecen exactamente", "que hacen exactamente", "qué hacen exactamente",
        "documento de servicios", "pdf", "brochure", "catalogo", "catálogo"
    ]):
        return "pregunta_servicios"

    # Si el cliente corrige la actividad de forma explícita, no lo tratamos como molestia.
    if contiene(t, ["no me entiendes", "no entiende", "no una industria", "no es industria", "le dije camaronera", "te dije camaronera"]):
        if detectar_actividad(t):
            return "correccion_actividad"

    # Duda razonable de confianza/identidad.
    if contiene(t, ["confiable", "es confiable", "esto es confiable", "quiero saber si es confiable", "confianza"]):
        return "campana_quienes_son"

    # Molestia explícita: no convertir en agendamiento ni pedir datos.
    if contiene(t, [
        "no me vuelvas a escribir", "no vuelvan a escribir", "ya no quiero nada",
        "me canse de explicarte", "me cansé de explicarte", "no entiendes",
        "que bruto", "qué bruto", "bruto", "inutil", "inútil", "pesimo", "pésimo",
        "no sirves", "no me interesa nada", "mejor deje ahi", "mejor deje ahí"
    ]):
        return "desconfianza_o_molestia"

    if contiene(t, PALABRAS_DESCONFIANZA):
        # Algunas preguntas de identidad son dudas razonables, no molestia.
        if contiene(t, CAMPANA_QUIENES_SON) and not contiene(t, ["estafa", "delincuente", "extorsion", "extorsión", "no molesten", "fraude"]):
            return "campana_quienes_son"
        return "desconfianza_o_molestia"

    # Evita confundir "no tengo permiso" con rechazo comercial.
    if es_negacion(t) and not contiene(t, ["no tengo permiso", "no tengo licencia", "no tengo registro", "no tengo papeles"]):
        return "no_interesado"

    if etapa_actual in ["cita_agendada", "cita_actualizada", "cita_cancelada"] and contiene(t, DESPEDIDAS):
        return "despedida"

    if contiene(t, PALABRAS_CANCELACION):
        return "cancelacion"

    if contiene(t, PALABRAS_CAMBIO):
        return "cambio_cita"

    if contiene(t, PALABRAS_NUEVA_FINCA):
        return "nueva_finca"

    tipo_atencion = detectar_tipo_atencion(t)
    if tipo_atencion == "llamada":
        return "solicita_llamada"
    if tipo_atencion == "visita":
        return "solicita_visita"

    if detectar_motivo(t) == "precio":
        return "pregunta_precio"

    # Respuestas frecuentes al mensaje automático de campaña.
    # Se priorizan antes de información genérica para que "sí", "me interesa" o
    # "más información" no queden como consulta ambigua.
    if contiene(t, CAMPANA_YA_TIENE_CONSULTOR):
        return "campana_ya_tiene_consultor"

    if (contiene(t, CAMPANA_YA_TIENE_PERMISO) or contiene(t, PERMISOS_SI)) and not _es_incertidumbre_sobre_permiso(t):
        return "campana_ya_tiene_permiso"

    if contiene(t, CAMPANA_EVALUACION_GRATIS):
        return "campana_evaluacion"

    if contiene(t, CAMPANA_SANCIONES_AUDITORIA):
        return "campana_sanciones_auditoria"

    if contiene(t, CAMPANA_QUIENES_SON):
        return "campana_quienes_son"

    # Si el cliente responde a una campaña con "sí", "info", "me interesa", etc.
    # y aún no existe una orientación previa, se toma como interés general.
    if etapa_actual in ["inicio", "esperando_actividad", "campana_esperando_actividad", "cerrado_no_interesado", "cerrado_molestia"]:
        if contiene(t, CAMPANA_INTERES_GENERAL) or es_afirmacion(t):
            return "campana_interes_general"

    if contiene(t, PALABRAS_INFORMACION):
        return "pide_informacion"

    if etapa_actual in ["orientacion_previa", "propuesta_atencion", "precio_sin_cierre", "esperando_preferencia_atencion"] and contiene(t, PALABRAS_INTERES_REVISION):
        return "afirmacion"

    if es_afirmacion(t):
        return "afirmacion"

    return "consulta"

# ======================================================
# EXTRACCIÓN DE DATOS
# ======================================================

BLOQUEADORES_NOMBRE = set(_tokens("""
hola buenas buen dia buenas tardes buenas noches facebook anuncio publicidad informacion info finca hacienda
camaronera granja hotel planta industria banco credito certificacion permiso licencia registro ministerio maate
autoridad seguimiento visita llamada manana mñn mnn tarde noche lunes martes miercoles jueves viernes sabado domingo
sector via recinto sitio parroquia canton por cerca necesito quiero tengo revisen revisar precio cuanto costo valor
me recomendaron referido como funciona funciona ayuda asesoria orientacion gracias muchas con gusto listo ok
"""))
# También se integran los bloqueadores centralizados del léxico base.
BLOQUEADORES_NOMBRE.update(_tokens(" ".join(BLOQUEADORES_NOMBRE_EXTRA)))


def _parece_nombre_suelto(texto: str) -> bool:
    t = normalizar(texto)
    toks = _tokens(t)

    if not toks:
        return False
    if len(toks) < 2 or len(toks) > 5:
        return False
    if any(tok.isdigit() for tok in toks):
        return False
    if any(tok in BLOQUEADORES_NOMBRE for tok in toks):
        return False
    if detectar_actividad(t) or detectar_motivo(t) or detectar_tipo_atencion(t):
        return False
    if extraer_fecha(texto) or extraer_hora(texto) or extraer_ubicacion(texto):
        return False

    conectores_permitidos = {"de", "del", "la", "las", "los", "don", "dona", "doña"}
    palabras_validas = [tok for tok in toks if tok not in conectores_permitidos]
    return len(palabras_validas) >= 1


def _limpiar_nombre_detectado(nombre: str):
    """
    Limpia un nombre detectado dentro de una frase más larga.
    Ejemplos:
    - "Ricardo Mena y estaría bien..." -> "Ricardo Mena"
    - "Marjorie Castro, mañana..." -> "Marjorie Castro"
    - "Don Pedro el jueves..." -> "Don Pedro"
    """
    nombre = (nombre or "").strip(" .,;:\n\t")

    if not nombre:
        return None

    # Corta cuando el cliente continúa la frase con agenda, condición o explicación.
    # Se incluye " y " porque es muy común: "Mi nombre es Ricardo Mena y...".
    cortes = [
        r",\s*el\s+",
        r"\s+el\s+(?=(?:lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo|hoy|mañana|manana|mñn|mnn|pasado))",
        r"\s+y\s+",
        r"\s+pero\s+",
        r"\s+para\s+",
        r"\s+porque\s+",
        r"\s+que\s+",
        r"\s+estaria\s+",
        r"\s+estaría\s+",
        r"\s+seria\s+",
        r"\s+sería\s+",
        r"\s+quisiera\s+",
        r"\s+quiero\s+",
        r"\s+necesito\s+",
        r"\s+prefiero\s+",
        r"\s+me\s+",
        r"\s+el\s+(?:lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo)",
        r"\s+(?:mañana|manana|mñn|mnn|hoy|lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo)\b",
        r"\s+(?:a\s+las|tipo|en\s+la\s+mañana|por\s+la\s+mañana|en\s+la\s+tarde|por\s+la\s+tarde|en\s+la\s+noche)\b",
        r"\s+(?:sector|via|vía|recinto|sitio|finca|camaronera|granja|hotel|planta)\b",
    ]

    for patron in cortes:
        partes = re.split(patron, nombre, maxsplit=1, flags=re.IGNORECASE)
        nombre = partes[0].strip(" .,;:")

    if not nombre:
        return None

    # Evita nombres demasiado largos o frases que no son nombres.
    palabras = nombre.split()
    if not (1 <= len(palabras) <= 6):
        return None

    # Valida que lo que quedó tenga forma de nombre.
    if not _parece_nombre_suelto(nombre):
        return None

    conectores = {"de", "del", "la", "las", "los", "don", "doña", "dona"}
    return " ".join(
        p.capitalize() if p.lower() not in conectores else p.lower()
        for p in palabras
    )


def extraer_nombre(mensaje: str):
    texto = mensaje or ""

    # Casos con marcador explícito de nombre.
    # Importante: capturamos todo lo que sigue y luego limpiamos, porque el cliente puede escribir:
    # "Mi nombre es Ricardo Mena y estaría bien que me llamen el jueves..."
    patrones = [
        r"(?:soy|soi|me\s+llamo|m\s+llamo|mi\s+nombre\s+es|le\s+saluda|le\s+escribe)\s+(.+)",
        r"(?:reg[ií]streme|registre|registrar|an[oó]teme|anote|a\s+nombre\s+de)\s+(?:como\s+|a\s+nombre\s+de\s+)?(.+)",
        r"(?:registrar\s+como|registreme\s+como|regístreme\s+como|anoteme\s+como|anóteme\s+como)\s+(.+)",
    ]

    for patron in patrones:
        m = re.search(patron, texto, flags=re.IGNORECASE)
        if m:
            nombre = _limpiar_nombre_detectado(m.group(1))
            if nombre:
                return nombre

    # Caso común: el cliente escribe nombre + datos de agenda en el mismo mensaje.
    # Ej.: "Marjorie Castro mañana en la tarde en mi finca".
    corte_agenda = re.search(
        r"\b(mañana|manana|mñn|mnn|hoy|lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo|a\s+las|tipo|en\s+la\s+mañana|en\s+la\s+tarde|en\s+la\s+noche|por\s+la\s+mañana|por\s+la\s+tarde)\b",
        texto,
        flags=re.IGNORECASE
    )
    if corte_agenda:
        posible_nombre = texto[:corte_agenda.start()].strip(" .,;:")
        nombre = _limpiar_nombre_detectado(posible_nombre)
        if nombre:
            return nombre

    # Caso de nombre solo: "Ricardo Mena".
    if _parece_nombre_suelto(texto):
        return " ".join(
            p.capitalize() if p.lower() not in ["de", "del", "la", "las", "los"] else p.lower()
            for p in texto.strip().split()
        )

    return None

def normalizar_expresiones_tiempo(texto: str) -> str:
    t = normalizar(texto)

    # Primero aplica reemplazos centralizados del léxico base.
    for frase, sustituto in REEMPLAZOS_TIEMPO.items():
        t = t.replace(normalizar(frase), normalizar(sustituto))

    # Refuerzos adicionales por escritura informal muy común.
    t = t.replace("mñn", "manana").replace("mnn", "manana")
    return t

def _hora_desde_match(m):
    grupos = [g for g in m.groups() if g is not None]
    texto = m.group(0).strip()
    if not grupos:
        return texto
    try:
        hora = int(grupos[0])
        minutos = 0
        meridiano = None
        for g in grupos[1:]:
            g_norm = normalizar(str(g))
            if g_norm.isdigit() and len(g_norm) <= 2:
                minutos = int(g_norm)
            elif g_norm in ["am", "pm"]:
                meridiano = g_norm
            elif g_norm in ["tarde", "noche"] and hora < 12:
                meridiano = "pm"
            elif g_norm == "manana":
                meridiano = "am"
        if meridiano == "pm" and hora < 12:
            hora += 12
        if meridiano == "am" and hora == 12:
            hora = 0
        return f"{hora:02d}:{minutos:02d}"
    except Exception:
        return texto


def extraer_hora(mensaje: str):
    t = normalizar_expresiones_tiempo(mensaje)

    patrones = [
        r"\b(?:a las|desde las)\s*([01]?\d|2[0-3])[:h]([0-5]\d)\b",
        r"\b(?:a las|desde las)\s*([01]?\d|2[0-3])\s+([0-5]\d)\b",
        r"\b(?:a las|desde las)\s*([1-9]|1[0-2])\s*(am|pm)\b",
        r"\b([1-9]|1[0-2])\s*(am|pm)\b",
        r"\b(?:a las)\s*([1-9]|1[0-2])\s*y\s*media\b",
        r"\b(?:a las)\s*([1-9]|1[0-2])\s*de\s*(la\s*)?(manana|tarde|noche)\b",
        r"\b(?:a las)\s*([1-9]|1[0-2])\b",
        r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b",
    ]

    for patron in patrones:
        m = re.search(patron, t)
        if m:
            return _hora_desde_match(m)

    if any(x in t for x in ["en la manana", "por la manana", "de manana", "temprano"]):
        return "en la mañana"
    if any(x in t for x in ["medio dia", "mediodia", "al medio dia", "al mediodia"]):
        return "al mediodía"
    if any(x in t for x in ["en la tarde", "por la tarde", "de tarde"]):
        return "en la tarde"
    if any(x in t for x in ["en la noche", "por la noche", "de noche"]):
        return "en la noche"

    return None


def extraer_fecha(mensaje: str):
    t = normalizar_expresiones_tiempo(mensaje)

    dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    for dia in dias:
        if dia in t:
            return dia.replace("miercoles", "miércoles").replace("sabado", "sábado")

    if "pasado manana" in t:
        return "pasado mañana"
    if "manana" in t:
        return "mañana"
    if "hoy" in t:
        return "hoy"
    if "en una semana" in t:
        return "en una semana"
    if "en dos dias" in t:
        return "pasado mañana"

    m = re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", t)
    if m:
        return m.group(0)

    m = re.search(r"\b(?:el\s+)?\d{1,2}\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b", t)
    if m:
        return m.group(0)

    return None


def extraer_ubicacion(mensaje: str):
    if not mensaje:
        return None

    t = normalizar(mensaje)

    if "maps.google" in t or "ubicacion enviada" in t or "https maps" in t or "maps" in t:
        return mensaje.strip()[:180]

    for frase, valor in FRASES_UBICACION_GENERICA.items():
        if normalizar(frase) in t:
            return valor

    # Evita confundir fecha/hora corta con ubicación.
    if len(t.split()) <= 3 and any(x in t for x in ["manana", "tarde", "noche", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]):
        return None

    patrones = [
        r"(?:sector|via|vía|recinto|sitio|parroquia|canton|cantón|km|kilometro|kilómetro|ubicad[oa] en|queda en|est[aá] en|por(?!\s+la\s+(?:mañana|manana|tarde|noche))|x(?!\s+(?:facebook|fb|face))|cerca de|cerca al|entrada a|junto a|al lado de|alado de)\s+([a-zA-Z0-9áéíóúÁÉÍÓÚñÑ .,#\-/]{4,110})",
        r"(?:\ben\s+)(?!la\s+(?:mañana|manana|tarde|noche)|el\s+(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)|facebook|face|fb|instagram|redes|publicidad|anuncio)([a-zA-Z0-9áéíóúÁÉÍÓÚñÑ .,#\-/]{4,110})",
        r"(?:finca|camaronera|granja|hotel|hosteria|planta|proyecto|hacienda|predio)\s+[a-zA-Z0-9áéíóúÁÉÍÓÚñÑ .\-/]{2,80}(?:,|\s+en\s+|\s+sector\s+|\s+via\s+|\s+vía\s+|\s+por\s+)([a-zA-Z0-9áéíóúÁÉÍÓÚñÑ .,#\-/]{4,110})",
    ]

    for patron in patrones:
        m = re.search(patron, mensaje, flags=re.IGNORECASE)
        if m:
            ubicacion = m.group(1).strip(" .,;:\n")
            ubic_norm_limpio = normalizar(ubicacion)
            if ubic_norm_limpio in NO_UBICACIONES or any(no in ubic_norm_limpio.split() for no in NO_UBICACIONES):
                return None

            if detectar_motivo(ubicacion) or detectar_actividad(ubicacion):
                return None

            cortes = [
                " soy ", " me llamo ", " m llamo ", " a nombre ", " registre", " regístreme",
                " manana", " mañana", " mñn", " lunes", " martes", " miercoles", " miércoles",
                " jueves", " viernes", " sabado", " sábado", " domingo", " a las ", " tipo "
            ]
            ubic_norm = " " + normalizar(ubicacion) + " "
            corte_idx = None
            for corte in cortes:
                idx = ubic_norm.find(normalizar(corte))
                if idx > 0:
                    corte_idx = idx if corte_idx is None else min(corte_idx, idx)
            if corte_idx is not None:
                ubicacion = ubicacion[:corte_idx].strip(" .,;:")
            return ubicacion[:120]

    return None


def extraer_finca_o_proyecto(mensaje: str):
    patron = r"(?:finca|camaronera|granja|hotel|hosteria|planta|proyecto|hacienda|predio)\s+([a-zA-Z0-9áéíóúÁÉÍÓÚñÑ .\-/]{3,80})"
    m = re.search(patron, mensaje or "", flags=re.IGNORECASE)
    if m:
        valor = m.group(0).strip(" .,;:\n")
        if contiene(valor, ["para que revise", "para revisar", "para que vea", "lo puedo recibir", "recibir en la finca"]):
            return None
        cortes = [",", " por ", " sector ", " via ", " vía ", " mañana", " manana", " mñn", " lunes", " martes", " miércoles", " miercoles", " jueves", " viernes", " sabado", " sábado", " domingo", " a las ", " tipo "]
        for corte in cortes:
            idx = normalizar(valor).find(normalizar(corte))
            if idx > 0:
                valor = valor[:idx].strip(" .,;:")
        valor_norm = normalizar(valor)
        genericos = ["finca", "finca bananera", "hacienda bananera", "camaronera", "granja", "granja porcina", "granja avicola", "hotel", "planta", "industria", "proyecto", "hacienda", "predio"]
        if valor_norm in genericos:
            return None
        return valor[:90]
    return None


def extraer_datos_cita(mensaje: str):
    return {
        "nombre": extraer_nombre(mensaje),
        "fecha": extraer_fecha(mensaje),
        "hora": extraer_hora(mensaje),
        "ubicacion": extraer_ubicacion(mensaje),
        "finca_proyecto": extraer_finca_o_proyecto(mensaje),
    }


def mensaje_tiene_datos_de_cita(mensaje: str) -> bool:
    datos = extraer_datos_cita(mensaje)
    return any([datos.get("fecha"), datos.get("hora"), datos.get("ubicacion"), datos.get("finca_proyecto")])
