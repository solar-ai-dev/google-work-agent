from collections.abc import Mapping


def route_after_build_dependencies(state: Mapping[str, object]) -> str:
    if "dependency_candidates" not in state:
        raise ValueError("dependency node must produce candidates")
    return "assemble"


__all__ = ["route_after_build_dependencies"]
