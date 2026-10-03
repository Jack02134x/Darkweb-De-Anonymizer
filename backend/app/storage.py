from threading import Lock

from .models import Investigation


class InvestigationStore:
    def __init__(self):
        self._items: dict[str, Investigation] = {}
        self._lock = Lock()

    def create(self, investigation: Investigation) -> Investigation:
        with self._lock:
            self._items[investigation.id] = investigation

        return investigation

    def get(self, investigation_id: str) -> Investigation | None:
        with self._lock:
            return self._items.get(investigation_id)

    def update(self, investigation: Investigation) -> Investigation:
        with self._lock:
            self._items[investigation.id] = investigation

        return investigation

    def list(self) -> list[Investigation]:
        with self._lock:
            return list(self._items.values())


store = InvestigationStore()