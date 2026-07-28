import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    BASE_DIR = Path(__file__).resolve().parent

    # Green API
    GREEN_API_INSTANCE = (os.getenv("GREEN_API_INSTANCE") or "").strip()
    GREEN_API_TOKEN = (os.getenv("GREEN_API_TOKEN") or "").strip()
    GREEN_API_BASE_URL = (os.getenv("GREEN_API_BASE_URL") or "https://api.green-api.com").strip().rstrip("/")

    # Google Sheets
    GOOGLE_SHEET_ID = (os.getenv("GOOGLE_SHEET_ID") or "").strip()
    GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

    # Número personal para notificaciones internas
    NUMERO_PERSONAL_DALGORO = (os.getenv("NUMERO_PERSONAL_DALGORO") or "").strip()

    # Comportamiento del bot
    AGRUPADOR_SEGUNDOS = int(os.getenv("AGRUPADOR_SEGUNDOS", "10"))
    MAX_MESSAGES_PER_MINUTE = int(os.getenv("MAX_MESSAGES_PER_MINUTE", "8"))
    MAX_RESPONSES_PER_HOUR = int(os.getenv("MAX_RESPONSES_PER_HOUR", "80"))

    # Notificaciones internas al número personal
    ENVIAR_NOTIFICACIONES = os.getenv("ENVIAR_NOTIFICACIONES", "true").lower() == "true"

    # Documento institucional de servicios DALGORO
    # BOT_PUBLIC_URL debe ser la URL pública de Render, por ejemplo:
    # https://bot-dalgoro-render.onrender.com
    BOT_PUBLIC_URL = (os.getenv("BOT_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    URL_PDF_SERVICIOS = (os.getenv("URL_PDF_SERVICIOS") or "").strip()
    NOMBRE_PDF_SERVICIOS = (os.getenv("NOMBRE_PDF_SERVICIOS") or "SERVICIOS_DALGORO_SAS.pdf").strip()
    DOCUMENTOS_DIR = Path(os.getenv("DOCUMENTOS_DIR") or (BASE_DIR / "documentos")).resolve()
    ENVIAR_PDF_SERVICIOS = os.getenv("ENVIAR_PDF_SERVICIOS", "true").lower() == "true"

    # Seguridad operacional: el bot no debe iniciar conversaciones frías.
    # Solo responde a eventos entrantes o coordina dentro de una conversación abierta.
    SOLO_RESPONDER_ENTRANTES = True
