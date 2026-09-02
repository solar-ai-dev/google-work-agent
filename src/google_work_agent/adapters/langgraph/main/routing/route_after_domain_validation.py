"""Route the Main graph after Domain validation."""

from collections.abc import Callable, Mapping

ROUTE_AFTER_DOMAIN_VALIDATION_SUCCESSORS = frozenset(
    {"waiting_approval", "preflight", "response_synthesis", "domain_reconcile", "end"}
)


def route_after_domain_validation(
    state: Mapping[str, object], *, should_stop_for_cancel: Callable[[str], bool]
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if target not in ROUTE_AFTER_DOMAIN_VALIDATION_SUCCESSORS:
        raise ValueError("DOMAIN_VALIDATION returned an unregistered successor")
    return str(target)
