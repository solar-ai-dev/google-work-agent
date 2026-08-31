from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.runtime.background_run_executor import (
    BackgroundRunExecutorAdapter,
)
from google_work_agent.application.use_cases.run.confirm_run import (
    ConfirmRunCommand,
    ConfirmRunHandler,
    ConfirmRunResult,
)
from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeConfirmationHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
    ScheduleRunExecutionHandler,
)
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowResumeRequest,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    ConfirmationResumeControlV1,
    RunExecutionRefV1,
    WorkflowExecutionAdmissionV1,
    WorkflowHandoffStageV1,
    WorkflowHandoffV1,
)


def start_with_admission(runtime: Any, database_path: Any, request: Any) -> Any:
    """Run a test START through the persisted handoff/admission boundary."""
    factory = runtime._unit_of_work_factory  # noqa: SLF001
    checkpoint = runtime._checkpoint_port  # noqa: SLF001
    profile = runtime._graph_profile.value  # noqa: SLF001
    registry = runtime._resume_target_registry  # noqa: SLF001
    target = registry.issue_agent_node(
        profile,
        "REQUEST_UNDERSTANDING",
        "request.identify_goal",
        RESUME_CONTRACT_VERSION,
    )
    handoff_id = f"test-start-{request.run_id}"
    with factory() as unit_of_work:
        if checkpoint.load_workflow_binding(request.run_id) is None:
            unit_of_work.workflow_bindings.create_workflow_binding(
                WorkflowBindingV1(
                    schema_version=1,
                    workflow_key=request.workflow_key,
                    run_id=request.run_id,
                    langgraph_thread_id=request.workflow_key,
                    graph_profile=profile,
                    graph_version=RESUME_CONTRACT_VERSION,
                    requested_mode=request.requested_mode,
                    created_at_ms=1,
                )
            )
        if unit_of_work.workflow_handoffs.get(handoff_id) is None:
            unit_of_work.workflow_handoffs.stage_pending(
                WorkflowHandoffStageV1(
                    schema_version=1,
                    handoff_id=handoff_id,
                    trigger_command_id=f"test-start-command-{request.run_id}",
                    execution=RunExecutionRefV1(
                        schema_version=1,
                        execution_kind="START",
                        run_id=request.run_id,
                        langgraph_thread_id=request.workflow_key,
                        graph_profile=profile,
                        graph_version=RESUME_CONTRACT_VERSION,
                        requested_mode=request.requested_mode,
                        resume_target=None,
                    ),
                    checkpoint_id=None,
                    checkpoint_generation=0,
                    control_kind="NONE",
                    control=None,
                    control_payload_hash=None,
                )
            )
        unit_of_work.commit()

    results: list[Any] = []
    errors: list[BaseException] = []

    def materialize(admission: WorkflowExecutionAdmissionV1, _handoff: WorkflowHandoffV1):
        with checkpoint.execution_scope(
            admission,
            applied_handoff_id=admission.handoff_id,
            owner_scope="REQUEST_UNDERSTANDING",
            resume_target=target,
        ):
            runtime.prepare_start(request)
        result = checkpoint.load_same_run_checkpoint(request.run_id, request.workflow_key)
        assert result is not None
        return result

    def invoke(admission: WorkflowExecutionAdmissionV1, _handoff: WorkflowHandoffV1) -> None:
        try:
            with checkpoint.execution_scope(
                admission,
                applied_handoff_id=admission.handoff_id,
                owner_scope="REQUEST_UNDERSTANDING",
                resume_target=target,
            ):
                results.append(runtime.start(request))
        except BaseException as error:
            errors.append(error)

    executor = _executor(runtime, materialize=materialize, invoke=invoke)
    try:
        schedule = ScheduleRunExecutionHandler(
            unit_of_work_factory=factory,
            workflow_execution=executor,
            id_factory=lambda: f"test-start-admission-{request.run_id}",
        )
        accepted = schedule(ScheduleRunExecutionCommand(handoff_id=handoff_id))
        assert accepted.accepted
        assert executor.await_drained(10_000)
        if errors:
            raise errors[0]
        assert len(results) == 1
        return results[0]
    finally:
        executor.close()


