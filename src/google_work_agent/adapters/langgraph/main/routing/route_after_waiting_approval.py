"""Route the Main graph after the approval interrupt."""

from collections.abc import Callable, Mapping

ROUTE_AFTER_WAITING_APPROVAL_SUCCESSORS = frozenset(
    {"review_entry", "preflight", "response_synthesis", "end"}
)


def route_after_waiting_approval(
    state: Mapping[str, object], *, should_stop_for_cancel: Callable[[str], bool]
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if target not in ROUTE_AFTER_WAITING_APPROVAL_SUCCESSORS:
        raise ValueError("WAITING_APPROVAL returned an unregistered successor")
    return str(target)
