from collections.abc import Mapping


def route_after_compose_arguments_per_output_route(state: Mapping[str, object]) -> str:
    if isinstance(state.get("user_interrupt"), Mapping):
        return "end"
    if not state.get("argument_candidates"):
        raise ValueError("arguments node must produce candidates")
    return "derive_dependencies"


__all__ = ["route_after_compose_arguments_per_output_route"]
