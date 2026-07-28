ACTIVIDAD_LABELS = {
    "bananera": "finca bananera",
    "camaronera": "camaronera",
    "mineria": "actividad minera",
    "cacaotera": "finca cacaotera",
    "cultivo_ciclo_corto": "cultivo de ciclo corto",
    "granja_porcina": "granja porcina",
    "granja_avicola": "granja avícola",
    "hotel": "hotel u hostería",
    "industria": "industria o planta",
    "otra": "actividad productiva",
    "otros": "actividad productiva",
}

MOTIVO_LABELS = {
    "credito_bancario": "requerimiento de banco o crédito",
    "certificacion": "certificación o auditoría",
    "autoridad": "requerimiento de autoridad ambiental",
    "regularizacion": "regularización o permiso ambiental",
    "seguimiento": "seguimiento de obligaciones ambientales",
    "precio": "consulta de valor",
}


ACTIVIDADES_SERVICIO_TEXTO = (
    "bananeras, camaroneras, minería, cacaoteras, cultivos de ciclo corto, "
    "granjas porcinas, granjas avícolas, hoteles, industrias u otras actividades productivas"
)


def label_actividad(actividad):
    return ACTIVIDAD_LABELS.get(actividad or "otra", "actividad")


def label_motivo(motivo):
    return MOTIVO_LABELS.get(motivo or "", "cumplimiento ambiental")


def bienvenida(origen):
    if origen == "referido":
        return (
            "Hola, le saluda el equipo técnico de DALGORO S.A.S. "
            "Me indicaron que podríamos apoyarle con el tema ambiental. "
            "Para orientarle bien: ¿qué actividad maneja y en qué sector está ubicada?"
        )

    if origen == "facebook":
        return (
            "Hola, gracias por escribir a DALGORO S.A.S. "
            "Le ayudo a revisar qué aplica en su caso sin hacerlo escribir demasiado. "
            f"¿Su consulta se refiere a qué tipo de actividad: {ACTIVIDADES_SERVICIO_TEXTO}?"
        )

    return (
        "Hola, le saluda el equipo técnico de DALGORO S.A.S. "
        f"Con gusto le orientamos. Para ubicar mejor su caso: ¿qué actividad maneja y en qué sector se encuentra? Cuéntenos a cuál de estas actividades se dedica usted: {ACTIVIDADES_SERVICIO_TEXTO}."
    )


def pedir_motivo(actividad):
    act = label_actividad(actividad)
    return (
        f"Entiendo, se trata de una {act}. "
        "Para orientarle correctamente, ¿el tema ambiental lo necesita por un requerimiento bancario, por estarse calificando para una certificación, porque la autoridad ambiental se lo solicita, porque usted requiere regular su actividad ambientalmente por primera vez o requiere que se le de el seguimiento a las obligaciones ambientales?"
    )


def explicar_servicio_y_ofrecer_siguiente_paso(actividad, motivo):
    act = label_actividad(actividad)
    mot = label_motivo(motivo)

    if motivo == "credito_bancario":
        contexto = "En estos casos conviene revisar antes la documentación ambiental para evitar observaciones durante el trámite del crédito."
    elif motivo == "certificacion":
        contexto = "Para certificaciones o auditorías es importante verificar que permisos, obligaciones e informes estén coherentes y actualizados."
    elif motivo == "autoridad":
        contexto = "Cuando existe requerimiento de autoridad, lo mejor es revisar el caso con cuidado antes de responder o presentar documentación."
    elif motivo == "regularizacion":
        contexto = "Si aún no está regularizado, primero se debe identificar qué permiso o trámite corresponde según la actividad y escala."
    elif motivo == "seguimiento":
        contexto = "Si ya cuenta con permiso, el punto clave es revisar obligaciones, vencimientos, evidencias e informes pendientes."
    else:
        contexto = "Podemos revisar el caso y orientarle sobre el camino más conveniente para cumplir sin complicaciones."

    return (
        f"Gracias, con eso ya tengo una idea del caso: {act} por {mot}. "
        f"{contexto} "
        "Podemos empezar con una revisión de documentación o con un diagnóstico inicial gratuito para decirle qué le falta y qué conviene hacer. "
        "¿Desea que lo revisemos por llamada breve o prefiere una visita técnica?"
    )


