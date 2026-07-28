import requests
from datetime import datetime

WEBHOOK_RENDER = "https://bot-dalgoro-render.onrender.com/webhook"

telefono_prueba = "593984770663"

payload = {
    "typeWebhook": "incomingMessageReceived",
    "idMessage": f"PRUEBA-RENDER-{datetime.now().strftime('%H%M%S')}",
    "senderData": {
        "chatId": f"{telefono_prueba}@c.us",
        "sender": f"{telefono_prueba}@c.us",
        "senderName": "Darwin Prueba"
    },
    "messageData": {
        "typeMessage": "textMessage",
        "textMessageData": {
            "textMessage": "Hola vi su publicidad en Facebook"
        }
    }
}

print("Enviando prueba directa a Render...")
print(WEBHOOK_RENDER)

r = requests.post(WEBHOOK_RENDER, json=payload, timeout=60)

print("Código HTTP:", r.status_code)
print("Respuesta:", r.text)