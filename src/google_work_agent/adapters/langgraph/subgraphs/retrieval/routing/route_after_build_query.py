from collections.abc import Mapping


def route_after_build_query(state: object) -> str:
    if isinstance(state, Mapping) and state.get("__context_followup_operation__") == "FINALIZE":
        return "finalize"
    return "execute_read"
