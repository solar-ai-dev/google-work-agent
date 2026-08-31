"""Exact Product Node invocation boundary."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from evaluation.targets.target_registry import ResolvedTarget


def execute_node_product_target(
    target: ResolvedTarget,
    product_input: dict[str, object],
    *,
    dependencies: Mapping[str, object] | None = None,
) -> dict[str, object]:
    function = target.load()
    signature = inspect.signature(function)
    available = dependencies or {}
    kwargs: dict[str, Any] = {}
    for name, parameter in list(signature.parameters.items())[1:]:
        if parameter.kind not in {parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY}:
            continue
        if name in available:
            kwargs[name] = available[name]
        elif parameter.default is parameter.empty:
            raise ValueError(f"missing Node Product dependency: {name}")
    output = function(product_input, **kwargs)
    if not isinstance(output, Mapping):
        raise ValueError("Node Product target must return an object")
    return {"node_results": [{"target_id": target.target_id, "output": dict(output)}]}


__all__ = ["execute_node_product_target"]
