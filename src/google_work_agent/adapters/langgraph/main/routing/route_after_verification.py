"""Route the Main graph after durable effect verification."""

from collections.abc import Callable, Collection, Mapping

ROUTE_AFTER_VERIFICATION_SUCCESSORS = frozenset(
    {"preflight", "recovery", "cancel_resolution", "response_synthesis", "end"}
)


def route_after_verification(
    state: Mapping[str, object],
    *,
    available_targets: Collection[str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if (
        isinstance(run_id, str)
        and should_stop_for_cancel(run_id)
        and target not in {"cancel_resolution", "response_synthesis"}
    ):
        return "end"
    if target not in ROUTE_AFTER_VERIFICATION_SUCCESSORS or target not in available_targets:
        raise ValueError("VERIFICATION returned an unregistered successor")
    return str(target)
