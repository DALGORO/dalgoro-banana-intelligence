# -*- coding: utf-8 -*-
"""
AUDITOR V3 - Calidad de respuestas del bot DALGORO

Objetivo:
- No solo probar si el bot "corre".
- Detectar posibles fallas comerciales o conversacionales antes de producción.

Uso:
1. Copia este archivo en la carpeta principal del bot.
2. Asegúrate de tener también uno de estos archivos:
   - escenarios_simulacion_300_dalgoro.py
   - escenarios_simulacion_300_dalgoro_CORREGIDO.py
   - escenarios_simulacion_300_dalgoro.json
3. Ejecuta:
   python auditor_calidad_respuestas_v2.py

El auditor revisa:
- respuestas vacías
- errores críticos
- actividad no reconocida
- motivo no reconocido
- nombre pedido repetidamente
- cierre demasiado temprano
- confirmación de cita incompleta
- respuestas demasiado largas
- demasiadas preguntas en un solo mensaje
- respuesta repetida
- envío duplicado de PDF
- envío de PDF en rechazo/desconfianza
- frases confusas o antiguas
"""

import json
import re
import unicodedata
from pathlib import Path
from collections import defaultdict, Counter


# ======================================================
# CARGA DE ESCENARIOS
# ======================================================

def cargar_escenarios():
    posibles_json = [
        Path("escenarios_simulacion_300_dalgoro.json"),
        Path("dalgoro_escenarios_300/escenarios_simulacion_300_dalgoro.json"),
    ]

    for ruta in posibles_json:
        if ruta.exists():
            return json.loads(ruta.read_text(encoding="utf-8"))

    posibles_py = [
        "escenarios_simulacion_300_dalgoro",
        "escenarios_simulacion_300_dalgoro_CORREGIDO",
    ]

    for modulo in posibles_py:
        try:
            m = __import__(modulo)
            if hasattr(m, "ESCENARIOS"):
                return m.ESCENARIOS
        except Exception:
            pass

    raise FileNotFoundError(
        "No encontré los escenarios. Coloca en esta carpeta uno de estos archivos:\n"
        "- escenarios_simulacion_300_dalgoro.json\n"
        "- escenarios_simulacion_300_dalgoro.py\n"
        "- escenarios_simulacion_300_dalgoro_CORREGIDO.py"
    )


# ======================================================
# UTILIDADES
# ======================================================

def normalizar(texto):
    texto = texto or ""
    texto = texto.lower().strip()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def contiene(texto, frases):
    t = normalizar(texto)
    return any(normalizar(f) in t for f in frases)


def contar_preguntas(texto):
    return (texto or "").count("?") + (texto or "").count("¿")


def parece_pedir_nombre(respuesta):
    return contiene(respuesta, [
        "nombre",
        "a nombre de quien",
        "a nombre de quién",
        "con que nombre",
        "con qué nombre",
        "a nombre de quien queda",
        "a nombre de quién queda",
    ])


def parece_pedir_dia_hora(respuesta):
    return contiene(respuesta, [
        "dia y hora",
        "día y hora",
        "fecha y hora",
        "dia, hora",
        "día, hora",
        "que dia",
        "qué día",
        "hora aproximada",
        "para dejar coordinada",
        "para dejarlo bien registrado",
    ])


def parece_confirmacion_cita(respuesta):
    return contiene(respuesta, [
        "queda registrada la llamada",
        "queda registrada la visita",
        "queda registrado",
        "queda registrada",
        "el ing. darwin",
        "se contactara directamente",
        "se contactará directamente",
    ])


def extraer_flags_pdf(resultado):
    """
    Compatible con varias formas posibles del resultado:
    - enviar_pdf_servicios
    - enviar_pdf
    - pdf_servicios
    - archivo_pdf
    """
    if not isinstance(resultado, dict):
        return False

    claves = [
        "enviar_pdf_servicios",
        "enviar_pdf",
        "pdf_servicios",
        "archivo_pdf",
        "documento_pdf",
    ]

    for clave in claves:
        if resultado.get(clave):
            return True

    return False