def proponer_visita_o_llamada(actividad, motivo):
    # Se mantiene el nombre de la función para no afectar el gestor.
    return explicar_servicio_y_ofrecer_siguiente_paso(actividad, motivo)


def pedir_preferencia_atencion(actividad=None, motivo=None):
    act = label_actividad(actividad) if actividad else "su caso"

    if motivo == "credito_bancario":
        return (
            f"Entiendo. Para el requisito del banco conviene revisar rápido la documentación de {act} antes de que le hagan observaciones. "
            "Podemos empezar con una llamada breve o, si prefiere, una visita técnica. ¿Qué le conviene más?"
        )

    if motivo == "certificacion":
        return (
            f"Para certificación o auditoría de {act}, lo ideal es revisar permisos, evidencias e informes antes de la inspección. "
            "¿Prefiere que lo revisemos por llamada breve o mediante una visita técnica?"
        )

    if motivo == "regularizacion":
        return (
            f"Para regularizar {act}, primero se valida qué permiso o trámite corresponde. "
            "Podemos orientarle por llamada breve o hacer una visita técnica de diagnóstico. ¿Qué le resulta mejor?"
        )

    if motivo == "seguimiento":
        return (
            f"Para seguimiento de {act}, revisamos obligaciones, informes, vencimientos y evidencias pendientes. "
            "¿Desea empezar con una llamada breve o prefiere una visita técnica?"
        )

    if motivo == "autoridad":
        return (
            f"Si hay requerimiento de autoridad, conviene revisar {act} con cuidado antes de responder o presentar documentos. "
            "¿Le conviene una llamada breve o una visita técnica?"
        )

    return (
        "Perfecto. Para continuar sin hacerlo perder tiempo, podemos hacerlo de dos formas: "
        "una llamada breve para revisar el caso o una visita técnica para diagnóstico inicial. "
        "¿Qué le conviene más: llamada o visita?"
    )


def pedir_datos_cita(tipo_atencion):
    if tipo_atencion == "llamada":
        return (
            "De acuerdo, coordinemos una llamada. "
            "Para agendarla, envíeme por favor su nombre y el día/hora aproximada en que puede atender."
        )

    return (
        "De acuerdo, coordinemos la visita técnica. "
        "Para agendarla, envíeme por favor su nombre, el sector o ubicación de la finca/proyecto, y el día/hora que le queda mejor. "
        "También puede enviar la ubicación por WhatsApp."
    )


def pedir_datos_faltantes(faltantes, tipo_atencion):
    if not faltantes:
        return "¿Me confirma por favor los datos para dejar la coordinación registrada?"

    if faltantes == ["actividad"]:
        return "Para orientarle bien, ¿me confirma qué actividad maneja? Puede ser bananera, camaronera, minería, cacaotera, cultivo de ciclo corto, granja porcina, granja avícola, hotel, industria u otra actividad."

    if faltantes == ["nombre"]:
        return "Solo para dejarlo correctamente registrado: ¿a nombre de quién dejo la coordinación?"

    if faltantes == ["fecha_hora"]:
        if tipo_atencion == "llamada":
            return "¿Qué día y hora aproximada le queda bien para que el Ing. Darwin González pueda llamarle?"
        return "¿Qué día y hora aproximada le queda bien para la visita técnica?"

    if faltantes == ["ubicacion"]:
        return "¿Me indica el sector o ubicación donde sería la visita? También puede enviar la ubicación por WhatsApp."

    partes = []
    if "actividad" in faltantes:
        partes.append("la actividad")
    if "nombre" in faltantes:
        partes.append("a nombre de quién queda")
    if "fecha_hora" in faltantes:
        partes.append("día y hora aproximada")
    if tipo_atencion == "visita" and "ubicacion" in faltantes:
        partes.append("sector o ubicación")

    return "Para dejarlo bien registrado, me faltaría confirmar: " + "; ".join(partes) + "."


