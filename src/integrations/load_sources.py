from dataclasses import dataclass
from datetime import date
from typing import Protocol

from src.database.models import Load


@dataclass(frozen=True)
class LoadSearchCriteria:
    origin_city: str | None = None
    origin_state: str | None = None
    destination_city: str | None = None
    destination_state: str | None = None
    equipment_type: str | None = None
    pickup_date: date | None = None
    minimum_rate: float | None = None


class LoadSource(Protocol):
    name: str

    def search(self, criteria: LoadSearchCriteria) -> list[Load]:
        """Return normalized loads from an authorized external source."""


class LoadSourceRegistry:
    def __init__(self, sources: list[LoadSource] | None = None) -> None:
        self._sources = sources or []

    def search(self, criteria: LoadSearchCriteria) -> list[Load]:
        loads: list[Load] = []
        for source in self._sources:
            loads.extend(source.search(criteria))
        return loads


class InMemoryLoadSource:
    name = "in_memory"

    def __init__(self, loads: list[Load] | None = None) -> None:
        self._loads = loads or []

    def search(self, criteria: LoadSearchCriteria) -> list[Load]:
        return [load for load in self._loads if self._matches(load, criteria)]

    @staticmethod
    def _matches(load: Load, criteria: LoadSearchCriteria) -> bool:
        checks = (
            (criteria.origin_city, load.origin.city),
            (criteria.origin_state, load.origin.state),
            (criteria.destination_city, load.destination.city),
            (criteria.destination_state, load.destination.state),
            (criteria.equipment_type, load.equipment_type),
            (criteria.pickup_date, load.pickup_date),
        )
        for expected, actual in checks:
            if expected is not None and str(expected).casefold() != str(actual).casefold():
                return False
        if criteria.minimum_rate is not None:
            if load.offered_rate is None or float(load.offered_rate) < criteria.minimum_rate:
                return False
        return True