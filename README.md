# LoadTwin LLC

Estructura base del proyecto para la operacion de dispatch de carga y sus integraciones.

## Estructura

- `docs/`: contratos, acuerdos legales, Dispatch Agreement, W-9 y documentos relacionados.
- `config/`: archivos de configuracion y plantillas de variables de entorno.
- `src/agent/`: logica del agente de IA, prompts y cadenas de LangChain/LLM.
- `src/api/`: servidor web y endpoints de FastAPI o Node.js.
- `src/database/`: esquema de base de datos y migraciones.
- `src/integrations/`: conexiones con WhatsApp API, Google Maps API y otros servicios.
- `data/`: registros locales, JSONs de prueba y logs de desarrollo.

## Desarrollo local

Desde la raiz del proyecto, inicia la API en una terminal:

```powershell
py -3 -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

En otra terminal, sirve la landing:

```powershell
cd Web
py -3 -m http.server 8080
```

URLs locales:

- Landing: `http://127.0.0.1:8080`
- Salud de la API: `http://127.0.0.1:8000/health`
- Documentación interactiva: `http://127.0.0.1:8000/docs`

La API expone `POST /matching/carriers` para matching, `POST /loads/search` para buscar cargas normalizadas, `POST /assistant/search` para convertir un pedido de texto en filtros de búsqueda, `GET/POST /webhooks/whatsapp` para la verificación y recepción de mensajes de WhatsApp Cloud API, y `POST /contact` para solicitudes comerciales. La búsqueda usa un registro de fuentes preparado para conectar Trulos, DAT, Truckstop u otros proveedores mediante APIs o integraciones autorizadas; mientras no haya una fuente conectada devuelve una lista vacía.

Para verificar el webhook en Render, configura las variables privadas `WHATSAPP_VERIFY_TOKEN` y `WHATSAPP_APP_SECRET` con los valores de Meta. El webhook recibe mensajes y valida su firma cuando `WHATSAPP_APP_SECRET` está configurado. El parser inicial entiende pedidos comunes en español e inglés; más adelante puede sustituirse por un modelo LLM con salida estructurada. Todavía no envía respuestas automáticamente ni consulta una bolsa de cargas hasta configurar las credenciales oficiales.

Las solicitudes de contacto se guardan en memoria mientras el proceso está activo; antes de producción deben persistirse en una base de datos y conectarse a un canal de notificación. No se debe automatizar el acceso a bolsas de carga mediante scraping sin autorización del proveedor.

La web usa `http://127.0.0.1:8000` como URL local de la API. Antes de publicar, cambia `window.LOADTWIN_API_URL` en `Web/index.html` por la URL HTTPS de la API.
