"""Exact compiled Main Graph/Profile invocation boundary."""

from __future__ import annotations

from collections.abc import Mapping

from evaluation.targets.target_registry import ResolvedTarget


def execute_main_profile_product_target(
    target: ResolvedTarget,
    product_input: dict[str, object],
    *,
    builder_arguments: Mapping[str, object],
) -> dict[str, object]:
    arguments = dict(builder_arguments)
    input_adapter = arguments.pop("input_adapter", None)
    output_adapter = arguments.pop("output_adapter", None)
    if input_adapter is not None and not callable(input_adapter):
        raise ValueError("Main Profile input_adapter must be callable")
    if output_adapter is not None and not callable(output_adapter):
        raise ValueError("Main Profile output_adapter must be callable")
    composition = target.load()(**arguments)
    graph = composition.build()
    graph_input = product_input if input_adapter is None else input_adapter(product_input)
    output = graph.invoke(graph_input)
    if not isinstance(output, Mapping):
        raise ValueError("compiled Main Profile Product target must return an object")
    if output_adapter is not None:
        observed = output_adapter(output)
        if not isinstance(observed, Mapping):
            raise ValueError("Main Profile output_adapter must return an object")
        return dict(observed)
    return {"node_results": [{"target_id": target.target_id, "output": dict(output)}]}


__all__ = ["execute_main_profile_product_target"]
