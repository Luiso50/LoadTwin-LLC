# Arquitectura de LoadTwin LLC

## Dirección del producto

LoadTwin LLC es la capa de automatización e inteligencia que opera sobre Trulos, que continúa siendo el TMS operativo. WhatsApp sirve para comunicación rápida y el correo/documentos sirven como evidencia legal.

## Estado actual

- FastAPI concentra los endpoints y las integraciones con WhatsApp y Trulos.
- `src/agent/` contiene parsing, matching, rentabilidad y aprobaciones.
- `src/database/models.py` contiene contratos Pydantic compartidos por la API.
- La persistencia operativa actual es en memoria; no debe considerarse producción.
- La web pública existente permanece separada de la API y no se rediseña en esta fase.

## Arquitectura objetivo

```text
WhatsApp / Email / Dashboard
            |
       FastAPI API
            |
  Casos de uso de operaciones
            |
  Repositorios (memoria -> Firestore)
            |
 Trulos como TMS operacional
```

Los endpoints deben depender de modelos y repositorios, no de Firestore directamente. Así se puede probar el flujo localmente y sustituir `OperationsStore` por un repositorio Firestore en la fase 3.

## Colecciones previstas

`drivers`, `loads`, `brokers`, `contracts`, `documents`, `evidence`, `commissions` y `messages`.

La evidencia se relaciona con un `load_id` y conserva tipo, descripción, origen, fecha, URL y metadatos. Esto permite reconstruir una operación sin asumir que WhatsApp es el archivo legal definitivo. `POST /loads/{load_id}/evidence/email` registra asunto, destinatarios y cuerpo del email.

`POST /proposals` registra la propuesta enviada a un driver; `send_whatsapp` permite el envío explícito. La orden oficial continúa tomándose en Trulos después de la aceptación.

`POST /proposals/{proposal_id}/respond` registra aceptación o rechazo. Las respuestas `ACEPTO`, `ACEPTAR` y `RECHAZO` por WhatsApp actualizan la propuesta pendiente del driver registrado.

Una aceptación crea un `BookingCase` en `driver_accepted`; el caso queda pendiente de tomar la orden en Trulos y conserva la referencia externa cuando esa coordinación se complete.

La aceptación desde la oficina y la aceptación por WhatsApp usan la misma transición, evitando expedientes divergentes.

`POST /booking-cases/{case_id}/trulos-order` registra la referencia externa y avanza el caso a `ordered` después de que el operador tome la orden en Trulos.

`POST /booking-cases/{case_id}/status` permite seguir el caso en `in_transit` o `completed` sin modificar la orden dentro de Trulos.

Los endpoints `/booking-cases/{case_id}/payments` reflejan estados y comprobantes procesados por Trulos/Stripe; LoadTwin no cobra ni almacena credenciales de Stripe.

La referencia externa del pago es idempotente por booking case: reintentar la misma sincronización no crea un duplicado.

## Roadmap

1. **Fase 1:** drivers, onboarding documental, contratos, cargas y evidencia; completar repositorios y casos de uso.
2. **Fase 2:** persistencia de mensajes, integración de email, automatización WhatsApp y comisiones.
3. **Fase 3:** Firestore, dashboard operativo, autenticación, permisos y reporting.
4. **Fase 4:** sincronización autorizada con Trulos, matching avanzado y recomendaciones IA.

## Siguientes tareas

- Migrar brokers, contratos y comisiones desde memoria a un repositorio persistente.
- Añadir auditoría completa de aceptación y renovación de contratos digitales.
- `GET /contracts/renewals` ya devuelve contratos con renovación dentro de una ventana configurable.
- Conectar los mensajes idempotentes con persistencia real y políticas de retención.
- La finalización del onboarding crea el perfil activo y copia los cinco documentos verificados al driver.
- Los documentos activos se consultan con `GET /drivers/{driver_id}/documents` e incluyen URL y vencimiento cuando existen.
- Añadir notificaciones de onboarding con plantillas aprobadas de WhatsApp y email.
- La plantilla se puede previsualizar en `GET /onboarding/{phone}/message`; el envío WhatsApp requiere `WHATSAPP_ONBOARDING_AUTOREPLY=true`.
- Sustituir el almacenamiento en memoria por interfaces de repositorio y un adaptador Firestore.
- Añadir autenticación y autorización antes de exponer datos de drivers.
- Crear dashboard operativo sin alterar la landing pública.
- El API ya expone `GET /dashboard/summary` y `POST/GET /loads` para alimentar el dashboard con métricas operativas.

## Estrategia de Trulos

Trulos debe ser la fuente de verdad para operaciones que ya existan allí. La integración debe ser explícita, con mapeos de identificadores externos, reintentos, logs y sincronización idempotente. No se debe automatizar scraping ni asumir endpoints no documentados.