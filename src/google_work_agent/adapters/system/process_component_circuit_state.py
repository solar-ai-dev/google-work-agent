"""Process-local component circuit-state adapter."""


class ProcessComponentCircuitStateAdapter:
    def __init__(self) -> None:
        self._open_components: set[str] = set()

    def is_open(self, component: str) -> bool:
        return component in self._open_components

    def set_open(self, component: str, is_open: bool) -> None:
        if is_open:
            self._open_components.add(component)
        else:
            self._open_components.discard(component)
