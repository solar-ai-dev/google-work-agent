"""Modify review and replan integration tests."""

from __future__ import annotations

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    ApproveWriteActionCommand,
    ApproveWriteActionService,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
    GraphProfile,
    ModifyWriteActionCommand,
    ModifyWriteActionService,
    Path,
    ProductFixtureSnapshotLoader,
    WorkflowCorrelationContext,
    WorkflowOutcome,
    WorkflowResumeRequest,
    _action_required_intent,
    _analysis_output,
    _make_runtime,
    _plan,
    _profile_reason_plan_output,
    _profile_request_source_output,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_write_request,
    _sufficiency_output,
    _write_plan_output,
    connect_sqlite,
    pytest,
    sqlite_unit_of_work_factory,
)


def test_edge_preflight_google_read_failure_blocks_claim_and_write(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-preflight-failure-edge.db",
        prompt_manifest_path=manifest_path,
    )

    try:
        assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
        approved = ApproveWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
            now_ms=lambda: 1000,
        )(
            ApproveWriteActionCommand(
                command_id="approve-preflight-failure-edge",
                request_hash="d" * 64,
                action_id="action-1",
                expected_version=0,
                approved_by_account_id="account-1",
                approved_by_display="User",
                source_snapshot={},
                approval_id="approval-preflight-failure-edge",
                idempotency_key="e" * 64,
            )
        )
        assert approved.applied is True
        gateway.queue_fault(
            operation="list_tasks",
            fault=GoogleGatewayFault(GoogleGatewayFaultKind.HTTP_500),
        )

        runtime.resume(
            WorkflowResumeRequest(
                run_id="run-1",
                workflow_key="thread-1",
                resume_kind="APPROVAL",
                resume_payload={"approved": True},
                correlation=WorkflowCorrelationContext(
                    request_id="request-preflight-failure-edge",
                    command_id="command-preflight-failure-edge",
                    api_contract_version="1",
                ),
            )
        )

        connection = connect_sqlite(database_path)
        try:
            action_status = connection.execute(
                "SELECT status FROM actions WHERE id = 'action-1';"
            ).fetchone()[0]
            attempt_count = connection.execute(
                "SELECT COUNT(*) FROM execution_attempts;"
            ).fetchone()[0]
        finally:
            connection.close()
        assert action_status == "APPROVED"
        assert gateway.count_calls("create_task") == 0
        assert attempt_count == 0
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "profile",
    [
        GraphProfile.SIX_ROLE_BASELINE,
        GraphProfile.THREE_STAGE,
        GraphProfile.SINGLE_BASELINE,
    ],
)
def test_modify_reenters_profile_review_and_pass_reopens_approval(
    tmp_path: Path, profile: GraphProfile
) -> None:
    root = tmp_path / profile.value.lower()
    root.mkdir()
    database_path = _seed_runtime_database(root)
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    llm_transaction_checks: list[bool] = []

    def assert_no_sqlite_write_transaction() -> None:
        connection = connect_sqlite(database_path)
        try:
            connection.execute("BEGIN IMMEDIATE;")
            llm_transaction_checks.append(True)
            connection.rollback()
        finally:
            connection.close()

    initial_payloads = (
        [
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ]
        if profile is GraphProfile.SIX_ROLE_BASELINE
        else [
            _profile_request_source_output(),
            _profile_reason_plan_output("PLAN_READY"),
            _review_output("PASS"),
        ]
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[*initial_payloads, _review_output("PASS")],
        gateway=gateway,
        checkpoint_database_path=root / "checkpoints-modify-review.db",
        graph_profile=profile,
        prompt_manifest_path=_runtime_active_manifest_path(root),
        before_llm_invoke=assert_no_sqlite_write_transaction,
    )

    try:
        assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
        modified = ModifyWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
            now_ms=lambda: 1000,
            gateway=gateway,
        )(
            ModifyWriteActionCommand(
                command_id=f"modify-{profile.value}",
                request_hash="f" * 64,
                action_id="action-1",
                expected_version=0,
                arguments_patch={"title": "Send reviewed summary"},
            )
        )
        assert modified["applied"] is True

        resumed = runtime.resume(
            WorkflowResumeRequest(
                run_id="run-1",
                workflow_key="thread-1",
                resume_kind="MODIFY_REVIEW",
                resume_payload={
                    "resume_kind": "MODIFY_REVIEW",
                    "plan_id": "plan-1",
                    "review_version": 1,
                },
                correlation=WorkflowCorrelationContext(
                    request_id=f"request-{profile.value}",
                    command_id=f"resume-{profile.value}",
                    api_contract_version="1",
                ),
            )
        )

        assert resumed.outcome is WorkflowOutcome.ACCEPTED
        with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
            plan = unit_of_work.plans.get_by_id("plan-1")
            action = unit_of_work.actions.get_by_id("action-1")
        assert plan is not None and plan.review_status.value == "PASSED"
        assert action is not None and action.status == "MODIFIED"
        assert llm_transaction_checks
        assert gateway.count_calls("create_task") == 0

        approved = ApproveWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
            now_ms=lambda: 1000,
        )(
            ApproveWriteActionCommand(
                command_id=f"approve-after-review-{profile.value}",
                request_hash="0" * 64,
                action_id="action-1",
                expected_version=1,
                approved_by_account_id="account-1",
                approved_by_display="User",
                source_snapshot={},
                approval_id=f"approval-after-review-{profile.value}",
                idempotency_key="9" * 64,
            )
        )
        assert approved.applied is True
    finally:
        runtime.close()


