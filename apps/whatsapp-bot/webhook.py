from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime, timedelta
import json
import logging

from config import Config
from google_sheets_utils import sheets_manager
from green_api_client import enviar_mensaje_whatsapp, limpiar_numero, enviar_pdf_servicios
from agrupador_mensajes import agregar_mensaje
from gestor_conversacion import manejar_conversacion
from estado_storage import obtener_estado, guardar_estado
from notificaciones import (
    notificar_cita,
    notificar_cita_actualizada,
    notificar_cancelacion,
    notificar_sin_cierre,
    notificar_llamada,
    notificar_archivo_o_audio,
)
from respuestas_comerciales import llamada_recibida, archivo_o_audio_recibido

app = Flask(__name__)
logger = logging.getLogger(__name__)

if not Config.GREEN_API_INSTANCE or not Config.GREEN_API_TOKEN:
    raise EnvironmentError("❌ GREEN_API_INSTANCE o GREEN_API_TOKEN no están definidos en variables de entorno.")


class RateLimiter:
    def __init__(self):
        self.message_counts = {}
        self.response_counts = {}
        self.processed_messages = {}

    def can_process_message(self, telefono):
        minuto = datetime.now().replace(second=0, microsecond=0)
        clave = f"{telefono}_{minuto}"
        cuenta = self.message_counts.get(clave, 0)

        if cuenta >= Config.MAX_MESSAGES_PER_MINUTE:
            return False

        self.message_counts[clave] = cuenta + 1
        return True

    def can_send_response(self):
        hora = datetime.now().replace(minute=0, second=0, microsecond=0)
        cuenta = self.response_counts.get(hora, 0)

        if cuenta >= Config.MAX_RESPONSES_PER_HOUR:
            return False

        self.response_counts[hora] = cuenta + 1
        return True

    def is_duplicate(self, message_id):
        if not message_id:
            return False

        ahora = datetime.now()
        vencidos = [k for k, v in self.processed_messages.items() if ahora - v > timedelta(hours=2)]
        for k in vencidos:
            self.processed_messages.pop(k, None)

        if message_id in self.processed_messages:
            return True

        self.processed_messages[message_id] = ahora
        return False


rate_limiter = RateLimiter()


def extraer_texto_telefono_tipo(data):
    """
    Extrae teléfono, texto y tipo de contenido desde eventos comunes de Green API.
    """
    sender = data.get("senderData", {})
    telefono = limpiar_numero(sender.get("chatId", ""))

    message_data = data.get("messageData", {})
    tipo = message_data.get("typeMessage", "")

    if tipo == "textMessage":
        texto = message_data.get("textMessageData", {}).get("textMessage", "")
        return telefono, texto, tipo

    if tipo == "extendedTextMessage":
        texto = message_data.get("extendedTextMessageData", {}).get("text", "")
        return telefono, texto, tipo

    if tipo == "locationMessage":
        loc = message_data.get("locationMessageData", {})
        lat = loc.get("latitude", "")
        lng = loc.get("longitude", "")
        direccion = loc.get("address", "") or loc.get("nameLocation", "")
        texto = f"Ubicación enviada: {direccion}. Maps: https://maps.google.com/?q={lat},{lng}"
        return telefono, texto, tipo

    if tipo in ["audioMessage", "imageMessage", "videoMessage", "documentMessage"]:
        return telefono, "", tipo

    return telefono, "", tipo


def enviar_y_loguear(telefono, mensaje):
    if not mensaje:
        return False

    if not rate_limiter.can_send_response():
        print("⚠️ Límite de respuestas por hora alcanzado.")
        return False

    enviado = enviar_mensaje_whatsapp(telefono, mensaje)
    if enviado:
        sheets_manager.log_message(telefono, mensaje, "Enviado", "WhatsApp")

    return enviado



def enviar_pdf_y_loguear(telefono, caption):
    """Envía el PDF institucional de servicios y registra el evento en Google Sheets."""
    if not rate_limiter.can_send_response():
        print("⚠️ Límite de respuestas por hora alcanzado antes de enviar PDF.")
        return False

    enviado = enviar_pdf_servicios(telefono, caption or "")
    if enviado:
        sheets_manager.log_message(telefono, f"[PDF enviado] {Config.NOMBRE_PDF_SERVICIOS}", "Enviado", "WhatsApp")
    return enviado


