"""Evaluación simple de rentabilidad de una carga en función del costo de diésel.

Placeholder mientras no haya una fuente real de precio de diésel (ej. EIA API)
ni de distancia real de ruta (ej. Google Maps Distance Matrix). Por ahora
`distance_miles` y `diesel_price_per_gallon` se reciben como parámetros
explícitos; más adelante pueden alimentarse desde una integración real.
"""

from dataclasses import dataclass
from decimal import Decimal

from src.database.models import Load

DEFAULT_AVG_MPG = Decimal("6.5")  # promedio típico de un tractocamión


@dataclass(frozen=True)
class ProfitabilityAssessment:
    load_id: str
    distance_miles: Decimal
    diesel_price_per_gallon: Decimal
    estimated_gallons: Decimal
    estimated_fuel_cost: Decimal
    offered_rate: Decimal
    estimated_margin: Decimal
    rate_per_mile: Decimal
    is_profitable: bool


def evaluate_load_profitability(
    load: Load,
    distance_miles: Decimal,
    diesel_price_per_gallon: Decimal,
    avg_mpg: Decimal = DEFAULT_AVG_MPG,
    minimum_margin: Decimal = Decimal("0"),
) -> ProfitabilityAssessment:
    if load.offered_rate is None:
        raise ValueError("El load no tiene offered_rate para evaluar rentabilidad")
    if distance_miles <= 0:
        raise ValueError("distance_miles debe ser mayor a 0")

    estimated_gallons = distance_miles / avg_mpg
    estimated_fuel_cost = estimated_gallons * diesel_price_per_gallon
    estimated_margin = load.offered_rate - estimated_fuel_cost
    rate_per_mile = load.offered_rate / distance_miles

    return ProfitabilityAssessment(
        load_id=load.id,
        distance_miles=distance_miles,
        diesel_price_per_gallon=diesel_price_per_gallon,
        estimated_gallons=estimated_gallons,
        estimated_fuel_cost=estimated_fuel_cost,
        offered_rate=load.offered_rate,
        estimated_margin=estimated_margin,
        rate_per_mile=rate_per_mile,
        is_profitable=estimated_margin > minimum_margin,
    )
