from copy import deepcopy
from ia_intenciones import (
    detectar_actividad,
    detectar_motivo,
    detectar_origen,
    detectar_intencion,
    detectar_tipo_atencion,
    extraer_datos_cita,
    mensaje_tiene_datos_de_cita,
    es_afirmacion,
    _mensaje_declara_actividad,
)
from respuestas_comerciales import (
    bienvenida,
    pedir_motivo,
    proponer_visita_o_llamada,
    pedir_preferencia_atencion,
    pedir_datos_cita,
    pedir_datos_faltantes,
    cita_registrada,
    cita_actualizada,
    responder_precio_sin_perder_cierre,
    responder_informacion_general,
    responder_revision_documental_puntual,
    pedir_aclaracion_suave,
    despedida_silenciosa,
    no_interesado,
    molestia_o_desconfianza,
    consulta_post_cita,
    nueva_finca,
    cambio_cita,
    cancelacion,
    mensaje_ambiguedad_final,
    responder_campana_interes_general,
    responder_campana_evaluacion,
    responder_campana_precio,
    responder_campana_quienes_son,
    responder_campana_ya_tiene_permiso,
    responder_campana_ya_tiene_consultor,
    responder_campana_sanciones_auditoria,
    mensaje_pdf_servicios,
    responder_pregunta_servicios,
)
from time_utils import ahora_txt


def crear_estado_inicial():
    return {
        "etapa": "inicio",
        "origen": "directo",
        "actividad": None,
        "motivo": None,
        "nombre": None,
        "tipo_atencion": None,
        "finca_proyecto": None,
        "ubicacion": None,
        "fecha": None,
        "hora": None,
        "id_cita_activa": None,
        "mensaje_original_cita": None,
        "despedida_respondida": False,
        "contador_ambiguedad": 0,
        "orientacion_dada": False,
        "nombre_solicitado": False,
        "pdf_servicios_enviado": False,
        "pdf_bloqueado_por_desconfianza": False,
        "ultima_interaccion": ahora_txt(),
    }


def limpiar_campos_cita(estado):
    estado["actividad"] = None
    estado["motivo"] = None
    estado["tipo_atencion"] = None
    estado["finca_proyecto"] = None
    estado["ubicacion"] = None
    estado["fecha"] = None
    estado["hora"] = None
    estado["id_cita_activa"] = None
    estado["mensaje_original_cita"] = None
    estado["despedida_respondida"] = False
    estado["contador_ambiguedad"] = 0
    estado["orientacion_dada"] = False
    estado["nombre_solicitado"] = False
    estado["pdf_servicios_enviado"] = False
    estado["pdf_bloqueado_por_desconfianza"] = False


def _puede_actualizar_actividad(estado, actividad_nueva):
    """
    Evita que una ubicación o nombre de finca cambie la actividad ya detectada.
    Ejemplo: si el cliente dijo "tengo chanchera" y luego agenda "en la camaronera Los Esteros",
    no debemos cambiar granja_porcina por camaronera solo por el lugar.
    """
    if not actividad_nueva:
        return False

    actividad_actual = estado.get("actividad")
    etapa = estado.get("etapa") or "inicio"

    if not actividad_actual:
        return True

    # Si antes quedó genérico, una actividad específica sí puede reemplazarlo.
    if actividad_actual in ["otra", "otros"] and actividad_nueva not in ["otra", "otros"]:
        return True

    # En etapas tempranas sí aceptamos correcciones del propio cliente.
    etapas_abiertas = [
        "inicio", "esperando_actividad", "campana_esperando_actividad",
        "campana_identidad", "campana_permiso_detectado", "campana_consultor_existente",
        "campana_sanciones_auditoria"
    ]
    if etapa in etapas_abiertas and actividad_actual != actividad_nueva:
        return True

    return False


