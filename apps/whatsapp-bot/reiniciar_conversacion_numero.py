import argparse
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# ======================================================
# CONFIGURACIÓN LOCAL PARA PRUEBAS
# ======================================================
# Debe estar en la misma carpeta del proyecto si no usas GOOGLE_CREDENTIALS_JSON en .env.
ARCHIVO_CREDENCIALES_LOCAL = "dalgoro-api-ea1fa305d0ca.json"


def preparar_google_sheets_local():
    """
    Carga GOOGLE_CREDENTIALS_JSON antes de importar google_sheets_utils.

    Prioridad:
    1. Usa GOOGLE_CREDENTIALS_JSON si ya existe en .env o en el entorno.
    2. Si no existe, lee el archivo JSON local y lo convierte en variable de entorno.
    """
    load_dotenv()

    if os.getenv("GOOGLE_CREDENTIALS_JSON"):
        print("✅ GOOGLE_CREDENTIALS_JSON cargado desde variable de entorno.")
        return

    ruta_json = Path(ARCHIVO_CREDENCIALES_LOCAL)

    if not ruta_json.exists():
        raise FileNotFoundError(
            f"No encontré el archivo {ARCHIVO_CREDENCIALES_LOCAL}. "
            "Debe estar en la misma carpeta del proyecto o debe existir GOOGLE_CREDENTIALS_JSON en .env."
        )

    with open(ruta_json, "r", encoding="utf-8") as f:
        credenciales = json.load(f)

    os.environ["GOOGLE_CREDENTIALS_JSON"] = json.dumps(credenciales)

    print("✅ GOOGLE_CREDENTIALS_JSON cargado desde archivo JSON local.")
    print("✅ Service account:", credenciales.get("client_email", "No encontrado"))


def mostrar_resultado(resultado):
    print("\n======================================")
    print(" REINICIO DE CONVERSACIÓN DALGORO")
    print("======================================")
    print(f"Teléfono procesado: {resultado.get('telefono')}")

    print("\nFilas eliminadas:")
    print(f"- Contactos: {resultado.get('Contactos', 0)}")
    print(f"- Mensajes: {resultado.get('Mensajes', 0)}")
    print(f"- Citas: {resultado.get('Citas', 0)}")
    print(f"- Conversaciones_Sin_Cierre: {resultado.get('Conversaciones_Sin_Cierre', 0)}")
    print(f"- Estados_Conversacion: {resultado.get('Estados_Conversacion', 0)}")

    print("\n✅ Proceso finalizado.")
    print("Ahora ese número puede escribir al bot como si fuera una conversación nueva.")


def main():
    parser = argparse.ArgumentParser(
        description="Reinicia o borra registros de conversación de un número específico en Google Sheets."
    )

    parser.add_argument(
        "telefono",
        help="Número a reiniciar. Ejemplo: 593984770663 o 0984770663"
    )

    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="Confirma el borrado. Sin esta opción no se ejecuta la eliminación."
    )

    parser.add_argument(
        "--solo-estado",
        action="store_true",
        help="Borra solo el estado conversacional, sin borrar mensajes, citas ni contactos."
    )

    args = parser.parse_args()

    if not args.confirmar:
        print("⚠️ Esta acción puede borrar registros de Google Sheets.")
        print("Para ejecutar realmente el reinicio completo, use:")
        print(f"python reiniciar_conversacion_numero.py {args.telefono} --confirmar")
        print("\nSi solo desea borrar el estado conversacional:")
        print(f"python reiniciar_conversacion_numero.py {args.telefono} --solo-estado --confirmar")
        return

    # Importante: primero cargar credenciales y luego importar google_sheets_utils.
    preparar_google_sheets_local()

    from google_sheets_utils import sheets_manager

    if args.solo_estado:
        resultado = sheets_manager.reiniciar_numero(
            args.telefono,
            borrar_contacto=False,
            borrar_mensajes=False,
            borrar_citas=False,
            borrar_sin_cierre=False,
            borrar_estado=True
        )
    else:
        resultado = sheets_manager.reiniciar_numero(
            args.telefono,
            borrar_contacto=True,
            borrar_mensajes=True,
            borrar_citas=True,
            borrar_sin_cierre=True,
            borrar_estado=True
        )

    mostrar_resultado(resultado)


if __name__ == "__main__":
    main()
