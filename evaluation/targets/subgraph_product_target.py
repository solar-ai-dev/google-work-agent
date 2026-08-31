"""Exact compiled Product Subgraph invocation boundary."""

from __future__ import annotations

from collections.abc import Mapping

from evaluation.targets.target_registry import ResolvedTarget


def execute_subgraph_product_target(
    target: ResolvedTarget,
    product_input: dict[str, object],
    *,
    constructor_arguments: Mapping[str, object],
) -> dict[str, object]:
    subgraph = target.load()(**dict(constructor_arguments)).build()
    output = subgraph.invoke(product_input)
    if not isinstance(output, Mapping):
        raise ValueError("compiled Subgraph Product target must return an object")
    return {"node_results": [{"target_id": target.target_id, "output": dict(output)}]}


__all__ = ["execute_subgraph_product_target"]
