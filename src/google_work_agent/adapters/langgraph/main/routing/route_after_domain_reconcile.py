"""Route the Main graph after durable Domain reconciliation."""

from collections.abc import Callable, Mapping

ROUTE_AFTER_DOMAIN_RECONCILE_SUCCESSORS = frozenset(
    {"waiting_approval", "action_execution", "recovery", "response_synthesis", "end"}
)


def route_after_domain_reconcile(
    state: Mapping[str, object], *, should_stop_for_cancel: Callable[[str], bool]
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if target not in ROUTE_AFTER_DOMAIN_RECONCILE_SUCCESSORS:
        raise ValueError("DOMAIN_RECONCILE returned an unregistered successor")
    return str(target)