def procesar_mensaje_agrupado(telefono, mensaje):
    """
    Se ejecuta después de agrupar mensajes consecutivos del cliente.
    """
    print(f"🧩 Mensaje agrupado de {telefono}: {mensaje}")

    estado_actual = obtener_estado(telefono)
    resultado = manejar_conversacion(telefono, mensaje, estado_actual)
    nuevo_estado = resultado.get("estado")

    if nuevo_estado:
        guardar_estado(telefono, nuevo_estado)

    sheets_manager.update_contact(telefono, resultado.get("contacto"))

    if resultado.get("registrar_cita"):
        id_cita = sheets_manager.registrar_cita(resultado["registrar_cita"])
        if id_cita:
            nuevo_estado["id_cita_activa"] = id_cita
            guardar_estado(telefono, nuevo_estado)
            resultado["registrar_cita"]["ID_Cita"] = id_cita
            resultado["notificar_cita"]["ID_Cita"] = id_cita

    if resultado.get("actualizar_cita"):
        sheets_manager.actualizar_ultima_cita(resultado["actualizar_cita"])

    if resultado.get("cancelar_cita"):
        sheets_manager.cancelar_ultima_cita(resultado["cancelar_cita"])

    if resultado.get("registrar_sin_cierre"):
        sheets_manager.registrar_sin_cierre(resultado["registrar_sin_cierre"])

    respuesta = resultado.get("respuesta")
    if respuesta:
        enviar_y_loguear(telefono, respuesta)

    pdf_info = resultado.get("enviar_pdf_servicios")
    if pdf_info:
        enviar_pdf_y_loguear(telefono, pdf_info.get("caption", ""))

    if resultado.get("notificar_cita"):
        notificar_cita(resultado["notificar_cita"])

    if resultado.get("notificar_cita_actualizada"):
        notificar_cita_actualizada(resultado["notificar_cita_actualizada"])

    if resultado.get("notificar_cancelacion"):
        notificar_cancelacion(resultado["notificar_cancelacion"])

    if resultado.get("notificar_sin_cierre"):
        notificar_sin_cierre(resultado["notificar_sin_cierre"])


@app.route("/", methods=["GET"])
def home():
    return "DALGORO bot activo", 200




@app.route("/documentos/<path:filename>", methods=["GET"])
def servir_documento(filename):
    """
    Publica documentos institucionales para que Green API pueda enviarlos por URL.
    """
    return send_from_directory(Config.DOCUMENTOS_DIR, filename, as_attachment=True)


@app.route("/webhook", methods=["POST"])
def recibir():
    if not request.is_json:
        return jsonify({"error": "Formato inválido"}), 400

    data = request.json
    print("📥 JSON recibido:\n", json.dumps(data, indent=2, ensure_ascii=False))

    tipo_webhook = data.get("typeWebhook", "")
    message_id = data.get("idMessage")

    if rate_limiter.is_duplicate(message_id):
        return jsonify({"status": "duplicado_ignorado"}), 200

    # Evento de llamada: el nombre exacto puede variar según configuración de Green API.
    if "call" in tipo_webhook.lower():
        telefono = limpiar_numero(data.get("from", "") or data.get("senderData", {}).get("chatId", ""))
        if telefono:
            sheets_manager.log_message(telefono, "Intento de llamada por WhatsApp", "Recibido", "WhatsApp")
            enviar_y_loguear(telefono, llamada_recibida())
            notificar_llamada(telefono)
        return jsonify({"status": "llamada_procesada"}), 200

    if tipo_webhook != "incomingMessageReceived":
        return jsonify({"status": "ignorado"}), 200

    telefono, mensaje, tipo_contenido = extraer_texto_telefono_tipo(data)

    if not telefono:
        print("❌ Teléfono incompleto")
        return jsonify({"error": "Teléfono incompleto"}), 400

    if not rate_limiter.can_process_message(telefono):
        print(f"⚠️ Límite de mensajes por minuto alcanzado para {telefono}")
        return jsonify({"status": "limite_mensajes"}), 200

    if tipo_contenido in ["audioMessage", "imageMessage", "videoMessage", "documentMessage"]:
        sheets_manager.update_contact(telefono)
        sheets_manager.log_message(telefono, f"Contenido recibido: {tipo_contenido}", "Recibido", "WhatsApp")
        enviar_y_loguear(telefono, archivo_o_audio_recibido())
        notificar_archivo_o_audio(telefono, tipo_contenido)
        return jsonify({"status": "contenido_no_texto_procesado"}), 200

    if not mensaje:
        print("❌ Mensaje vacío:", tipo_contenido)
        return jsonify({"error": "Mensaje vacío"}), 400

    sheets_manager.update_contact(telefono)
    sheets_manager.log_message(telefono, mensaje, "Recibido", "WhatsApp")

    # El bot no responde inmediatamente: agrupa mensajes del mismo cliente por unos segundos.
    agregar_mensaje(telefono, mensaje, procesar_mensaje_agrupado)

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(debug=True, port=5000)
