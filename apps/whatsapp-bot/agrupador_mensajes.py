import threading
from config import Config

pendientes = {}
lock = threading.Lock()


def agregar_mensaje(telefono, mensaje, callback):
    """
    Agrupa mensajes consecutivos del mismo teléfono.
    Espera unos segundos antes de responder para que el cliente pueda enviar varias partes.
    """
    with lock:
        actual = pendientes.get(telefono)

        if actual and actual.get("timer"):
            actual["timer"].cancel()
            mensajes = actual["mensajes"] + [mensaje]
        else:
            mensajes = [mensaje]

        timer = threading.Timer(Config.AGRUPADOR_SEGUNDOS, _procesar, args=(telefono, callback))
        timer.daemon = True

        pendientes[telefono] = {
            "mensajes": mensajes,
            "timer": timer
        }

        timer.start()


def _procesar(telefono, callback):
    with lock:
        paquete = pendientes.pop(telefono, None)

    if not paquete:
        return

    mensaje_unido = "\n".join(m.strip() for m in paquete["mensajes"] if m.strip())

    if mensaje_unido:
        callback(telefono, mensaje_unido)