def actualizar_estado_con_mensaje(estado, mensaje):
    estado["origen"] = detectar_origen(mensaje, estado.get("origen"))

    actividad = detectar_actividad(mensaje)
    actividad_actual = estado.get("actividad")
    if _puede_actualizar_actividad(estado, actividad) or (
        actividad and actividad_actual and actividad_actual != actividad and _mensaje_declara_actividad(mensaje)
    ):
        # Si el cliente corrige la actividad explícitamente, se actualiza y se permite reorientar.
        if actividad_actual and actividad_actual != actividad:
            estado["orientacion_dada"] = False
        estado["actividad"] = actividad

    motivo = detectar_motivo(mensaje)
    if motivo and motivo != "precio":
        motivo_anterior = estado.get("motivo")
        if motivo_anterior != motivo:
            estado["motivo"] = motivo
            # Si veníamos de una consulta de precio y luego el cliente aclara el motivo real,
            # permitimos una orientación nueva para evitar repetir la misma respuesta genérica.
            if motivo_anterior == "precio":
                estado["orientacion_dada"] = False

    tipo_atencion = detectar_tipo_atencion(mensaje)
    if tipo_atencion:
        estado["tipo_atencion"] = tipo_atencion

    datos = extraer_datos_cita(mensaje)
    for campo in ["nombre", "fecha", "hora", "ubicacion", "finca_proyecto"]:
        if datos.get(campo):
            estado[campo] = datos[campo]
            if campo == "nombre":
                estado["nombre_solicitado"] = False

    # Si el cliente ya manda fecha/hora y ubicación sin decir "visita", normalmente quiere coordinación presencial.
    # No inferimos visita solo porque escribió "finca bananera", ya que eso es actividad, no agenda.
    if not estado.get("tipo_atencion") and mensaje_tiene_datos_de_cita(mensaje):
        if datos.get("ubicacion") and (datos.get("fecha") or datos.get("hora")):
            estado["tipo_atencion"] = "visita"

    estado["ultima_interaccion"] = ahora_txt()


def datos_contacto_para_sheet(estado):
    return {
        "nombre": estado.get("nombre") or "",
        "origen": estado.get("origen") or "directo",
        "actividad": estado.get("actividad") or "",
        "motivo": estado.get("motivo") or "",
        "etapa": estado.get("etapa") or "",
        "estado_comercial": "En conversación" if estado.get("etapa") not in ["cerrado_no_interesado", "cerrado_molestia"] else "Cerrado",
        "observacion": ""
    }


def faltantes_para_cierre(estado):
    tipo = estado.get("tipo_atencion") or "visita"
    faltantes = []

    if not estado.get("actividad"):
        faltantes.append("actividad")

    if not estado.get("nombre"):
        faltantes.append("nombre")

    if not estado.get("fecha") or not estado.get("hora"):
        faltantes.append("fecha_hora")

    if tipo == "visita" and not estado.get("ubicacion"):
        faltantes.append("ubicacion")

    return faltantes


def armar_datos_cita(telefono, estado, mensaje):
    tipo_atencion = estado.get("tipo_atencion") or "visita"

    # Si la coordinación es llamada, no se arrastran ubicaciones detectadas en mensajes anteriores
    # porque pueden venir de frases como "vengo de Facebook" o del sector inicial, y no son necesarias.
    ubicacion = "" if tipo_atencion == "llamada" else (estado.get("ubicacion") or "")
    finca_proyecto = "" if tipo_atencion == "llamada" else (estado.get("finca_proyecto") or "")

    return {
        "ID_Cita": estado.get("id_cita_activa") or "",
        "Telefono": telefono,
        "Nombre": estado.get("nombre") or "",
        "Origen": estado.get("origen") or "directo",
        "Actividad": estado.get("actividad") or "otra",
        "Motivo": estado.get("motivo") or "",
        "Tipo_Atencion": tipo_atencion,
        "Finca_Proyecto": finca_proyecto,
        "Ubicacion": ubicacion,
        "Fecha": estado.get("fecha") or "",
        "Hora": estado.get("hora") or "",
        "Estado": "Agendada",
        "Mensaje_Original": estado.get("mensaje_original_cita") or mensaje,
    }


def preparar_resultado(estado):
    return {
        "respuesta": None,
        "estado": estado,
        "contacto": datos_contacto_para_sheet(estado),
        "registrar_cita": None,
        "actualizar_cita": None,
        "cancelar_cita": None,
        "registrar_sin_cierre": None,
        "notificar_cita": None,
        "notificar_cita_actualizada": None,
        "notificar_cancelacion": None,
        "notificar_sin_cierre": None,
        "enviar_pdf_servicios": None,
    }


