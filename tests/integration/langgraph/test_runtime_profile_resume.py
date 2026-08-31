"""Profile resume and prompt compatibility tests."""

from __future__ import annotations

from tests.integration.langgraph.test_runtime import (
    _PROFILE_CANDIDATE_PROMPT_IDS,
    _SIX_ROLE_BASELINE_PROMPT_IDS,
    FIXTURE_ROOT,
    FakeGoogleGateway,
    GraphProfile,
    InactivePromptArtifactError,
    Path,
    ProductFixtureSnapshotLoader,
    WorkflowCorrelationContext,
    WorkflowOutcome,
    WorkflowResumeRequest,
    _action_required_intent,
    _ambiguous_intent,
    _analysis_output,
    _answer_output,
    _clear_intent,
    _make_runtime,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _start_write_request,
    _write_plan_output,
    connect_sqlite,
    pytest,
    write_draft_manifest,
    write_manifest_with_legacy_profile_slots,
)
from tests.support.canonical_workflow_runtime import (
    resume_confirmation_with_handoff,
    start_with_admission,
)
from tests.support.checkpoint import sqlite_checkpoint
from tests.unit.application.workflows.test_context_retrieval import _sufficiency_output


def _answer_path_payloads() -> list[object]:
    return [
        _clear_intent(),
        _selection_output(),
        _sufficiency_output("SUFFICIENT"),
        _analysis_output(),
        _answer_output(),
    ]


def _action_path_payloads() -> list[object]:
    return [
        _action_required_intent(),
        _selection_output(),
        _sufficiency_output("SUFFICIENT"),
        _analysis_output(),
        _write_plan_output(),
        _review_output("PASS"),
    ]


