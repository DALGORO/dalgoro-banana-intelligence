from datetime import datetime
from zoneinfo import ZoneInfo

ZONA_HORARIA_EC = ZoneInfo("America/Guayaquil")


def ahora_ec():
    """Fecha y hora actual de Ecuador continental (America/Guayaquil)."""
    return datetime.now(ZONA_HORARIA_EC)


def ahora_txt():
    """Texto estándar para registrar en Google Sheets."""
    return ahora_ec().strftime("%Y-%m-%d %H:%M:%S")


def ahora_id():
    """Texto compacto para IDs internos."""
    return ahora_ec().strftime("%Y%m%d%H%M%S")
