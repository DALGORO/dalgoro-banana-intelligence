from green_api_client import enviar_mensaje_whatsapp


def enviar_mensaje(numero, mensaje):
    """
    Función auxiliar para pruebas manuales.
    No colocar credenciales en este archivo.
    """
    return enviar_mensaje_whatsapp(numero, mensaje)


if __name__ == "__main__":
    numero_destino = "593984770663"
    texto = "Prueba técnica de DALGORO S.A.S."
    enviar_mensaje(numero_destino, texto)
