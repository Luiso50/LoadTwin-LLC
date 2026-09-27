import json
from typing import Optional
from pydantic import BaseModel, Field

# Esquema de datos para la extracción de información de cargas
class LoadDetails(BaseModel):
    origin: str = Field(description="Ciudad y Estado de origen de la carga, e.g., 'Miami, FL'")
    destination: str = Field(description="Ciudad y Estado de destino, e.g., 'Orlando, FL'")
    equipment_type: str = Field(description="Tipo de remolque: Dry Van, Reefer, Flatbed, etc.")
    weight_lbs: Optional[int] = Field(None, description="Peso de la carga en libras si se especifica")
    pickup_date: Optional[str] = Field(None, description="Fecha de recogida estimada")
    offered_rate: Optional[float] = Field(None, description="Tarifa u oferta mencionada por el cliente")

# Prompt del sistema para el Agente Dispatcher
DISPATCHER_SYSTEM_PROMPT = """
Eres el Agente de Despacho Automático de LoadTwin LLC.
Tu objetivo es analizar los mensajes entrantes de clientes o choferes y extraer los detalles clave de la carga con total precisión.

REGLAS DE OPERACIÓN:
1. Extrae únicamente la información presente en el texto. Si un dato no se menciona (ej. peso o tarifa), déjalo como null.
2. Identifica correctamente las abreviaturas de estados (ej. 'FL' para Florida).
3. Clasifica el tipo de equipo (Dry Van, Reefer, Flatbed) de acuerdo con los términos habituales del transporte.
4. Responde SIEMPRE en formato JSON estricto cumpliendo con el esquema especificado.
"""

def build_agent_payload(user_message: str) -> dict:
    """
    Función auxiliar para estructurar la solicitud hacia el modelo Gemini.
    """
    return {
        "system_instruction": DISPATCHER_SYSTEM_PROMPT,
        "contents": [user_message],
        "response_mime_type": "application/json",
        "response_schema": LoadDetails.model_json_schema()
    }

if __name__ == "__main__":
    # Ejemplo de prueba rápida
    sample_text = "Necesito mover una carga de refrigerado de Miami, FL a Orlando, FL para mañana. Pesa unas 18000 lbs y pago $900."
    print("--- Ejemplo de carga procesada ---")
    print(json.dumps(build_agent_payload(sample_text), indent=2))
