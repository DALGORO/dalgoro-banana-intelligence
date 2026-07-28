import requests
from config import Config


def limpiar_numero(numero: str) -> str:
    """
    Devuelve el número en formato internacional, sin @c.us ni caracteres extraños.
    """
    if not numero:
        return ""

    numero = str(numero).replace("@c.us", "").strip()
    return "".join(c for c in numero if c.isdigit())


def _validar_green_api() -> bool:
    if not Config.GREEN_API_INSTANCE or not Config.GREEN_API_TOKEN:
        print("❌ Faltan GREEN_API_INSTANCE o GREEN_API_TOKEN en variables de entorno.")
        return False
    return True


def enviar_mensaje_whatsapp(numero: str, mensaje: str) -> bool:
    """
    Envía un mensaje de texto por Green API.
    Retorna True si Green API acepta el envío.
    """
    numero = limpiar_numero(numero)

    if not numero or not mensaje:
        print("❌ No se pudo enviar: número o mensaje vacío.")
        return False

    if not _validar_green_api():
        return False

    url = (
        f"{Config.GREEN_API_BASE_URL}/"
        f"waInstance{Config.GREEN_API_INSTANCE}/"
        f"sendMessage/"
        f"{Config.GREEN_API_TOKEN}"
    )

    data = {
        "chatId": f"{numero}@c.us",
        "message": mensaje
    }

    try:
        respuesta = requests.post(
            url,
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=20
        )

        if respuesta.status_code == 200:
            return True

        print(f"❌ Error Green API texto: {respuesta.status_code} - {respuesta.text}")
        return False

    except Exception as e:
        print("❌ Error enviando mensaje por Green API:", e)
        return False


def obtener_url_pdf_servicios() -> str:
    """
    Define la URL pública del PDF institucional.

    Prioridad:
    1. URL_PDF_SERVICIOS si fue configurada directamente en Render.
    2. BOT_PUBLIC_URL + /documentos/NOMBRE_PDF_SERVICIOS.
    """
    if Config.URL_PDF_SERVICIOS:
        return Config.URL_PDF_SERVICIOS.strip()

    if Config.BOT_PUBLIC_URL:
        return f"{Config.BOT_PUBLIC_URL}/documentos/{Config.NOMBRE_PDF_SERVICIOS}"

    return ""


def enviar_archivo_por_url(numero: str, url_file: str, file_name: str, caption: str = "") -> bool:
    """
    Envía un archivo por URL pública usando Green API sendFileByUrl.
    """
    numero = limpiar_numero(numero)

    if not numero:
        print("❌ No se pudo enviar archivo: número vacío.")
        return False

    if not url_file:
        print("❌ No se pudo enviar archivo: URL del archivo vacía.")
        return False

    if not file_name:
        print("❌ No se pudo enviar archivo: nombre de archivo vacío.")
        return False

    if not _validar_green_api():
        return False

    url = (
        f"{Config.GREEN_API_BASE_URL}/"
        f"waInstance{Config.GREEN_API_INSTANCE}/"
        f"sendFileByUrl/"
        f"{Config.GREEN_API_TOKEN}"
    )

    data = {
        "chatId": f"{numero}@c.us",
        "urlFile": url_file,
        "fileName": file_name,
        "caption": caption or ""
    }

    try:
        respuesta = requests.post(
            url,
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if respuesta.status_code == 200:
            return True

        print(f"❌ Error Green API archivo: {respuesta.status_code} - {respuesta.text}")
        print("URL PDF usada:", url_file)
        return False

    except Exception as e:
        print("❌ Error enviando archivo por Green API:", e)
        return False


def enviar_pdf_servicios(numero: str, caption: str = "") -> bool:
    """
    Envía el PDF institucional de servicios DALGORO una sola vez cuando el flujo lo solicita.
    Esta función es importada por webhook.py.
    """
    if not Config.ENVIAR_PDF_SERVICIOS:
        print("ℹ️ Envío de PDF de servicios desactivado por ENVIAR_PDF_SERVICIOS=false.")
        return False

    url_pdf = obtener_url_pdf_servicios()

    if not url_pdf:
        print("❌ No se pudo enviar PDF: configure BOT_PUBLIC_URL o URL_PDF_SERVICIOS.")
        return False

    return enviar_archivo_por_url(
        numero=numero,
        url_file=url_pdf,
        file_name=Config.NOMBRE_PDF_SERVICIOS,
        caption=caption or "Le comparto el documento de servicios de DALGORO S.A.S."
    )