def cita_registrada(datos):
    tipo = datos.get("Tipo_Atencion", "visita")
    fecha = datos.get("Fecha") or "fecha por confirmar"
    hora = datos.get("Hora") or "hora por confirmar"
    ubicacion = datos.get("Ubicacion") or "ubicación por confirmar"

    if tipo == "llamada":
        return (
            "Listo, queda registrada la llamada.\n\n"
            f"📅 Día: {fecha}\n"
            f"⏰ Hora: {hora}\n\n"
            "El Ing. Darwin González se contactará directamente para confirmar los detalles."
        )

    return (
        "Listo, queda registrada la visita técnica.\n\n"
        f"📅 Día: {fecha}\n"
        f"⏰ Hora: {hora}\n"
        f"📍 Lugar: {ubicacion}\n\n"
        "El Ing. Darwin González se contactará directamente para confirmar los detalles."
    )


def cita_actualizada(datos):
    tipo = datos.get("Tipo_Atencion", "visita")
    fecha = datos.get("Fecha") or "fecha por confirmar"
    hora = datos.get("Hora") or "hora por confirmar"
    ubicacion = datos.get("Ubicacion") or "ubicación por confirmar"

    if tipo == "llamada":
        return (
            "Listo, dejo reportado el ajuste de la llamada.\n\n"
            f"📅 Día: {fecha}\n"
            f"⏰ Hora: {hora}\n\n"
            "El Ing. Darwin González lo confirmará directamente."
        )

    return (
        "Listo, dejo reportado el ajuste de la visita.\n\n"
        f"📅 Día: {fecha}\n"
        f"⏰ Hora: {hora}\n"
        f"📍 Lugar: {ubicacion}\n\n"
        "El Ing. Darwin González lo confirmará directamente."
    )


def responder_precio_sin_perder_cierre(actividad):
    act = label_actividad(actividad)
    return (
        f"El valor depende de si la {act} ya cuenta con permiso, si requiere regularización inicial o si tiene obligaciones pendientes. "
        "Para no darle una cifra incompleta por chat, podemos hacer primero una revisión breve del caso y con eso orientarle mejor. "
        "¿Desea que lo revisemos por llamada o mediante una visita técnica?"
    )


def responder_informacion_general(actividad=None, motivo=None):
    if actividad or motivo:
        return explicar_servicio_y_ofrecer_siguiente_paso(actividad or "otra", motivo)

    return (
        "Claro. En DALGORO S.A.S. apoyamos con regularización, licenciamiento y seguimiento ambiental para actividades productivas. "
        "Primero revisamos qué actividad maneja y por qué le están solicitando el cumplimiento ambiental; con eso se le puede orientar sin hacerlo perder tiempo. "
        f"¿Su consulta se refiere para cuál de estas actividades: {ACTIVIDADES_SERVICIO_TEXTO}?"
    )



def responder_revision_documental_puntual(actividad=None, motivo=None):
    """
    Respuesta breve para cuando el cliente ya recibió la orientación general
    y vuelve a preguntar si se puede revisar documentación, obligaciones o el caso.
    Evita repetir el bloque completo de orientación.
    """
    act = label_actividad(actividad) if actividad else "su actividad"

    if motivo == "seguimiento":
        return (
            f"Sí, también revisamos documentación y obligaciones ambientales de {act}. "
            "Podemos verificar permiso, vencimientos, informes, evidencias y posibles pendientes. "
            "Para avanzar sin hacerlo escribir demasiado, ¿prefiere una llamada breve o una visita técnica?"
        )

    if motivo == "credito_bancario":
        return (
            f"Sí, podemos revisar la documentación ambiental de {act} antes de presentarla al banco. "
            "Eso ayuda a evitar observaciones durante el trámite. "
            "¿Prefiere que lo revisemos primero por llamada breve o mediante una visita técnica?"
        )

    if motivo == "certificacion":
        return (
            f"Sí, podemos revisar la documentación de {act} para certificación o auditoría. "
            "La idea es verificar permisos, evidencias e informes antes de que le observen algo. "
            "¿Le conviene una llamada breve o una visita técnica?"
        )

    if motivo == "autoridad":
        return (
            f"Sí, podemos revisar la documentación de {act} antes de responder a la autoridad. "
            "Conviene ordenar bien el caso para no presentar información incompleta. "
            "¿Prefiere una llamada breve o una visita técnica?"
        )

    return (
        f"Sí, podemos hacer una revisión inicial de {act} y decirle qué documentos u obligaciones conviene ordenar primero. "
        "¿Le resulta mejor una llamada breve o una visita técnica?"
    )

