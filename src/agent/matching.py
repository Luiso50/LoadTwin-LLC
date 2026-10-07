from pydantic import BaseModel, Field

from src.database.models import Carrier, Load


class CarrierMatch(BaseModel):
    carrier_id: str
    score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)


def rank_carriers_for_load(
    load: Load,
    carriers: list[Carrier],
) -> list[CarrierMatch]:
    """Return active carriers ordered by equipment compatibility."""
    requested_equipment = load.equipment_type.strip().casefold()
    matches: list[CarrierMatch] = []

    for carrier in carriers:
        if not carrier.active:
            continue

        carrier_equipment = {
            equipment.strip().casefold() for equipment in carrier.equipment_types
        }
        if requested_equipment not in carrier_equipment:
            continue

        matches.append(
            CarrierMatch(
                carrier_id=carrier.id,
                score=100,
                reasons=[f"Compatible equipment: {load.equipment_type}"],
            )
        )

    return sorted(matches, key=lambda match: (-match.score, match.carrier_id))