def obtener_estado(resultado, estado_anterior):
    if isinstance(resultado, dict):
        return resultado.get("estado", estado_anterior)
    return estado_anterior


def obtener_respuesta(resultado):
    if isinstance(resultado, dict):
        return resultado.get("respuesta") or ""
    return ""


def obtener_actividad_estado(estado):
    if isinstance(estado, dict):
        return estado.get("actividad")
    return None


def obtener_motivo_estado(estado):
    if isinstance(estado, dict):
        return estado.get("motivo")
    return None


def obtener_nombre_estado(estado):
    if isinstance(estado, dict):
        return estado.get("nombre")
    return None


def obtener_tipo_atencion_estado(estado):
    if isinstance(estado, dict):
        return estado.get("tipo_atencion")
    return None


def obtener_fecha_estado(estado):
    if isinstance(estado, dict):
        return estado.get("fecha")
    return None


def obtener_hora_estado(estado):
    if isinstance(estado, dict):
        return estado.get("hora")
    return None


def obtener_ubicacion_estado(estado):
    if isinstance(estado, dict):
        return estado.get("ubicacion")
    return None



def es_post_cita_con_nueva_actividad(escenario):
    """
    Evita falsos positivos del auditor cuando el cliente, después de una cita,
    dice que tiene otra finca/camaronera/actividad. En esos casos el bot puede
    limpiar campos para iniciar una coordinación adicional, y eso no debe contarse
    como pérdida de actividad/motivo de la cita anterior.
    """
    if escenario.get("categoria_prueba") != "post_cierre":
        return False

    mensajes = " ".join(escenario.get("mensajes_cliente", []))
    return contiene(mensajes, [
        "otra finca", "otra camaronera", "otra actividad", "tambien tengo",
        "también tengo", "tengo otra", "otra propiedad", "segunda finca",
        "otro predio", "otra granja", "otra planta"
    ])

# ======================================================
# AUDITOR
# ======================================================

