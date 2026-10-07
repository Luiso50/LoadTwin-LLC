"""Adapter para la API oficial de Trulos Dispatch (requiere membresía Founder/Pro).

Este módulo queda con placeholders documentados: la API completa de Trulos está
detrás de un plan de pago y su documentación de endpoints no es pública. Antes
de usar este adapter en producción hay que:

1. Confirmar con Trulos (ventas/soporte) la URL base real de la API, el
   esquema de autenticación y el formato exacto de request/response.
2. Ajustar los paths, parámetros y el mapeo de campos marcados con TODO.
3. Definir la variable de entorno TRULOS_API_KEY (y TRULOS_API_BASE_URL si la
   URL real difiere del placeholder) en el entorno donde corre la API.
"""

import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import httpx

from src.database.models import Address, Load, LoadStatus
from src.integrations.load_sources import LoadSearchCriteria

# TODO: reemplazar por la URL base real una vez confirmada con Trulos.
DEFAULT_BASE_URL = "https://api.trulos.com"


class TrulosApiError(RuntimeError):
    """Error de configuración o de respuesta inesperada de la API de Trulos."""


@dataclass(frozen=True)
class TrulosApiConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL

    @classmethod
    def from_env(cls) -> "TrulosApiConfig":
        api_key = os.getenv("TRULOS_API_KEY")
        if not api_key:
            raise TrulosApiError("TRULOS_API_KEY no está configurada")
        base_url = os.getenv("TRULOS_API_BASE_URL", cls.base_url)
        return cls(api_key=api_key, base_url=base_url)


class TrulosApiSource:
    """Implementa el protocolo LoadSource consultando la bolsa de cargas de Trulos."""

    name = "trulos"

    def __init__(
        self,
        config: Optional[TrulosApiConfig] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._config = config or TrulosApiConfig.from_env()
        self._client = client or httpx.Client(
            base_url=self._config.base_url,
            headers={"Authorization": f"Bearer {self._config.api_key}"},
            timeout=10.0,
        )

    def search(self, criteria: LoadSearchCriteria) -> list[Load]:
        # TODO: confirmar el path real (placeholder: /v1/loads) y si acepta
        # estos mismos nombres de parámetros o requiere otro formato.
        response = self._client.get("/v1/loads", params=self._build_params(criteria))
        response.raise_for_status()
        payload = response.json()
        return [self._to_load(item) for item in payload.get("data", [])]

    def get_document(self, document_type: str, document_id: str) -> dict[str, Any]:
        """Obtiene un BOL o rate confirmation existente. Placeholder de endpoint."""
        # TODO: confirmar el path real (placeholder: /v1/documents/{type}/{id}).
        response = self._client.get(f"/v1/documents/{document_type}/{document_id}")
        response.raise_for_status()
        return response.json()

    def create_document(self, document_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Crea un BOL o rate confirmation. Placeholder de endpoint y payload."""
        # TODO: confirmar el path real y el esquema de payload esperado.
        response = self._client.post(f"/v1/documents/{document_type}", json=payload)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _build_params(criteria: LoadSearchCriteria) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if criteria.origin_city:
            params["origin_city"] = criteria.origin_city
        if criteria.origin_state:
            params["origin_state"] = criteria.origin_state
        if criteria.destination_city:
            params["destination_city"] = criteria.destination_city
        if criteria.destination_state:
            params["destination_state"] = criteria.destination_state
        if criteria.equipment_type:
            params["equipment_type"] = criteria.equipment_type
        if criteria.pickup_date:
            params["pickup_date"] = criteria.pickup_date.isoformat()
        if criteria.minimum_rate is not None:
            params["minimum_rate"] = criteria.minimum_rate
        return params

    @staticmethod
    def _to_load(item: dict[str, Any]) -> Load:
        # TODO: ajustar este mapeo al esquema real de respuesta de la API de Trulos.
        origin = item.get("origin", {})
        destination = item.get("destination", {})
        pickup_date_raw = item.get("pickup_date")
        return Load(
            id=str(item.get("id", "")),
            origin=Address(city=origin.get("city", ""), state=origin.get("state", "")),
            destination=Address(city=destination.get("city", ""), state=destination.get("state", "")),
            equipment_type=item.get("equipment_type", ""),
            pickup_date=date.fromisoformat(pickup_date_raw) if pickup_date_raw else None,
            offered_rate=item.get("rate"),
            status=LoadStatus.AVAILABLE,
            source="trulos",
            external_reference=str(item.get("id", "")),
        )

    def close(self) -> None:
        self._client.close()