def resume_confirmation_with_handoff(
    runtime: Any,
    database_path: Any,
    *,
    resume_payload: Mapping[str, object],
    command_id: str,
) -> tuple[ConfirmRunResult, Any | None]:
    """Run confirmation through ConfirmRun -> RESUME handoff -> admission worker."""
    del database_path
    factory = runtime._unit_of_work_factory  # noqa: SLF001
    checkpoint = runtime._checkpoint_port  # noqa: SLF001
    registry = runtime._resume_target_registry  # noqa: SLF001
    authority = runtime.resolve_pending_confirmation("run-1")
    if authority is None:
        raise AssertionError("test runtime has no pending confirmation")
    with factory() as unit_of_work:
        run = unit_of_work.runs.get("run-1")
        assert run is not None
        expected_version = run.version

    runtime_results: list[Any] = []
    errors: list[BaseException] = []

    def invoke(admission: WorkflowExecutionAdmissionV1, handoff: WorkflowHandoffV1) -> None:
        try:
            control = handoff.control
            assert isinstance(control, ConfirmationResumeControlV1)
            latest = checkpoint.load_same_run_checkpoint(
                admission.effective_binding.run_id,
                admission.effective_binding.langgraph_thread_id,
            )
            assert latest is not None
            target = admission.effective_binding.resume_target
            assert target is not None
            with checkpoint.execution_scope(
                admission,
                applied_handoff_id=admission.handoff_id,
                owner_scope=latest.owner_scope,
                resume_target=target,
            ):
                runtime_results.append(
                    runtime.resume(
                        WorkflowResumeRequest(
                            run_id="run-1",
                            workflow_key="thread-1",
                            resume_kind="CONFIRMATION",
                            resume_payload={
                                "confirmation_response": dict(control.confirmation_response),
                                "policy_confirmation_receipt": (
                                    None
                                    if control.policy_confirmation_receipt is None
                                    else dict(control.policy_confirmation_receipt)
                                ),
                            },
                            correlation=WorkflowCorrelationContext(
                                request_id=f"request-{command_id}",
                                command_id=command_id,
                                api_contract_version="1",
                            ),
                        )
                    )
                )
        except BaseException as error:
            errors.append(error)

    executor = _executor(
        runtime,
        materialize=lambda admission, handoff: _materialize_resume_control(
            runtime, admission, handoff
        ),
        invoke=invoke,
    )
    try:
        schedule = ScheduleRunExecutionHandler(
            unit_of_work_factory=factory,
            workflow_execution=executor,
            id_factory=lambda: f"test-admission-{command_id}",
        )
        resume_handler = ResumeConfirmationHandler(
            unit_of_work_factory=factory,
            checkpoint_port=runtime._checkpoint_port,  # noqa: SLF001
            now_ms=lambda: 2_000,
            id_factory=lambda: f"test-handoff-{command_id}",
            resume_target_registry=registry,
        )
        response_kind = str(resume_payload["response_kind"])
        selected_option = resume_payload.get("selected_option")
        free_text = resume_payload.get("free_text")
        result = ConfirmRunHandler(
            resolve_pending_confirmation=runtime.resolve_pending_confirmation,
            resume_confirmation=resume_handler,
            resume_target_registry=registry,
            schedule_run_execution=schedule,
            id_factory=lambda: f"test-policy-{command_id}",
        )(
            ConfirmRunCommand(
                command_id=command_id,
                request_hash=sha256(command_id.encode()).hexdigest(),
                run_id="run-1",
                expected_version=expected_version,
                interrupt_id=str(resume_payload["interrupt_id"]),
                response_kind=response_kind,
                selected_option=None if selected_option is None else str(selected_option),
                free_text=None if free_text is None else str(free_text),
            )
        )
        assert executor.await_drained(10_000)
        if errors:
            raise errors[0]
        return result, runtime_results[0] if runtime_results else None
    finally:
        executor.close()


def _materialize_resume_control(runtime: Any, admission: Any, handoff: Any) -> Any:
    del handoff
    checkpoint = runtime._checkpoint_port  # noqa: SLF001
    binding = admission.effective_binding
    latest = checkpoint.load_same_run_checkpoint(binding.run_id, binding.langgraph_thread_id)
    assert latest is not None
    return latest


def _executor(runtime: Any, *, materialize: Any, invoke: Any) -> BackgroundRunExecutorAdapter:
    checkpoint = runtime._checkpoint_port  # noqa: SLF001
    return BackgroundRunExecutorAdapter(
        unit_of_work_factory=runtime._unit_of_work_factory,  # noqa: SLF001
        checkpoint_port=checkpoint,
        materialize_admission_checkpoint=materialize,
        invoke_semantic_owner=invoke,
        release_active_lineage=lambda run_id, thread_id, handoff_id, run_sequence: (
            checkpoint.release_active_lineage(
                run_id=run_id,
                thread_id=thread_id,
                handoff_id=handoff_id,
                run_sequence=run_sequence,
            )
        ),
    )


__all__ = [
    "resume_confirmation_with_handoff",
    "start_with_admission",
]