@pytest.mark.parametrize(
    "graph_profile",
    [
        GraphProfile.SINGLE_BASELINE,
        GraphProfile.THREE_STAGE,
    ],
)
def test_agent_local_checkpoint_is_not_authority_for_approval_or_execution_facts(
    tmp_path: Path,
    graph_profile: GraphProfile,
) -> None:
    root = tmp_path / f"{graph_profile.value.lower()}-checkpoint-authority"
    root.mkdir()
    manifest_path = _runtime_active_manifest_path(root)
    database_path = _seed_runtime_database(root)
    checkpoint_database_path = root / "checkpoints.db"
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=_action_path_payloads(),
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(checkpoint_database_path),
        graph_profile=graph_profile,
        prompt_manifest_path=manifest_path,
    )

    try:
        started = runtime.start(_start_write_request())
        assert started.outcome is WorkflowOutcome.ACCEPTED

        checkpoint_connection = connect_sqlite(checkpoint_database_path)
        try:
            checkpoint_table_query_prefix = "SELECT name FROM sqlite_master WHERE type = 'table'"
            checkpoint_table_query = (
                f"{checkpoint_table_query_prefix} AND name LIKE 'checkpoints%';"
            )
            checkpoint_tables = [
                row[0] for row in checkpoint_connection.execute(checkpoint_table_query).fetchall()
            ]
            assert checkpoint_tables
            checkpoint_row_count = sum(
                checkpoint_connection.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
                for table in checkpoint_tables
            )
            assert checkpoint_row_count > 0
        finally:
            checkpoint_connection.close()

        domain_connection = connect_sqlite(database_path)
        try:
            counts = domain_connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM approvals) AS approval_count,
                    (SELECT COUNT(*) FROM execution_attempts) AS execution_attempt_count,
                    (SELECT COUNT(*) FROM verifications) AS verification_count;
                """
            ).fetchone()
            assert tuple(counts) == (0, 0, 0)
        finally:
            domain_connection.close()
    finally:
        runtime.close()


def test_single_stage_runtime_completes_answer_only_run(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=_answer_path_payloads(),
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(tmp_path / "checkpoints-single-answer.db"),
        graph_profile=GraphProfile.SINGLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    result = runtime.start(_start_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    assert result.payload["graph_profile"] == GraphProfile.SINGLE_BASELINE.value
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
        plan_count = connection.execute(
            "SELECT COUNT(*) FROM plans WHERE run_id = 'run-1';"
        ).fetchone()[0]
        action_count = connection.execute("SELECT COUNT(*) FROM actions;").fetchone()[0]
        assert tuple(run_row) == ("COMPLETED", 4)
        assert plan_count == 0
        assert action_count == 0
    finally:
        connection.close()
        runtime.close()


def test_three_stage_runtime_completes_answer_only_run(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=_answer_path_payloads(),
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(tmp_path / "checkpoints-three-answer.db"),
        graph_profile=GraphProfile.THREE_STAGE,
        prompt_manifest_path=manifest_path,
    )

    result = runtime.start(_start_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    assert result.payload["graph_profile"] == GraphProfile.THREE_STAGE.value
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
        plan_count = connection.execute(
            "SELECT COUNT(*) FROM plans WHERE run_id = 'run-1';"
        ).fetchone()[0]
        action_count = connection.execute("SELECT COUNT(*) FROM actions;").fetchone()[0]
        assert tuple(run_row) == ("COMPLETED", 4)
        assert plan_count == 0
        assert action_count == 0
    finally:
        connection.close()
        runtime.close()


def test_native_profiles_record_answer_path_invocation_counts(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    three = _make_runtime(
        database_path=database_path,
        llm_payloads=_answer_path_payloads(),
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(tmp_path / "checkpoints-three-native-full.db"),
        graph_profile=GraphProfile.THREE_STAGE,
        prompt_manifest_path=manifest_path,
    )
    try:
        three_result = three.start(_start_request())
        three_state = three._graph.get_state(three._config_for_thread("thread-1"))
        assert three_result.outcome is WorkflowOutcome.COMPLETED
        assert three_state.values["trace_context"]["agent_invocation_count"] == 5
        assert three_state.values["trace_context"]["llm_call_count"] == 13
    finally:
        three.close()

    single_root = tmp_path / "single-native"
    single_root.mkdir()
    database_path = _seed_runtime_database(single_root)
    single = _make_runtime(
        database_path=database_path,
        llm_payloads=_answer_path_payloads(),
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(single_root / "checkpoints-single-native-full.db"),
        graph_profile=GraphProfile.SINGLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )
    try:
        single_result = single.start(_start_request())
        single_state = single._graph.get_state(single._config_for_thread("thread-1"))
        assert single_result.outcome is WorkflowOutcome.COMPLETED
        assert single_state.values["trace_context"]["agent_invocation_count"] == 5
        assert single_state.values["trace_context"]["llm_call_count"] == 13
        assert {
            item["agent_subgraph_id"]
            for item in single_state.values["trace_context"]["agent_node_log"]
        } == {
            "request_understanding",
            "tool_route",
            "context_retriever",
            "work_analysis",
            "planning",
        }
    finally:
        single.close()


def test_resume_rejects_profile_change_for_same_thread(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    three_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_ambiguous_intent()],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(database_path),
        graph_profile=GraphProfile.THREE_STAGE,
        prompt_manifest_path=manifest_path,
    )
    first = start_with_admission(three_runtime, database_path, _start_request())
    assert first.outcome is WorkflowOutcome.ACCEPTED
    three_runtime.close()

    six_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(database_path),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    resumed = six_runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="CONFIRMATION",
            resume_payload={
                "confirmation_response": {
                    "schema_version": 1,
                    "response_kind": "FREE_TEXT",
                    "selected_option": None,
                    "free_text": "I mean Kim from project alpha.",
                },
            },
            correlation=WorkflowCorrelationContext(
                request_id="request-2",
                command_id="command-2",
                api_contract_version="1",
            ),
        )
    )

    try:
        assert resumed.outcome is WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT
        assert resumed.payload["graph_profile"] == GraphProfile.SIX_ROLE_BASELINE.value
    finally:
        six_runtime.close()


@pytest.mark.parametrize(
    ("graph_profile", "root_name"),
    [
        (GraphProfile.SINGLE_BASELINE, "single-plan"),
        (GraphProfile.THREE_STAGE, "three-plan"),
    ],
)
def test_native_profiles_generate_plan_and_share_domain_approval_boundary(
    tmp_path: Path,
    graph_profile: GraphProfile,
    root_name: str,
) -> None:
    root = tmp_path / root_name
    root.mkdir()
    manifest_path = _runtime_active_manifest_path(root)
    database_path = _seed_runtime_database(root)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=_action_path_payloads(),
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(root / "checkpoints-plan.db"),
        graph_profile=graph_profile,
        prompt_manifest_path=manifest_path,
    )

    started = runtime.start(_start_write_request())

    assert started.outcome is WorkflowOutcome.ACCEPTED
    connection = connect_sqlite(database_path)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1') AS run_status,
                (SELECT COUNT(*) FROM plans WHERE run_id = 'run-1') AS plan_count,
                (SELECT COUNT(*) FROM actions) AS action_count;
            """
        ).fetchone()
        assert tuple(counts) == ("WAITING_APPROVAL", 1, 1)
    finally:
        connection.close()
        runtime.close()


