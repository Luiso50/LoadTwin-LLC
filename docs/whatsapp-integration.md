# Integración de WhatsApp

LoadTwin usa WhatsApp para comunicación rápida; la evidencia y la operación oficial siguen registrándose en LoadTwin y Trulos.

## Webhook de Meta

Configura en Meta:

- Callback URL: `https://loadtwin-api.onrender.com/webhooks/whatsapp`
- Verify token: el valor privado elegido para `WHATSAPP_VERIFY_TOKEN`
- Suscripción: mensajes (`messages`)

## Variables privadas en Render

Configura estas variables en el servicio `loadtwin-api`:

- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_APP_SECRET`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_ONBOARDING_AUTOREPLY=false` inicialmente

El endpoint `GET /integrations/whatsapp/status` muestra únicamente booleanos de configuración; nunca devuelve tokens ni secretos.

## Activación gradual

1. Verifica el webhook con Meta.
2. Envía un mensaje de prueba y confirma `POST /webhooks/whatsapp`.
3. Revisa el mensaje en `GET /messages` y el caso en `GET /onboarding/{phone}`.
4. Activa `WHATSAPP_ONBOARDING_AUTOREPLY=true` solo después de validar las plantillas.
5. Activa `send_whatsapp=true` en una propuesta únicamente cuando el número destinatario esté autorizado.