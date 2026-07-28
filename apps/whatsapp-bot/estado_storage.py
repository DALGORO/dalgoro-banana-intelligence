from google_sheets_utils import sheets_manager


def obtener_estado(telefono):
    return sheets_manager.obtener_estado_conversacion(telefono)


def guardar_estado(telefono, estado):
    return sheets_manager.guardar_estado_conversacion(telefono, estado)