@pytest.mark.parametrize(
    (
        "review_output",
        "expected_target",
        "expected_review_status",
        "expected_plan_status",
        "expected_run_status",
    ),
    [
        (
            _review_output(
                "REVISE",
                issues=[
                    {
                        "schema_version": 2,
                        "issue_id": "revise-action",
                        "kind": "MISSING_GOAL_COVERAGE",
                        "message": "Revise the modified action.",
                        "affected_action_ids": ["action-1"],
                        "affected_field_paths": ["$.actions[0].arguments.payload.title"],
                        "evidence_refs": ["evidence-1"],
                        "resource_refs": ["task:task-followup"],
                        "reason_codes": ["EVIDENCE_SUPPORTED"],
                    }
                ],
            ),
            "planning",
            "REVISE",
            "SUPERSEDED",
            "PLANNING",
        ),
        (
            _review_output(
                "RETRIEVE_MORE",
                issues=[
                    {
                        "schema_version": 2,
                        "issue_id": "retrieve-action",
                        "kind": "MISSING_EVIDENCE",
                        "message": "Retrieve current task evidence.",
                        "affected_action_ids": ["action-1"],
                        "affected_field_paths": ["$.actions[0]"],
                        "evidence_refs": ["evidence-1"],
                        "resource_refs": ["task:task-followup"],
                        "reason_codes": ["EVIDENCE_SUPPORTED"],
                    }
                ],
                additional_acquisition_request={
                    "schema_version": 1,
                    "origin_phase": "PLAN_REVIEW",
                    "reason_code": "REVIEW_MISSING_EVIDENCE",
                    "missing_information": ["current task evidence"],
                    "preferred_sources": ["TASKS"],
                    "query_hints": ["follow-up"],
                    "time_hints": [],
                    "resource_hints": ["task:task-followup"],
                },
            ),
            "acquisition",
            "RETRIEVE_MORE",
            "SUPERSEDED",
            "PLANNING",
        ),
        (
            _review_output("BLOCK", blockers=["Modified plan is unsafe."]),
            "finalize",
            "BLOCKED",
            "WAITING_APPROVAL",
            "WAITING_APPROVAL",
        ),
    ],
)
def test_modify_review_branches_use_existing_supervisor_routes(
    tmp_path: Path,
    review_output: dict[str, object],
    expected_target: str,
    expected_review_status: str,
    expected_plan_status: str,
    expected_run_status: str,
) -> None:
    root = tmp_path / expected_review_status.lower()
    root.mkdir()
    database_path = _seed_runtime_database(root)
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
            review_output,
        ],
        gateway=gateway,
        checkpoint_database_path=root / "checkpoints-modify-review-branch.db",
        prompt_manifest_path=_runtime_active_manifest_path(root),
    )

    try:
        assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
        modified = ModifyWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
            now_ms=lambda: 1000,
            gateway=gateway,
        )(
            ModifyWriteActionCommand(
                command_id=f"modify-{expected_review_status}",
                request_hash="1" * 64,
                action_id="action-1",
                expected_version=0,
                arguments_patch={"title": "Branch-reviewed title"},
            )
        )
        assert modified["applied"] is True
        snapshot = runtime._graph.get_state(  # noqa: SLF001
            runtime._config_for_thread("thread-1")  # noqa: SLF001
        )
        prepared = runtime._prepare_modify_review_state(  # noqa: SLF001
            snapshot.values,
            plan_id="plan-1",
            review_version=1,
        )
        reviewed = runtime._modify_review_node(prepared)  # noqa: SLF001

        assert reviewed["__target__"] == expected_target
        with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
            plan = unit_of_work.plans.get_by_id("plan-1")
            run = unit_of_work.runs.get_by_id("run-1")
            approvals = unit_of_work.approvals.list_by_action("action-1")
        assert plan is not None and plan.review_status.value == expected_review_status
        assert plan.status.value == expected_plan_status
        assert run is not None and run.status.value == expected_run_status
        assert approvals == ()
        assert gateway.count_calls("create_task") == 0
    finally:
        runtime.close()


