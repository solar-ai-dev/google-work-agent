"""Route the Main graph after one claimed action execution step."""

from collections.abc import Callable, Mapping

ROUTE_AFTER_ACTION_EXECUTION_SUCCESSORS = frozenset(
    {
        "preflight",
        "verification",
        "recovery",
        "cancel_resolution",
        "domain_reconcile",
        "response_synthesis",
        "end",
    }
)


def route_after_action_execution(
    state: Mapping[str, object], *, should_stop_for_cancel: Callable[[str], bool]
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if (
        isinstance(run_id, str)
        and should_stop_for_cancel(run_id)
        and target not in {"cancel_resolution", "response_synthesis"}
    ):
        return "end"
    if target not in ROUTE_AFTER_ACTION_EXECUTION_SUCCESSORS:
        raise ValueError("ACTION_EXECUTION returned an unregistered successor")
    return str(target)
