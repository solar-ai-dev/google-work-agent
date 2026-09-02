"""Route the Main graph after the preflight safety boundary."""

from collections.abc import Callable, Mapping

ROUTE_AFTER_PREFLIGHT_SUCCESSORS = frozenset(
    {
        "action_execution",
        "waiting_approval",
        "recovery",
        "domain_reconcile",
        "response_synthesis",
        "end",
    }
)


def route_after_preflight(
    state: Mapping[str, object], *, should_stop_for_cancel: Callable[[str], bool]
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if target not in ROUTE_AFTER_PREFLIGHT_SUCCESSORS:
        raise ValueError("PREFLIGHT returned an unregistered successor")
    return str(target)