@pytest.mark.parametrize("review_status", ["REVISE", "RETRIEVE_MORE"])
def test_modify_review_revise_or_retrieve_persists_a_new_plan_revision(
    tmp_path: Path, review_status: str
) -> None:
    root = tmp_path / review_status.lower()
    root.mkdir()
    database_path = _seed_runtime_database(root)
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    issue = {
        "schema_version": 2,
        "issue_id": f"{review_status.lower()}-action",
        "kind": "MISSING_EVIDENCE" if review_status == "RETRIEVE_MORE" else "MISSING_GOAL_COVERAGE",
        "message": "The modified plan needs another planning pass.",
        "affected_action_ids": ["action-1"],
        "affected_field_paths": ["$.actions[0]"],
        "evidence_refs": ["evidence-1"],
        "resource_refs": ["task:task-followup"],
        "reason_codes": ["EVIDENCE_SUPPORTED"],
    }
    additional_request = (
        {
            "schema_version": 1,
            "origin_phase": "PLAN_REVIEW",
            "reason_code": "REVIEW_MISSING_EVIDENCE",
            "missing_information": ["current task evidence"],
            "preferred_sources": ["TASKS"],
            "query_hints": ["follow-up"],
            "time_hints": [],
            "resource_hints": ["task:task-followup"],
        }
        if review_status == "RETRIEVE_MORE"
        else None
    )
    branch_review = _review_output(
        review_status,
        issues=[issue],
        additional_acquisition_request=additional_request,
    )
    continuation = (
        [
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ]
        if review_status == "RETRIEVE_MORE"
        else [_write_plan_output(), _review_output("PASS")]
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
            branch_review,
            *continuation,
        ],
        gateway=gateway,
        checkpoint_database_path=root / "checkpoints-modify-review-replan.db",
        prompt_manifest_path=_runtime_active_manifest_path(root),
    )

    try:
        assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
        modified = ModifyWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
            now_ms=lambda: 1000,
            gateway=gateway,
        )(
            ModifyWriteActionCommand(
                command_id=f"modify-{review_status.lower()}-chain",
                request_hash="4" * 64,
                action_id="action-1",
                expected_version=0,
                arguments_patch={"title": "Review branch title"},
            )
        )
        assert modified["applied"] is True

        resumed = runtime.resume(
            WorkflowResumeRequest(
                run_id="run-1",
                workflow_key="thread-1",
                resume_kind="MODIFY_REVIEW",
                resume_payload={
                    "resume_kind": "MODIFY_REVIEW",
                    "plan_id": "plan-1",
                    "review_version": 1,
                },
                correlation=WorkflowCorrelationContext(
                    request_id=f"request-{review_status.lower()}-chain",
                    command_id=f"resume-{review_status.lower()}-chain",
                    api_contract_version="1",
                ),
            )
        )

        assert resumed.outcome is WorkflowOutcome.ACCEPTED
        with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
            plans = unit_of_work.plans.list_by_run("run-1")
            run = unit_of_work.runs.get_by_id("run-1")
            old_actions = unit_of_work.actions.list_by_plan("plan-1")
            new_actions = unit_of_work.actions.list_by_plan(plans[-1].id)
        assert [(plan.revision_no, plan.status.value) for plan in plans] == [
            (1, "SUPERSEDED"),
            (2, "WAITING_APPROVAL"),
        ]
        assert run is not None and run.status.value == "WAITING_APPROVAL"
        assert old_actions[0].status == "MODIFIED"
        assert new_actions[0].id != "action-1"
        assert new_actions[0].status == "PROPOSED"
        assert gateway.count_calls("create_task") == 0
    finally:
        runtime.close()