def registrar_sin_cierre_resultado(resultado, telefono, estado, mensaje, accion):
    datos = {
        "Telefono": telefono,
        "Nombre": estado.get("nombre") or "",
        "Origen": estado.get("origen") or "directo",
        "Actividad": estado.get("actividad") or "",
        "Motivo": estado.get("motivo") or "",
        "Ultima_Etapa": estado.get("etapa") or "",
        "Ultimo_Mensaje": mensaje,
        "Accion_Sugerida": accion,
    }
    resultado["registrar_sin_cierre"] = datos
    resultado["notificar_sin_cierre"] = datos




def _programar_envio_pdf_servicios(resultado, estado, motivo="informacion"):
    """
    Marca el envío del PDF institucional una sola vez por conversación.
    El envío real se realiza en webhook.py para no mezclar lógica comercial con Green API.
    """
    if estado.get("pdf_servicios_enviado"):
        return False

    # Si el cliente inició con desconfianza/identidad, no enviamos PDF de forma automática.
    # Puede parecer invasivo; primero se responde con transparencia y se deja la puerta abierta.
    if estado.get("pdf_bloqueado_por_desconfianza") and motivo != "solicitado_explicitamente":
        return False

    estado["pdf_servicios_enviado"] = True
    resultado["enviar_pdf_servicios"] = {
        "caption": mensaje_pdf_servicios(motivo)
    }
    return True


def _marcar_origen_campana(estado):
    """
    Si el contacto responde a una campaña automática y no tenía origen definido,
    lo marcamos como campana_whatsapp para CRM sin alterar otros orígenes.
    """
    if estado.get("origen") in [None, "", "directo"]:
        estado["origen"] = "campana_whatsapp"


def _manejar_respuesta_campana(intencion, estado, resultado):
    """
    Responde a mensajes derivados de la campaña automática sin saltar directo a cita.
    Retorna True si ya dejó una respuesta lista.
    """
    if not str(intencion).startswith("campana_"):
        return False

    _marcar_origen_campana(estado)
    estado["orientacion_dada"] = False

    if intencion == "campana_interes_general":
        if estado.get("actividad"):
            estado["etapa"] = "esperando_motivo"
            resultado["respuesta"] = pedir_motivo(estado.get("actividad"))
        else:
            estado["etapa"] = "campana_esperando_actividad"
            resultado["respuesta"] = responder_campana_interes_general()

    elif intencion == "campana_evaluacion":
        if estado.get("actividad"):
            estado["etapa"] = "esperando_motivo"
            resultado["respuesta"] = pedir_motivo(estado.get("actividad"))
        else:
            estado["etapa"] = "campana_esperando_actividad"
            resultado["respuesta"] = responder_campana_evaluacion()

    elif intencion == "campana_quienes_son":
        estado["etapa"] = "campana_identidad"
        estado["pdf_bloqueado_por_desconfianza"] = True
        resultado["respuesta"] = responder_campana_quienes_son()
        # No enviamos PDF automáticamente ante dudas de identidad/desconfianza.
        # Primero se responde con transparencia; si luego pide información, se envía.

    elif intencion == "campana_ya_tiene_permiso":
        if not estado.get("motivo"):
            estado["motivo"] = "seguimiento"
        if estado.get("actividad"):
            estado["etapa"] = "campana_permiso_detectado"
            resultado["respuesta"] = responder_campana_ya_tiene_permiso(estado.get("actividad"))
        else:
            estado["etapa"] = "campana_esperando_actividad"
            resultado["respuesta"] = responder_campana_ya_tiene_permiso()

    elif intencion == "campana_ya_tiene_consultor":
        estado["etapa"] = "campana_consultor_existente"
        resultado["respuesta"] = responder_campana_ya_tiene_consultor()

    elif intencion == "campana_sanciones_auditoria":
        if not estado.get("motivo"):
            estado["motivo"] = "autoridad"
        estado["etapa"] = "campana_sanciones_auditoria"
        resultado["respuesta"] = responder_campana_sanciones_auditoria(estado.get("actividad"))

    resultado["contacto"] = datos_contacto_para_sheet(estado)
    return True