def pedir_aclaracion_suave(etapa=None):
    if etapa == "esperando_motivo":
        return (
            "Disculpe, para orientarle bien necesito precisar el motivo. "
            "¿Se lo están pidiendo por banco, certificación, autoridad ambiental, regularización inicial o seguimiento de obligaciones ambientales?"
        )

    if etapa == "esperando_preferencia_atencion":
        return "Para avanzar, ¿prefiere que se revise por llamada breve o mediante visita técnica?"

    if etapa == "esperando_datos_cita":
        return "Creo que me faltó un dato para registrar bien la coordinación. ¿Me confirma nombre, día/hora y ubicación para la visita?"

    return (
        "Disculpe, no quiero asumir mal la información. "
        "¿Me puede aclarar en una frase qué actividad maneja y qué necesita revisar?"
    )


def despedida_silenciosa():
    return "Con gusto 👍"


def no_interesado():
    return (
        "Comprendido, no le insistiremos. "
        "Si más adelante necesita revisar cumplimiento ambiental de su actividad, con gusto estaremos atentos para servirle."
    )


def molestia_o_desconfianza():
    return (
        "Entiendo. Disculpe la confusión. Le escribe el equipo técnico de DALGORO S.A.S.; "
        "no solicitamos pagos ni datos sensibles por este medio. Si no desea continuar, no le volveremos a escribir."
    )


def consulta_post_cita():
    return (
        "Sí, con gusto. Esa consulta la puede revisar directamente el Ing. Darwin González cuando se contacte con usted, "
        "para darle una respuesta correcta según su caso y no una información incompleta por chat."
    )


def nueva_finca():
    return (
        "Claro, podemos revisarla como una coordinación adicional para no mezclarla con la anterior. "
        "Indíqueme por favor qué actividad es, el sector o ubicación de esa finca/proyecto, y si prefiere llamada o visita para una mejor coordinación."
    )


def cambio_cita():
    return "Claro, podemos ajustar la coordinación. Indíqueme por favor el nuevo día, hora y ubicación si también cambia el lugar."


def cancelacion():
    return "Comprendido, dejamos sin efecto la coordinación. Si más adelante necesita retomarlo, con gusto le apoyamos."


# ======================================================
# RESPUESTAS ESPECÍFICAS A CAMPAÑAS AUTOMÁTICAS
# ======================================================

def responder_campana_interes_general():
    return (
        "Hola, le saluda el equipo técnico de DALGORO S.A.S. Claro, con gusto. "
        "Para orientarle sin asumir mal su caso, primero necesito ubicar la actividad. "
        f"Trabajamos con: {ACTIVIDADES_SERVICIO_TEXTO}. "
        "¿Qué actividad maneja usted?"
    )


def responder_campana_evaluacion():
    return (
        "Sí, la evaluación primaria no tiene costo ni compromiso. Consiste en revisar de forma inicial qué actividad maneja, "
        "si ya cuenta con permiso ambiental y qué le podrían solicitar en las entidades bancarias, las certificadoras, en una auditoría ambiental o en una inspección por parte de la autoridad ambiental. "
        "Para orientarle bien: ¿qué actividad maneja?"
    )


def responder_campana_precio(actividad=None):
    act = label_actividad(actividad)
    if actividad:
        return (
            f"El valor depende de si la {act} requiere regularización inicial, seguimiento mensual o revisión documental. "
            "Antes de darle una cifra incompleta, podemos hacer una evaluación primaria gratuita para decirle qué aplica en su caso. "
            "¿El trámite lo necesita por banco, certificación, autoridad, regularización inicial o seguimiento?"
        )

    return (
        "El valor depende del tipo de actividad y de si necesita regularización inicial, seguimiento mensual o revisión documental. "
        "Para no darle una cifra incompleta, primero ubicamos su caso con una evaluación primaria gratuita. "
        f"¿Su actividad es parte de estas: {ACTIVIDADES_SERVICIO_TEXTO}?"
    )


def responder_campana_quienes_son():
    return (
        "Hola, le saluda el equipo técnico de DALGORO S.A.S. Entiendo su preocupación. "
        "Somos una empresa de consultoría ambiental que apoya a actividades productivas con regularización, licenciamiento, "
        "seguimiento ambiental, informes técnicos y preparación documental para auditorías o requerimientos. "
        "No solicitamos pagos ni datos sensibles por este medio. "
        "Para orientarle con algo útil, ¿qué actividad maneja usted?"
    )