def test_modify_review_block_finalizes_without_approval_or_write(tmp_path: Path) -> None:
    database_path = _seed_runtime_database(tmp_path)
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
            _review_output("BLOCK", blockers=["Modified plan is unsafe."]),
        ],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-modify-review-block.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )

    try:
        assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
        modified = ModifyWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
            now_ms=lambda: 1000,
            gateway=gateway,
        )(
            ModifyWriteActionCommand(
                command_id="modify-block-chain",
                request_hash="5" * 64,
                action_id="action-1",
                expected_version=0,
                arguments_patch={"title": "Unsafe branch title"},
            )
        )
        assert modified["applied"] is True

        resumed = runtime.resume(
            WorkflowResumeRequest(
                run_id="run-1",
                workflow_key="thread-1",
                resume_kind="MODIFY_REVIEW",
                resume_payload={
                    "resume_kind": "MODIFY_REVIEW",
                    "plan_id": "plan-1",
                    "review_version": 1,
                },
                correlation=WorkflowCorrelationContext(
                    request_id="request-block-chain",
                    command_id="resume-block-chain",
                    api_contract_version="1",
                ),
            )
        )

        assert resumed.outcome is WorkflowOutcome.COMPLETED
        with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
            run = unit_of_work.runs.get_by_id("run-1")
            plan = unit_of_work.plans.get_by_id("plan-1")
            approvals = unit_of_work.approvals.list_by_action("action-1")
            attempts = [
                attempt
                for approval in approvals
                for attempt in unit_of_work.execution_attempts.list_by_approval(approval.id)
            ]
        assert run is not None and run.status.value == "BLOCKED"
        assert plan is not None and plan.review_status.value == "BLOCKED"
        assert approvals == ()
        assert attempts == []
        assert gateway.count_calls("create_task") == 0
    finally:
        runtime.close()


def test_modify_during_review_discards_the_stale_llm_result(tmp_path: Path) -> None:
    database_path = _seed_runtime_database(tmp_path)
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
            _review_output("PASS"),
        ],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-stale-modify-review.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )
    modify_service = ModifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
        gateway=gateway,
    )

    try:
        assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
        assert (
            modify_service(
                ModifyWriteActionCommand(
                    command_id="modify-before-review",
                    request_hash="2" * 64,
                    action_id="action-1",
                    expected_version=0,
                    arguments_patch={"title": "First review title"},
                )
            )["applied"]
            is True
        )
        snapshot = runtime._graph.get_state(  # noqa: SLF001
            runtime._config_for_thread("thread-1")  # noqa: SLF001
        )
        first_generation = runtime._prepare_modify_review_state(  # noqa: SLF001
            snapshot.values,
            plan_id="plan-1",
            review_version=1,
        )

        assert (
            modify_service(
                ModifyWriteActionCommand(
                    command_id="modify-during-review",
                    request_hash="3" * 64,
                    action_id="action-1",
                    expected_version=1,
                    arguments_patch={"title": "Latest review title"},
                )
            )["applied"]
            is True
        )
        stale_review = runtime._modify_review_node(first_generation)  # noqa: SLF001
        stale_domain_result = runtime._domain_validation_node(stale_review)  # noqa: SLF001

        assert stale_domain_result["__target__"] == "end"
        assert stale_domain_result["execution_summary"] == {"result": "STALE_MODIFY_REVIEW"}
        with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
            plan = unit_of_work.plans.get_by_id("plan-1")
        assert plan is not None and plan.review_status.value == "REQUIRED"
        assert plan.review_version == 2
    finally:
        runtime.close()
