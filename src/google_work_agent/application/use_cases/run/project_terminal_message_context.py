"""Project bounded durable facts used by terminal Assistant messages."""

from json import loads
from typing import cast

from google_work_agent.application.use_cases.plan.persistence_projection import (
    current_plan_tuple,
)
from google_work_agent.application.use_cases.run.build_terminal_message import (
    TerminalActionOutcomeV1,
    TerminalActionStatusV1,
    TerminalEffectTypeV1,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

_TERMINAL_ACTION_STATUSES = frozenset(
    {
        "VERIFIED",
        "REJECTED",
        "FAILED",
        "MISMATCH",
        "BLOCKED",
        "DEPENDENCY_BLOCKED",
        "CANCELLED",
    }
)


def project_terminal_message_context(
    unit_of_work: UnitOfWork,
    run_id: str,
) -> tuple[str | None, tuple[TerminalActionOutcomeV1, ...]]:
    """Return the user request and closed action facts from canonical persistence."""

    run = unit_of_work.runs.get(run_id)
    if run is None:
        raise LookupError(f"run not found: {run_id}")
    messages, _ = unit_of_work.messages.list_by_conversation_keyset(
        conversation_id=run.conversation_id,
        cursor=None,
        page_size=200,
    )
    user_message = next(
        (message for message in messages if message.run_id == run_id and message.role == "USER"),
        None,
    )
    plans = current_plan_tuple(unit_of_work.plans, run_id)
    plan = plans[0] if plans else None
    actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
    outcomes: list[TerminalActionOutcomeV1] = []
    for action in actions:
        if action.status not in _TERMINAL_ACTION_STATUSES:
            continue
        arguments = loads(action.arguments_json)
        if not isinstance(arguments, dict):
            raise ValueError("persisted Action arguments must be an object")
        outcomes.append(
            TerminalActionOutcomeV1(
                tool_name=action.tool_name,
                effect_type=cast(TerminalEffectTypeV1, action.effect_type),
                status=cast(TerminalActionStatusV1, action.status),
                arguments=arguments,
                evidence_excerpts=tuple(
                    evidence.excerpt
                    for evidence in unit_of_work.evidence.list_for_action(action.id)
                ),
            )
        )
    return (
        None if user_message is None else user_message.content,
        tuple(outcomes),
    )


__all__ = ["project_terminal_message_context"]