def _manejar_faltantes(telefono, estado, mensaje, resultado):
    faltantes = faltantes_para_cierre(estado)

    if not faltantes:
        return False

    # Evita repetir indefinidamente el nombre. Si ya fue solicitado y el cliente no lo da,
    # seguimos pidiendo solo lo realmente indispensable sin insistir dos veces igual.
    if "nombre" in faltantes and estado.get("nombre_solicitado"):
        faltantes = [f for f in faltantes if f != "nombre"]
        if not faltantes:
            resultado["respuesta"] = "Me faltaría únicamente el nombre para dejarlo bien registrado. ¿A nombre de quién queda la coordinación?"
            resultado["contacto"] = datos_contacto_para_sheet(estado)
            return True

    if "nombre" in faltantes:
        estado["nombre_solicitado"] = True

    if not mensaje_tiene_datos_de_cita(mensaje) and not es_afirmacion(mensaje):
        estado["contador_ambiguedad"] = int(estado.get("contador_ambiguedad", 0)) + 1
    else:
        estado["contador_ambiguedad"] = 0

    if estado.get("contador_ambiguedad", 0) >= 3:
        resultado["respuesta"] = pedir_aclaracion_suave(estado.get("etapa"))
        registrar_sin_cierre_resultado(
            resultado,
            telefono,
            estado,
            mensaje,
            "Cliente no completó datos; revisar manualmente el último mensaje y retomar con llamada o mensaje personalizado."
        )
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return True

    resultado["respuesta"] = pedir_datos_faltantes(faltantes, estado.get("tipo_atencion") or "visita")
    resultado["contacto"] = datos_contacto_para_sheet(estado)
    return True


