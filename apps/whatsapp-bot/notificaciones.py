from config import Config
from green_api_client import enviar_mensaje_whatsapp


def notificar_darwin(texto: str) -> bool:
    if not Config.ENVIAR_NOTIFICACIONES:
        return False

    if not Config.NUMERO_PERSONAL_DALGORO:
        print("⚠️ NUMERO_PERSONAL_DALGORO no está definido.")
        return False

    return enviar_mensaje_whatsapp(Config.NUMERO_PERSONAL_DALGORO, texto)


def notificar_cita(datos):
    mensaje = (
        "📌 Nueva coordinación registrada - DALGORO\n\n"
        f"Teléfono: {datos.get('Telefono', '')}\n"
        f"Nombre: {datos.get('Nombre', '')}\n"
        f"Origen: {datos.get('Origen', '')}\n"
        f"Actividad: {datos.get('Actividad', '')}\n"
        f"Motivo: {datos.get('Motivo', '')}\n"
        f"Tipo: {datos.get('Tipo_Atencion', '')}\n"
        f"Finca/Proyecto: {datos.get('Finca_Proyecto', '')}\n"
        f"Ubicación: {datos.get('Ubicacion', '')}\n"
        f"Fecha: {datos.get('Fecha', '')}\n"
        f"Hora: {datos.get('Hora', '')}\n\n"
        f"Mensaje original: {datos.get('Mensaje_Original', '')}"
    )
    return notificar_darwin(mensaje)


def notificar_cita_actualizada(datos):
    mensaje = (
        "🔁 Coordinación actualizada - DALGORO\n\n"
        f"Teléfono: {datos.get('Telefono', '')}\n"
        f"Nombre: {datos.get('Nombre', '')}\n"
        f"Tipo: {datos.get('Tipo_Atencion', '')}\n"
        f"Finca/Proyecto: {datos.get('Finca_Proyecto', '')}\n"
        f"Ubicación: {datos.get('Ubicacion', '')}\n"
        f"Fecha: {datos.get('Fecha', '')}\n"
        f"Hora: {datos.get('Hora', '')}\n\n"
        f"Mensaje original/ajuste: {datos.get('Mensaje_Original', '')}"
    )
    return notificar_darwin(mensaje)


def notificar_cancelacion(datos):
    mensaje = (
        "❌ Coordinación cancelada - DALGORO\n\n"
        f"Teléfono: {datos.get('Telefono', '')}\n"
        f"Nombre: {datos.get('Nombre', '')}\n"
        f"Tipo: {datos.get('Tipo_Atencion', '')}\n"
        f"Fecha: {datos.get('Fecha', '')}\n"
        f"Hora: {datos.get('Hora', '')}\n"
        f"Ubicación: {datos.get('Ubicacion', '')}"
    )
    return notificar_darwin(mensaje)


def notificar_sin_cierre(datos):
    mensaje = (
        "⚠️ Conversación sin cierre - posible seguimiento\n\n"
        f"Teléfono: {datos.get('Telefono', '')}\n"
        f"Nombre: {datos.get('Nombre', '')}\n"
        f"Origen: {datos.get('Origen', '')}\n"
        f"Actividad: {datos.get('Actividad', '')}\n"
        f"Motivo: {datos.get('Motivo', '')}\n"
        f"Etapa: {datos.get('Ultima_Etapa', '')}\n"
        f"Último mensaje: {datos.get('Ultimo_Mensaje', '')}\n"
        f"Acción sugerida: {datos.get('Accion_Sugerida', '')}"
    )
    return notificar_darwin(mensaje)


def notificar_llamada(telefono):
    return notificar_darwin(
        "📞 Cliente intentó llamar por WhatsApp\n\n"
        f"Teléfono: {telefono}\n"
        "Acción sugerida: devolver llamada personalmente si corresponde."
    )


def notificar_archivo_o_audio(telefono, tipo):
    return notificar_darwin(
        "📎 Cliente envió archivo/audio - DALGORO\n\n"
        f"Teléfono: {telefono}\n"
        f"Tipo recibido: {tipo}\n"
        "Acción sugerida: revisar si conviene llamar personalmente."
    )
