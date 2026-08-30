from collections.abc import Mapping


def route_after_assemble_plan(state: Mapping[str, object]) -> str:
    if not isinstance(state.get("final_result"), Mapping):
        raise ValueError("assemble node must produce a validated final_result")
    return "end"


__all__ = ["route_after_assemble_plan"]