def responder_campana_ya_tiene_permiso(actividad=None):
    act = label_actividad(actividad)
    if actividad:
        return (
            f"Perfecto, en una {act} tener permiso ya es un buen avance. El siguiente punto es revisar si las obligaciones, informes, evidencias "
            "y vencimientos están al día para evitar observaciones. Podemos hacerle una revisión primaria gratuita. "
            "¿Ese permiso lo desea revisar por banco, certificación, autoridad o seguimiento mensual?"
        )

    return (
        "Perfecto, si ya cuenta con permiso ambiental, podemos ayudarle con seguimiento, informes técnicos, evidencias y preparación para auditorías. "
        "Para orientarle mejor: ¿qué actividad maneja?"
    )


def responder_campana_ya_tiene_consultor():
    return (
        "Entiendo. Si ya cuenta con consultor, no hay problema. En ese caso podemos apoyarle solo con una segunda revisión primaria, "
        "sin compromiso, para confirmar si todo está al día o si existe algún riesgo documental. "
        "Si desea revisarlo, indíqueme qué actividad maneja."
    )


def responder_campana_sanciones_auditoria(actividad=None):
    act = label_actividad(actividad) if actividad else "actividad"
    return (
        f"Cuando hay auditoría, observación o riesgo de sanción, conviene revisar documentos antes de responder o presentar información. "
        f"Podemos hacer una evaluación primaria de su {act} para identificar qué falta y qué conviene ordenar primero. "
        "¿Esto viene por autoridad, certificación, banco o revisión interna?"
    )



def responder_pregunta_servicios(actividad=None, motivo=None):
    """
    Responde cuando el cliente pregunta explícitamente qué servicios ofrece DALGORO.
    Esta respuesta habilita el envío del PDF, pero no fuerza una cita inmediata.
    """
    if actividad:
        act = label_actividad(actividad)
        return (
            f"Claro. Para {act}, en DALGORO S.A.S. podemos apoyar con regularización o licenciamiento ambiental, "
            "revisión documental, seguimiento de obligaciones, informes técnicos y preparación ante requerimientos de bancos, "
            "certificaciones o autoridad ambiental. "
            "Le comparto nuestro documento de servicios para que lo revise con calma. Luego, si desea, podemos indicarle qué aplica en su caso específico."
        )

    return (
        "Claro. En DALGORO S.A.S. apoyamos con regularización, licenciamiento ambiental, revisión documental, "
        "seguimiento de obligaciones, informes técnicos y acompañamiento ante bancos, certificaciones o autoridad ambiental. "
        "Le comparto nuestro documento de servicios para que lo revise con calma. Luego podemos orientarle según su actividad."
    )


def mensaje_pdf_servicios(motivo="informacion"):
    """
    Mensaje breve que acompaña el PDF institucional.
    Se usa como caption del documento para que no se sienta invasivo.
    """
    if motivo == "identidad":
        return (
            "Le comparto el documento institucional de DALGORO S.A.S. para que pueda revisar con calma quiénes somos y los servicios que ofrecemos. "
            "No solicitamos pagos ni datos sensibles por este medio."
        )

    if motivo == "evaluacion":
        return (
            "Le comparto nuestro documento de servicios. Ahí puede revisar el alcance de DALGORO S.A.S.; luego podemos orientarle según su actividad y el trámite que necesita."
        )

    return (
        "Le comparto nuestro documento de servicios para que lo revise con calma. Luego, si desea, podemos orientarle según su actividad y el trámite que necesita."
    )


def llamada_recibida():
    return (
        "Disculpe, en este momento no podemos atender llamadas por este medio. "
        "Si desea, indíqueme si prefiere que el Ing. Darwin le devuelva la llamada o si coordinamos una visita técnica."
    )


def archivo_o_audio_recibido():
    return (
        "Recibimos su archivo o audio. Para atenderlo rápido, puede escribirnos en una frase: "
        "actividad, sector y qué necesita revisar. Si prefiere, también podemos coordinar una llamada breve del Ing. Darwin."
    )


def mensaje_ambiguedad_final():
    return (
        "Para avanzar sin hacerlo escribir mucho, puede enviarnos solo estos datos: "
        "actividad, sector y qué necesita revisar. Con eso le damos una orientación más precisa."
    )