@pytest.mark.parametrize(
    ("graph_profile", "root_name"),
    [
        (GraphProfile.SINGLE_BASELINE, "single-resume"),
        (GraphProfile.THREE_STAGE, "three-resume"),
    ],
)
def test_native_profiles_resume_with_same_profile_after_confirmation(
    tmp_path: Path,
    graph_profile: GraphProfile,
    root_name: str,
) -> None:
    root = tmp_path / root_name
    root.mkdir()
    manifest_path = _runtime_active_manifest_path(root)
    database_path = _seed_runtime_database(root)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    first_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_ambiguous_intent()],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(database_path),
        graph_profile=graph_profile,
        prompt_manifest_path=manifest_path,
        id_prefix=f"{root_name}-initial",
    )

    first = start_with_admission(first_runtime, database_path, _start_request())

    assert first.outcome is WorkflowOutcome.ACCEPTED
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    first_runtime.close()

    resumed_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=_answer_path_payloads(),
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(database_path),
        graph_profile=graph_profile,
        prompt_manifest_path=manifest_path,
        id_prefix=f"{root_name}-resumed",
    )

    application_result, resumed = resume_confirmation_with_handoff(
        resumed_runtime,
        database_path,
        command_id="command-2",
        resume_payload={
            "interrupt_id": interrupt_id,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "Use the default task list.",
        },
    )
    assert application_result.applied is True
    assert resumed is not None

    try:
        assert resumed.outcome is WorkflowOutcome.COMPLETED
    finally:
        resumed_runtime.close()


@pytest.mark.parametrize(
    ("start_profile", "resume_profile", "root_name"),
    [
        (GraphProfile.SINGLE_BASELINE, GraphProfile.THREE_STAGE, "single-to-three"),
        (GraphProfile.SIX_ROLE_BASELINE, GraphProfile.SINGLE_BASELINE, "six-to-single"),
    ],
)
def test_resume_rejects_mismatched_profile_for_thread(
    tmp_path: Path,
    start_profile: GraphProfile,
    resume_profile: GraphProfile,
    root_name: str,
) -> None:
    root = tmp_path / root_name
    root.mkdir()
    manifest_path = _runtime_active_manifest_path(root)
    database_path = _seed_runtime_database(root)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    start_payloads = [_ambiguous_intent()]
    starter = _make_runtime(
        database_path=database_path,
        llm_payloads=start_payloads,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(database_path),
        graph_profile=start_profile,
        prompt_manifest_path=manifest_path,
    )
    first = start_with_admission(starter, database_path, _start_request())
    assert first.outcome is WorkflowOutcome.ACCEPTED
    starter.close()

    resumed_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(database_path),
        graph_profile=resume_profile,
        prompt_manifest_path=manifest_path,
    )

    resumed = resumed_runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="CONFIRMATION",
            resume_payload={
                "confirmation_response": {
                    "schema_version": 1,
                    "response_kind": "FREE_TEXT",
                    "selected_option": None,
                    "free_text": "Continue with the default task list.",
                },
            },
            correlation=WorkflowCorrelationContext(
                request_id="request-2",
                command_id="command-2",
                api_contract_version="1",
            ),
        )
    )

    try:
        assert resumed.outcome is WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT
        assert resumed.payload["graph_profile"] == resume_profile.value
    finally:
        resumed_runtime.close()


def test_default_product_runtime_rejects_draft_prompt_bundle(
    tmp_path: Path,
) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    manifest_path = write_draft_manifest(
        tmp_path,
        prompt_ids={"request_understanding.identify_goal"},
    )

    with pytest.raises(InactivePromptArtifactError, match="request_understanding.identify_goal"):
        _make_runtime(
            database_path=database_path,
            llm_payloads=[],
            gateway=FakeGoogleGateway(snapshot),
            checkpoint_port=sqlite_checkpoint(tmp_path / "checkpoints-draft.db"),
            prompt_manifest_path=manifest_path,
        )


def test_six_role_baseline_runtime_ignores_inactive_profile_candidate_prompts(
    tmp_path: Path,
) -> None:
    """SINGLE_BASELINE/THREE_STAGE are E06-A architecture candidates under
    comparison (docs/06-agent-workflow.md 1.1), not features that ship
    alongside SIX_ROLE_BASELINE. Their prompts being DRAFT must not block
    construction of a SIX_ROLE_BASELINE runtime.
    """
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    manifest_path = write_manifest_with_legacy_profile_slots(
        tmp_path,
        legacy_prompt_ids=_PROFILE_CANDIDATE_PROMPT_IDS,
        active_prompt_ids=_SIX_ROLE_BASELINE_PROMPT_IDS,
        draft_prompt_ids=_PROFILE_CANDIDATE_PROMPT_IDS,
    )

    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_port=sqlite_checkpoint(tmp_path / "checkpoints-six-role-only.db"),
        prompt_manifest_path=manifest_path,
    )
    try:
        assert runtime.graph_profile() is GraphProfile.SIX_ROLE_BASELINE
    finally:
        runtime.close()
