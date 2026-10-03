from abc import ABC, abstractmethod

from ..models import Evidence


class Collector(ABC):

    name: str

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[Evidence]:
        raise NotImplementedError