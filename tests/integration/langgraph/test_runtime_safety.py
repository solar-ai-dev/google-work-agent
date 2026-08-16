"""Approval and preflight safety integration tests."""

from __future__ import annotations

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    FakeGoogleGateway,
    GraphProfile,
    Path,
    ProductFixtureSnapshotLoader,
    RejectWriteActionCommand,
    RejectWriteActionService,
    WorkflowCorrelationContext,
    WorkflowOutcome,
    WorkflowResumeRequest,
    _action_required_intent,
    _analysis_output,
    _make_runtime,
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


@pytest.mark.parametrize(
    ("profile", "profile_nodes"),
    [
        (
            # "acquisition" is a registered GraphNodeBindings callable (used
            # by _node_handler lookups and other profiles) but is not part
            # of SIX_ROLE_BASELINE's own topology -- WorkflowGraphComposition
            # .build() only calls graph.add_node() for _topology's own
            # entries plus the fixed shared-node list, so it is never
            # compiled into this profile's StateGraph (Retrieval V2's
            # context_retriever replaced it here).
            GraphProfile.SIX_ROLE_BASELINE,
            {
                "request_understanding",
                "context_retriever",
                "work_analysis",
                "planning",
                "review",
            },
        ),
        (GraphProfile.THREE_STAGE, {"stage_one", "stage_two", "stage_three"}),
        (GraphProfile.SINGLE_BASELINE, {"single_workflow"}),
    ],
)
def test_compiled_graph_registers_profile_and_shared_nodes(
    tmp_path: Path,
    profile: GraphProfile,
    profile_nodes: set[str],
) -> None:
    root = tmp_path / profile.value.lower()
    root.mkdir()
    runtime = _make_runtime(
        database_path=_seed_runtime_database(root),
        llm_payloads=[],
        gateway=FakeGoogleGateway(
            ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
        ),
        checkpoint_database_path=root / "checkpoints-topology-edge.db",
        graph_profile=profile,
        prompt_manifest_path=_runtime_active_manifest_path(root),
    )

    try:
        graph = runtime._graph.get_graph()  # noqa: SLF001
        shared = {
            "domain_validation",
            "waiting_confirmation",
            "waiting_approval",
            "action_execution",
            "recovery",
            "finalize",
        }
        assert profile_nodes | shared <= set(graph.nodes)
        assert any(edge.target == "action_execution" for edge in graph.edges)
        assert any(edge.source == "action_execution" for edge in graph.edges)
    finally:
        runtime.close()


def test_edge_rejected_approval_never_enters_preflight_or_claim(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _action_required_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-rejected-edge.db",
        prompt_manifest_path=manifest_path,
    )

    try:
        assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
        preflight_reads_before_resume = gateway.count_calls("list_tasks")
        rejected = RejectWriteActionService(
            unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
            now_ms=lambda: 1000,
        )(
            RejectWriteActionCommand(
                command_id="reject-edge",
                request_hash="c" * 64,
                action_id="action-1",
                expected_version=0,
            )
        )
        assert rejected["applied"] is True

        runtime.resume(
            WorkflowResumeRequest(
                run_id="run-1",
                workflow_key="thread-1",
                resume_kind="APPROVAL",
                resume_payload={"approved": False},
                correlation=WorkflowCorrelationContext(
                    request_id="request-reject-edge",
                    command_id="command-reject-edge",
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
        assert action_status == "REJECTED"
        assert gateway.count_calls("list_tasks") == preflight_reads_before_resume
        assert gateway.count_calls("create_task") == 0
        assert attempt_count == 0
    finally:
        runtime.close()
