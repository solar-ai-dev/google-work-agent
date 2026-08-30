from collections.abc import Mapping


def route_after_draft_action_objective_per_output_route(state: Mapping[str, object]) -> str:
    final = state.get("final_result")
    if isinstance(final, Mapping) and final.get("disposition") == "INTERRUPTED":
        return "end"
    if not state.get("action_objective_candidates"):
        raise ValueError("objective node must produce candidates")
    return "compose_arguments_per_output_route"


__all__ = ["route_after_draft_action_objective_per_output_route"]
