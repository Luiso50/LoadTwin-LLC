import re

from src.integrations.load_sources import LoadSearchCriteria


EQUIPMENT_ALIASES = {
    "dry van": "Dry Van",
    "van seca": "Dry Van",
    "reefer": "Reefer",
    "refrigerado": "Reefer",
    "refrigerada": "Reefer",
    "flatbed": "Flatbed",
    "plataforma": "Flatbed",
}


def parse_load_request(message: str) -> LoadSearchCriteria:
    normalized = message.casefold()
    equipment_type = next(
        (value for alias, value in EQUIPMENT_ALIASES.items() if alias in normalized),
        None,
    )
    route_match = re.search(
        r"(?:de|from)\s+(.+?)\s+(?:a|to)\s+(.+?)(?:\s+para\b|\s+por\b|$)",
        message,
        flags=re.IGNORECASE,
    )
    if not route_match:
        return LoadSearchCriteria(equipment_type=equipment_type)

    return LoadSearchCriteria(
        origin_city=route_match.group(1).strip(" .,"),
        destination_city=route_match.group(2).strip(" .,"),
        equipment_type=equipment_type,
    )