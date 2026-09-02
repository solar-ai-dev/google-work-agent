from google_work_agent.adapters.langgraph.write_reconciliation import (
    ReconcileAggregate,
    reconcile_write_conflict,
)


def test_action_approval__conflict_routes_to__existing_waiting_approval() -> None:
    decision = reconcile_write_conflict(
        aggregate=ReconcileAggregate.ACTION,
        current_status="MODIFIED",
        next_allowed_commands=("APPROVE_ACTION",),
    )

    assert decision.target == "waiting_approval"
    assert decision.outcome == "WAITING_APPROVAL"


def test_action_unknown__result_routes__to_existing_recovery() -> None:
    decision = reconcile_write_conflict(
        aggregate=ReconcileAggregate.ACTION,
        current_status="UNKNOWN_RESULT",
        next_allowed_commands=("RECOVER_EXISTING_RESULT",),
    )

    assert decision.target == "recovery"
    assert decision.outcome == "RECOVERY_REQUIRED"


def test_run_recovery__required_routes__to_existing_recovery() -> None:
    decision = reconcile_write_conflict(
        aggregate=ReconcileAggregate.RUN,
        current_status="RECOVERY_REQUIRED",
        next_allowed_commands=("RESOLVE_RECOVERY",),
    )

    assert decision.target == "recovery"
    assert decision.outcome == "RECOVERY_REQUIRED"


def test_reauth_and__cancel_are__real_suspend_branches() -> None:
    reauth = reconcile_write_conflict(
        aggregate=ReconcileAggregate.RUN,
        current_status="REAUTH_REQUIRED",
        next_allowed_commands=(),
    )
    cancel = reconcile_write_conflict(
        aggregate=ReconcileAggregate.RUN,
        current_status="CANCEL_REQUESTED",
        next_allowed_commands=(),
    )

    assert (reauth.target, reauth.outcome) == ("end", "SUSPEND_REAUTH_REQUIRED")
    assert (cancel.target, cancel.outcome) == ("end", "SUSPEND_CANCEL_REQUESTED")


def test_already_terminal_action__reenters_executor_without__new_domain_mutation() -> None:
    decision = reconcile_write_conflict(
        aggregate=ReconcileAggregate.ACTION,
        current_status="VERIFIED",
        next_allowed_commands=(),
    )

    assert decision.target == "action_execution"
    assert decision.outcome == "ALREADY_TERMINAL"
