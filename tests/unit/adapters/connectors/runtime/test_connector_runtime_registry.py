from __future__ import annotations

from dataclasses import dataclass

import pytest

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)


@dataclass
class _Runtime:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def test_registry_rejects_duplicate_authority_and_closes_each_runtime() -> None:
    registry = ConnectorRuntimeRegistry()
    runtime = _Runtime()
    registry.register("google_workspace", runtime)  # type: ignore[arg-type]

    assert registry.resolve("google_workspace") is runtime
    assert registry.connector_ids() == ("google_workspace",)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("google_workspace", _Runtime())  # type: ignore[arg-type]

    registry.close_all()

    assert runtime.closed is True
    assert registry.connector_ids() == ()
