import os
from dataclasses import dataclass

import httpx

DEFAULT_GRAPH_API_BASE_URL = "https://graph.facebook.com/v20.0"


@dataclass(frozen=True)
class IncomingWhatsAppMessage:
    message_id: str
    sender: str
    text: str


class WhatsAppSendError(RuntimeError):
    """Error de configuración o de respuesta inesperada al enviar un mensaje."""


def extract_text_messages(payload: dict) -> list[IncomingWhatsAppMessage]:
    messages: list[IncomingWhatsAppMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                text = message.get("text", {}).get("body")
                if not text:
                    continue
                messages.append(
                    IncomingWhatsAppMessage(
                        message_id=message.get("id", ""),
                        sender=message.get("from", ""),
                        text=text,
                    )
                )
    return messages


def send_whatsapp_text_message(to: str, text: str) -> dict:
    """Envía un mensaje de texto saliente vía WhatsApp Cloud API.

    Requiere WHATSAPP_ACCESS_TOKEN y WHATSAPP_PHONE_NUMBER_ID configurados.
    """
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not access_token or not phone_number_id:
        raise WhatsAppSendError(
            "WHATSAPP_ACCESS_TOKEN y WHATSAPP_PHONE_NUMBER_ID deben estar configurados"
        )

    base_url = os.getenv("WHATSAPP_API_BASE_URL", DEFAULT_GRAPH_API_BASE_URL)
    response = httpx.post(
        f"{base_url}/{phone_number_id}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()