"""Installed local-model discovery boundary."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class InstalledLocalModelV1:
    model_id: str
    digest: str | None


class LocalModelCatalogPort(Protocol):
    def list_installed_models(self) -> tuple[InstalledLocalModelV1, ...]: ...


__all__ = ["InstalledLocalModelV1", "LocalModelCatalogPort"]
