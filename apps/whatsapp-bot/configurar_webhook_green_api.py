import requests
from config import Config

WEBHOOK_URL = "https://bot-dalgoro-render.onrender.com/webhook"

url = (
    f"{Config.GREEN_API_BASE_URL}/"
    f"waInstance{Config.GREEN_API_INSTANCE}/"
    f"setSettings/"
    f"{Config.GREEN_API_TOKEN}"
)

payload = {
    "webhookUrl": WEBHOOK_URL,
    "incomingWebhook": "yes",
    "outgoingWebhook": "yes",
    "outgoingMessageWebhook": "yes",
    "outgoingAPIMessageWebhook": "yes",
    "stateWebhook": "yes",
    "deviceWebhook": "yes",
    "keepOnlineStatus": "yes"
}

print("Configurando webhook:")
print(WEBHOOK_URL)

r = requests.post(url, json=payload, timeout=30)

print("Código HTTP:", r.status_code)
print("Respuesta:", r.text)

if r.status_code == 200:
    print("✅ Webhook configurado correctamente.")
else:
    print("❌ No se pudo configurar el webhook.")