def auditar():
    escenarios = cargar_escenarios()

    try:
        from gestor_conversacion import manejar_conversacion
    except Exception as e:
        print("ERROR: No pude importar gestor_conversacion.manejar_conversacion")
        print("Detalle:", e)
        return

    alertas = []
    conteo_alertas = Counter()
    respuestas_largas = []
    ejemplos_por_alerta = defaultdict(list)

    total = len(escenarios)
    errores_criticos = 0
    eventos_sin_respuesta = 0
    conversaciones_con_cierre = 0
    pdf_enviados = 0

    for idx, escenario in enumerate(escenarios, start=1):
        telefono = "593997" + str(idx).zfill(6)
        estado = None
        respuestas = []
        pdf_count = 0
        hubo_cierre = False
        respuesta_anterior_norm = None

        actividad_esperada = escenario.get("actividad_esperada")
        motivo_esperado = escenario.get("motivo_esperado")
        resultado_esperado = escenario.get("resultado_esperado", "")
        categoria = escenario.get("categoria_prueba", "")

        for paso, mensaje in enumerate(escenario.get("mensajes_cliente", []), start=1):
            try:
                try:
                    resultado = manejar_conversacion(
                        telefono=telefono,
                        mensaje=mensaje,
                        estado_actual=estado
                    )
                except TypeError:
                    resultado = manejar_conversacion(telefono, mensaje)

            except Exception as e:
                errores_criticos += 1
                alerta = {
                    "tipo": "error_critico",
                    "id": escenario.get("id"),
                    "paso": paso,
                    "mensaje": mensaje,
                    "error": str(e),
                    "categoria": categoria,
                    "resultado_esperado": resultado_esperado,
                }
                alertas.append(alerta)
                conteo_alertas["error_critico"] += 1
                ejemplos_por_alerta["error_critico"].append(alerta)
                continue

            if not isinstance(resultado, dict):
                alerta = {
                    "tipo": "resultado_no_dict",
                    "id": escenario.get("id"),
                    "paso": paso,
                    "mensaje": mensaje,
                    "resultado": str(resultado),
                    "categoria": categoria,
                }
                alertas.append(alerta)
                conteo_alertas["resultado_no_dict"] += 1
                ejemplos_por_alerta["resultado_no_dict"].append(alerta)
                continue

            estado = obtener_estado(resultado, estado)
            respuesta = obtener_respuesta(resultado)
            respuestas.append(respuesta)

            if extraer_flags_pdf(resultado):
                pdf_count += 1
                pdf_enviados += 1

            if resultado.get("registrar_cita") or resultado.get("actualizar_cita") or resultado.get("cancelar_cita"):
                hubo_cierre = True

            # ALERTA: respuesta vacía
            if not respuesta:
                eventos_sin_respuesta += 1
                alerta = {
                    "tipo": "respuesta_vacia",
                    "id": escenario.get("id"),
                    "paso": paso,
                    "mensaje": mensaje,
                    "categoria": categoria,
                }
                alertas.append(alerta)
                conteo_alertas["respuesta_vacia"] += 1
                ejemplos_por_alerta["respuesta_vacia"].append(alerta)

            # ALERTA: respuesta demasiado larga
            if len(respuesta) > 850:
                alerta = {
                    "tipo": "respuesta_muy_larga",
                    "id": escenario.get("id"),
                    "paso": paso,
                    "largo": len(respuesta),
                    "mensaje": mensaje,
                    "respuesta": respuesta[:500],
                    "categoria": categoria,
                }
                alertas.append(alerta)
                conteo_alertas["respuesta_muy_larga"] += 1
                ejemplos_por_alerta["respuesta_muy_larga"].append(alerta)
                respuestas_largas.append(alerta)

            # ALERTA: demasiadas preguntas en un mensaje
            if contar_preguntas(respuesta) > 2:
                alerta = {
                    "tipo": "demasiadas_preguntas",
                    "id": escenario.get("id"),
                    "paso": paso,
                    "preguntas": contar_preguntas(respuesta),
                    "mensaje": mensaje,
                    "respuesta": respuesta,
                    "categoria": categoria,
                }
                alertas.append(alerta)
                conteo_alertas["demasiadas_preguntas"] += 1
                ejemplos_por_alerta["demasiadas_preguntas"].append(alerta)

            # ALERTA: pidió nombre cuando ya existe nombre en estado
            if parece_pedir_nombre(respuesta) and obtener_nombre_estado(estado):
                alerta = {
                    "tipo": "pidio_nombre_repetido",
                    "id": escenario.get("id"),
                    "paso": paso,
                    "nombre_estado": obtener_nombre_estado(estado),
                    "mensaje": mensaje,
                    "respuesta": respuesta,
                    "categoria": categoria,
                }
                alertas.append(alerta)
                conteo_alertas["pidio_nombre_repetido"] += 1
                ejemplos_por_alerta["pidio_nombre_repetido"].append(alerta)

            # ALERTA: fue directo a cita demasiado pronto
            if parece_pedir_dia_hora(respuesta):
                if not obtener_actividad_estado(estado) and not obtener_motivo_estado(estado):
                    alerta = {
                        "tipo": "cierre_demasiado_temprano",
                        "id": escenario.get("id"),
                        "paso": paso,
                        "mensaje": mensaje,
                        "respuesta": respuesta,
                        "actividad_estado": obtener_actividad_estado(estado),
                        "motivo_estado": obtener_motivo_estado(estado),
                        "categoria": categoria,
                    }
                    alertas.append(alerta)
                    conteo_alertas["cierre_demasiado_temprano"] += 1
                    ejemplos_por_alerta["cierre_demasiado_temprano"].append(alerta)

            # ALERTA: confirmación literal con comillas
            if respuesta.strip().startswith('"') or respuesta.strip().endswith('"'):
                alerta = {
                    "tipo": "respuesta_con_comillas_literal",
                    "id": escenario.get("id"),
                    "paso": paso,
                    "mensaje": mensaje,
                    "respuesta": respuesta,
                    "categoria": categoria,
                }
                alertas.append(alerta)
                conteo_alertas["respuesta_con_comillas_literal"] += 1
                ejemplos_por_alerta["respuesta_con_comillas_literal"].append(alerta)

            # ALERTA: frase antigua confusa de actividades
            if contiene(respuesta, ["por finca, camaronera", "finca, camaronera, granja"]):
                alerta = {
                    "tipo": "frase_actividades_confusa",
                    "id": escenario.get("id"),
                    "paso": paso,
                    "mensaje": mensaje,
                    "respuesta": respuesta,
                    "categoria": categoria,
                }
                alertas.append(alerta)
                conteo_alertas["frase_actividades_confusa"] += 1
                ejemplos_por_alerta["frase_actividades_confusa"].append(alerta)

            # ALERTA: respuesta repetida consecutiva
            respuesta_norm = normalizar(respuesta)
            if respuesta_norm and respuesta_anterior_norm and respuesta_norm == respuesta_anterior_norm:
                alerta = {
                    "tipo": "respuesta_repetida_consecutiva",
                    "id": escenario.get("id"),
                    "paso": paso,
                    "mensaje": mensaje,
                    "respuesta": respuesta,
                    "categoria": categoria,
                }
                alertas.append(alerta)
                conteo_alertas["respuesta_repetida_consecutiva"] += 1
                ejemplos_por_alerta["respuesta_repetida_consecutiva"].append(alerta)

            if respuesta_norm:
                respuesta_anterior_norm = respuesta_norm

        # ALERTA POST-CONVERSACIÓN: actividad esperada no detectada
        actividad_final = obtener_actividad_estado(estado)
        saltar_post_cita_nueva = es_post_cita_con_nueva_actividad(escenario)
        if not saltar_post_cita_nueva and actividad_esperada and actividad_final and actividad_final != actividad_esperada:
            alerta = {
                "tipo": "actividad_distinta_a_esperada",
                "id": escenario.get("id"),
                "actividad_esperada": actividad_esperada,
                "actividad_final": actividad_final,
                "mensajes": escenario.get("mensajes_cliente", []),
                "categoria": categoria,
            }
            alertas.append(alerta)
            conteo_alertas["actividad_distinta_a_esperada"] += 1
            ejemplos_por_alerta["actividad_distinta_a_esperada"].append(alerta)

        if not saltar_post_cita_nueva and actividad_esperada and not actividad_final:
            alerta = {
                "tipo": "actividad_no_detectada",
                "id": escenario.get("id"),
                "actividad_esperada": actividad_esperada,
                "mensajes": escenario.get("mensajes_cliente", []),
                "categoria": categoria,
            }
            alertas.append(alerta)
            conteo_alertas["actividad_no_detectada"] += 1
            ejemplos_por_alerta["actividad_no_detectada"].append(alerta)

        # ALERTA POST-CONVERSACIÓN: motivo esperado no detectado
        motivo_final = obtener_motivo_estado(estado)
        if not saltar_post_cita_nueva and motivo_esperado and motivo_esperado not in ["consultor", "informacion"] and not motivo_final:
            alerta = {
                "tipo": "motivo_no_detectado",
                "id": escenario.get("id"),
                "motivo_esperado": motivo_esperado,
                "mensajes": escenario.get("mensajes_cliente", []),
                "categoria": categoria,
            }
            alertas.append(alerta)
            conteo_alertas["motivo_no_detectado"] += 1
            ejemplos_por_alerta["motivo_no_detectado"].append(alerta)

        # ALERTA: cita/llamada registrada sin fecha u hora
        if hubo_cierre:
            conversaciones_con_cierre += 1
            if (not saltar_post_cita_nueva) and (not obtener_fecha_estado(estado) or not obtener_hora_estado(estado)):
                alerta = {
                    "tipo": "cierre_sin_fecha_u_hora",
                    "id": escenario.get("id"),
                    "fecha": obtener_fecha_estado(estado),
                    "hora": obtener_hora_estado(estado),
                    "estado": estado,
                    "categoria": categoria,
                }
                alertas.append(alerta)
                conteo_alertas["cierre_sin_fecha_u_hora"] += 1
                ejemplos_por_alerta["cierre_sin_fecha_u_hora"].append(alerta)

            if obtener_tipo_atencion_estado(estado) == "visita" and not obtener_ubicacion_estado(estado):
                alerta = {
                    "tipo": "visita_sin_ubicacion",
                    "id": escenario.get("id"),
                    "estado": estado,
                    "categoria": categoria,
                }
                alertas.append(alerta)
                conteo_alertas["visita_sin_ubicacion"] += 1
                ejemplos_por_alerta["visita_sin_ubicacion"].append(alerta)

        # ALERTA: PDF duplicado
        if pdf_count > 1:
            alerta = {
                "tipo": "pdf_enviado_mas_de_una_vez",
                "id": escenario.get("id"),
                "pdf_count": pdf_count,
                "mensajes": escenario.get("mensajes_cliente", []),
                "categoria": categoria,
            }
            alertas.append(alerta)
            conteo_alertas["pdf_enviado_mas_de_una_vez"] += 1
            ejemplos_por_alerta["pdf_enviado_mas_de_una_vez"].append(alerta)

        # ALERTA: PDF enviado en rechazo
        if pdf_count > 0 and resultado_esperado in ["cerrar_sin_insistir", "responder_identidad_y_no_presionar"] and categoria in ["rechazo", "desconfianza"]:
            alerta = {
                "tipo": "pdf_posiblemente_invasivo",
                "id": escenario.get("id"),
                "pdf_count": pdf_count,
                "categoria": categoria,
                "resultado_esperado": resultado_esperado,
                "mensajes": escenario.get("mensajes_cliente", []),
            }
            alertas.append(alerta)
            conteo_alertas["pdf_posiblemente_invasivo"] += 1
            ejemplos_por_alerta["pdf_posiblemente_invasivo"].append(alerta)

    # Guardar reporte JSON
    reporte = {
        "total_escenarios": total,
        "errores_criticos": errores_criticos,
        "eventos_sin_respuesta": eventos_sin_respuesta,
        "conversaciones_con_cierre": conversaciones_con_cierre,
        "pdf_enviados": pdf_enviados,
        "conteo_alertas": dict(conteo_alertas),
        "alertas": alertas,
    }

    Path("reporte_auditoria_v3.json").write_text(
        json.dumps(reporte, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # Salida consola
    print("=" * 74)
    print("AUDITOR V3 - CALIDAD DE RESPUESTAS DALGORO")
    print("=" * 74)
    print("Total escenarios:", total)
    print("Errores críticos:", errores_criticos)
    print("Eventos sin respuesta:", eventos_sin_respuesta)
    print("Conversaciones con cierre/llamada/cambio/cancelación:", conversaciones_con_cierre)
    print("PDF enviados detectados:", pdf_enviados)
    print("Alertas totales:", len(alertas))

    print("\nAlertas por tipo:")
    if conteo_alertas:
        for tipo, cantidad in conteo_alertas.most_common():
            print(f"- {tipo}: {cantidad}")
    else:
        print("- Sin alertas detectadas.")

    if alertas:
        print("\nPrimeros ejemplos por tipo:")
        for tipo, ejemplos in list(ejemplos_por_alerta.items())[:12]:
            print("\n" + "-" * 60)
            print("TIPO:", tipo)
            for ej in ejemplos[:2]:
                print("ID:", ej.get("id"), "| Paso:", ej.get("paso", "-"))
                if ej.get("mensaje"):
                    print("Mensaje:", ej.get("mensaje"))
                if ej.get("respuesta"):
                    print("Respuesta:", str(ej.get("respuesta"))[:400])
                if ej.get("mensajes"):
                    print("Mensajes:", ej.get("mensajes"))

    print("\nReporte completo guardado en:")
    print("reporte_auditoria_v3.json")
    print("\nFin de auditoría.")


if __name__ == "__main__":
    auditar()