def manejar_conversacion(telefono, mensaje, estado_actual=None):
    estado = deepcopy(estado_actual) if estado_actual else crear_estado_inicial()
    if not isinstance(estado, dict):
        estado = crear_estado_inicial()

    etapa_anterior = estado.get("etapa", "inicio")
    intencion = detectar_intencion(mensaje, etapa_anterior)

    # Si el cliente expresa molestia/rechazo fuerte, no extraemos nombre, ubicación ni datos de cita
    # de ese mensaje. Esto evita que insultos o frases como "no me vuelvas a escribir" activen el flujo.
    if intencion in ["no_interesado", "desconfianza_o_molestia"]:
        resultado = preparar_resultado(estado)
        estado["etapa"] = "cerrado_molestia" if intencion == "desconfianza_o_molestia" else "cerrado_no_interesado"
        if etapa_anterior in ["cerrado_no_interesado", "cerrado_molestia"]:
            resultado["respuesta"] = "Entendido. No le volveremos a escribir por este medio."
        elif intencion == "desconfianza_o_molestia":
            estado["pdf_bloqueado_por_desconfianza"] = True
            resultado["respuesta"] = molestia_o_desconfianza()
            registrar_sin_cierre_resultado(resultado, telefono, estado, mensaje, "No insistir; revisar manualmente si conviene contacto futuro.")
        else:
            resultado["respuesta"] = no_interesado()
            registrar_sin_cierre_resultado(resultado, telefono, estado, mensaje, "No insistir; dejar como contacto frío.")
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    actualizar_estado_con_mensaje(estado, mensaje)

    # Evita que nombres de finca/persona con la palabra "precio" bloqueen el cierre
    # cuando el sistema ya está esperando datos de cita.
    if intencion == "pregunta_precio" and etapa_anterior in ["esperando_datos_cita", "esperando_actualizacion_cita"]:
        if mensaje_tiene_datos_de_cita(mensaje):
            intencion = "consulta"

    resultado = preparar_resultado(estado)

    # Si el contacto ya quedó cerrado por molestia o no interés, no reiniciamos ni pedimos datos.
    if etapa_anterior in ["cerrado_no_interesado", "cerrado_molestia"] and intencion in ["no_interesado", "desconfianza_o_molestia"]:
        resultado["respuesta"] = "Entendido. No le volveremos a escribir por este medio."
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    # Pregunta directa por servicios: aquí sí se explica y se envía el PDF una sola vez.
    if intencion == "pregunta_servicios":
        estado["etapa"] = "orientacion_previa"
        estado["orientacion_dada"] = True
        resultado["respuesta"] = responder_pregunta_servicios(estado.get("actividad"), estado.get("motivo"))
        _programar_envio_pdf_servicios(resultado, estado, "solicitado_explicitamente")
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    # Corrección explícita de actividad, por ejemplo: "tengo camaronera, no industria".
    if intencion == "correccion_actividad":
        if estado.get("actividad"):
            if estado.get("motivo"):
                estado["etapa"] = "esperando_preferencia_atencion"
                estado["orientacion_dada"] = True
                resultado["respuesta"] = (
                    "Tiene razón, disculpe la confusión. Ya lo corrijo: se trata de una "
                    + ("camaronera" if estado.get("actividad") == "camaronera" else "actividad productiva")
                    + ". "
                    + pedir_preferencia_atencion(estado.get("actividad"), estado.get("motivo"))
                )
            else:
                estado["etapa"] = "esperando_motivo"
                resultado["respuesta"] = (
                    "Tiene razón, disculpe la confusión. Ya lo corrijo. "
                    + pedir_motivo(estado.get("actividad"))
                )
        else:
            estado["etapa"] = "esperando_actividad"
            resultado["respuesta"] = "Disculpe la confusión. Para corregirlo bien, ¿me confirma nuevamente qué actividad maneja?"
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    # 1. Casos sensibles: desconfianza, molestia o no interés.
    if intencion == "desconfianza_o_molestia":
        estado["etapa"] = "cerrado_molestia"
        estado["pdf_bloqueado_por_desconfianza"] = True
        resultado["respuesta"] = molestia_o_desconfianza()
        registrar_sin_cierre_resultado(resultado, telefono, estado, mensaje, "No insistir; revisar manualmente si conviene contacto futuro.")
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    if intencion == "no_interesado":
        estado["etapa"] = "cerrado_no_interesado"
        resultado["respuesta"] = no_interesado()
        registrar_sin_cierre_resultado(resultado, telefono, estado, mensaje, "No insistir; dejar como contacto frío.")
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    # 1.1 Respuestas derivadas de campaña automática de WhatsApp.
    # No se agenda directo: primero se orienta y se pide actividad/motivo.
    if _manejar_respuesta_campana(intencion, estado, resultado):
        return resultado

    # Si el cliente repite la actividad cuando ya estamos esperando modalidad, no repetimos el bloque completo.
    if etapa_anterior == "esperando_preferencia_atencion" and estado.get("actividad") and estado.get("motivo") and intencion == "consulta" and _mensaje_declara_actividad(mensaje):
        estado["etapa"] = "esperando_preferencia_atencion"
        resultado["respuesta"] = (
            "Correcto, lo tengo registrado como "
            + ("camaronera" if estado.get("actividad") == "camaronera" else "actividad productiva")
            + ". Para avanzar, podemos revisarlo por llamada breve o mediante visita técnica. ¿Qué le conviene más?"
        )
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    # 2. Si ya hay cita agendada, cambiar a modo coordinación.
    if etapa_anterior in ["cita_agendada", "cita_actualizada"]:
        if intencion == "despedida":
            if estado.get("despedida_respondida"):
                resultado["respuesta"] = None
            else:
                resultado["respuesta"] = despedida_silenciosa()
                estado["despedida_respondida"] = True
            resultado["contacto"] = datos_contacto_para_sheet(estado)
            return resultado

        if intencion == "nueva_finca":
            limpiar_campos_cita(estado)
            # Reprocesamos el mismo mensaje porque a veces el cliente ya dice la nueva actividad:
            # "tengo otra camaronera que quiero revisar". Así no le pedimos información que ya dio.
            actualizar_estado_con_mensaje(estado, mensaje)

            if estado.get("actividad"):
                if estado.get("motivo"):
                    estado["etapa"] = "orientacion_previa"
                    estado["orientacion_dada"] = True
                    resultado["respuesta"] = proponer_visita_o_llamada(estado.get("actividad"), estado.get("motivo"))
                else:
                    estado["etapa"] = "esperando_motivo"
                    resultado["respuesta"] = (
                        "Claro, podemos revisar esa actividad como una coordinación adicional. "
                        + pedir_motivo(estado.get("actividad"))
                    )
            else:
                estado["etapa"] = "esperando_actividad"
                resultado["respuesta"] = nueva_finca()

            resultado["contacto"] = datos_contacto_para_sheet(estado)
            return resultado

        if intencion == "cambio_cita":
            if mensaje_tiene_datos_de_cita(mensaje):
                datos_actualizados = armar_datos_cita(telefono, estado, mensaje)
                estado["etapa"] = "cita_actualizada"
                resultado["respuesta"] = cita_actualizada(datos_actualizados)
                resultado["actualizar_cita"] = datos_actualizados
                resultado["notificar_cita_actualizada"] = datos_actualizados
                resultado["contacto"] = datos_contacto_para_sheet(estado)
                return resultado

            estado["etapa"] = "esperando_actualizacion_cita"
            resultado["respuesta"] = cambio_cita()
            resultado["contacto"] = datos_contacto_para_sheet(estado)
            return resultado

        if intencion == "cancelacion":
            estado["etapa"] = "cita_cancelada"
            datos_cancelacion = armar_datos_cita(telefono, estado, mensaje)
            datos_cancelacion["Estado"] = "Cancelada"
            datos_cancelacion["Mensaje_Original"] = mensaje
            resultado["respuesta"] = cancelacion()
            resultado["cancelar_cita"] = datos_cancelacion
            resultado["notificar_cancelacion"] = datos_cancelacion
            resultado["contacto"] = datos_contacto_para_sheet(estado)
            return resultado

        resultado["respuesta"] = consulta_post_cita()
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    # 3. Actualización de cita ya solicitada.
    if etapa_anterior == "esperando_actualizacion_cita":
        datos_actualizados = armar_datos_cita(telefono, estado, mensaje)
        estado["etapa"] = "cita_actualizada"
        resultado["respuesta"] = cita_actualizada(datos_actualizados)
        resultado["actualizar_cita"] = datos_actualizados
        resultado["notificar_cita_actualizada"] = datos_actualizados
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    # 4. Pregunta por precio: informar sin cerrar en seco.
    if intencion == "pregunta_precio":
        estado["etapa"] = "precio_sin_cierre"
        estado["orientacion_dada"] = True
        if not estado.get("motivo"):
            estado["motivo"] = "precio"

        # Si aún no sabemos la actividad, no conviene ofrecer llamada/visita de una vez.
        # Primero se ubica el caso, especialmente cuando el mensaje viene como respuesta corta de campaña.
        if not estado.get("actividad"):
            _marcar_origen_campana(estado)
            resultado["respuesta"] = responder_campana_precio(None)
        elif estado.get("origen") == "campana_whatsapp":
            resultado["respuesta"] = responder_campana_precio(estado.get("actividad"))
        else:
            resultado["respuesta"] = responder_precio_sin_perder_cierre(estado.get("actividad"))
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    # 5. Pregunta general de información.
    if intencion == "pide_informacion" and (estado.get("actividad") or estado.get("motivo")):
        estado["etapa"] = "orientacion_previa"

        # Si ya dimos la explicación general, no repetimos el mismo bloque.
        # Respondemos puntual y avanzamos a preferencia de llamada/visita.
        if estado.get("orientacion_dada"):
            resultado["respuesta"] = responder_revision_documental_puntual(estado.get("actividad"), estado.get("motivo"))
        else:
            estado["orientacion_dada"] = True
            resultado["respuesta"] = responder_informacion_general(estado.get("actividad"), estado.get("motivo"))
            _programar_envio_pdf_servicios(resultado, estado, "informacion")

        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    # 6. Si pide llamada o visita directamente.
    if intencion in ["solicita_visita", "solicita_llamada"]:
        estado["tipo_atencion"] = "llamada" if intencion == "solicita_llamada" else "visita"
        estado["etapa"] = "esperando_datos_cita"
        estado["mensaje_original_cita"] = estado.get("mensaje_original_cita") or mensaje

        if _manejar_faltantes(telefono, estado, mensaje, resultado):
            return resultado

    # 7. Si responde afirmativamente después de orientación, pedir modalidad antes de datos.
    if intencion == "afirmacion" and etapa_anterior in ["orientacion_previa", "propuesta_atencion", "precio_sin_cierre", "esperando_preferencia_atencion"]:
        estado["etapa"] = "esperando_preferencia_atencion"
        resultado["respuesta"] = pedir_preferencia_atencion(estado.get("actividad"), estado.get("motivo"))
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    # 8. Flujo principal: actividad -> motivo -> orientación -> modalidad -> datos.
    if not estado.get("actividad"):
        estado["etapa"] = "esperando_actividad"
        if etapa_anterior == "esperando_actividad" and intencion == "consulta":
            estado["contador_ambiguedad"] = int(estado.get("contador_ambiguedad", 0)) + 1
        else:
            estado["contador_ambiguedad"] = 0

        if estado.get("contador_ambiguedad", 0) >= 3:
            resultado["respuesta"] = mensaje_ambiguedad_final()
            registrar_sin_cierre_resultado(
                resultado,
                telefono,
                estado,
                mensaje,
                "Cliente no indicó actividad; revisar manualmente y retomar con mensaje personalizado."
            )
            resultado["contacto"] = datos_contacto_para_sheet(estado)
            return resultado

        if intencion == "pide_informacion":
            resultado["respuesta"] = responder_informacion_general()
            _programar_envio_pdf_servicios(resultado, estado, "informacion")
        elif estado.get("motivo"):
            # Ya entendimos la necesidad, pero falta clasificar actividad.
            # Esto evita repetir el saludo genérico varias veces.
            resultado["respuesta"] = (
                "Hola, le saluda el equipo técnico de DALGORO S.A.S. Entiendo el motivo del contacto. "
                "Para orientarle correctamente y no asumir mal, me falta confirmar la actividad que maneja: "
                "bananera, camaronera, minería, cacaotera, cultivo de ciclo corto, granja porcina, "
                "granja avícola, hotel, industria u otra actividad productiva."
            )
        else:
            resultado["respuesta"] = bienvenida(estado.get("origen"))
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    if not estado.get("motivo"):
        estado["etapa"] = "esperando_motivo"
        if etapa_anterior == "esperando_motivo" and intencion == "consulta":
            estado["contador_ambiguedad"] = int(estado.get("contador_ambiguedad", 0)) + 1
        else:
            estado["contador_ambiguedad"] = 0

        if estado.get("contador_ambiguedad", 0) >= 3:
            resultado["respuesta"] = pedir_aclaracion_suave("esperando_motivo")
            registrar_sin_cierre_resultado(
                resultado,
                telefono,
                estado,
                mensaje,
                "Cliente indicó actividad pero no motivo; revisar manualmente y retomar con diagnóstico rápido."
            )
            resultado["contacto"] = datos_contacto_para_sheet(estado)
            return resultado

        if etapa_anterior == "inicio":
            resultado["respuesta"] = "Hola, le saluda el equipo técnico de DALGORO S.A.S. " + pedir_motivo(estado.get("actividad"))
        else:
            resultado["respuesta"] = pedir_motivo(estado.get("actividad"))
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    if not estado.get("orientacion_dada") and not estado.get("tipo_atencion"):
        estado["etapa"] = "orientacion_previa"
        estado["orientacion_dada"] = True
        resultado["respuesta"] = proponer_visita_o_llamada(estado.get("actividad"), estado.get("motivo"))
        resultado["contacto"] = datos_contacto_para_sheet(estado)
        return resultado

    if not estado.get("tipo_atencion"):
        # Si ya mandó datos de cita, inferimos visita para no hacerlo repetir.
        if mensaje_tiene_datos_de_cita(mensaje):
            estado["tipo_atencion"] = "visita"
        else:
            estado["etapa"] = "esperando_preferencia_atencion"
            resultado["respuesta"] = pedir_preferencia_atencion(estado.get("actividad"), estado.get("motivo"))
            resultado["contacto"] = datos_contacto_para_sheet(estado)
            return resultado

    estado["etapa"] = "esperando_datos_cita"
    estado["mensaje_original_cita"] = estado.get("mensaje_original_cita") or mensaje

    if _manejar_faltantes(telefono, estado, mensaje, resultado):
        return resultado

    datos_cita = armar_datos_cita(telefono, estado, mensaje)
    estado["etapa"] = "cita_agendada"

    resultado["respuesta"] = cita_registrada(datos_cita)
    resultado["registrar_cita"] = datos_cita
    resultado["notificar_cita"] = datos_cita
    resultado["contacto"] = datos_contacto_para_sheet(estado)

    return resultado
