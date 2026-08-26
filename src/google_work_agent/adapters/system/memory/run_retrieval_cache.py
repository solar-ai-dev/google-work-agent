"""In-memory implementation of the run retrieval cache."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class InMemoryRunRetrievalCache:
    _entries: dict[str, object] = field(default_factory=dict)

    def get(self, key: str) -> object | None:
        return self._entries.get(key)

    def put(self, key: str, value: object) -> None:
        self._entries[key] = value

    def delete(self, key: str) -> None:
        self._entries.pop(key, None)
