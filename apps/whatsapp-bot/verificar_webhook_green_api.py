import requests
from config import Config

url = (
    f"{Config.GREEN_API_BASE_URL}/"
    f"waInstance{Config.GREEN_API_INSTANCE}/"
    f"getSettings/"
    f"{Config.GREEN_API_TOKEN}"
)

print("Consultando configuración Green API...")
print("URL:", url.replace(Config.GREEN_API_TOKEN, "TOKEN_OCULTO"))

r = requests.get(url, timeout=30)

print("Código HTTP:", r.status_code)
print("Respuesta:")
print(r.text)