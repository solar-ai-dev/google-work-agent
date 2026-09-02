from __future__ import annotations

from json import dumps
from pathlib import Path
from typing import cast

from google_work_agent.adapters.connectors.google.workspace.composition import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
    google_workspace_internal_read_binding,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.mcp_connector_read import (
    McpConnectorReadAdapter,
)
from google_work_agent.adapters.connectors.runtime.mcp_connector_write import (
    McpConnectorWriteAdapter,
)
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    sqlite_unit_of_work_factory,
)
from google_work_agent.adapters.system.memory.run_retrieval_cache import (
    InMemoryRunRetrievalCache,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SourceFetchPlanV1,
)
from google_work_agent.application.agents.retrieval.execute_read import execute_read
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.claim.build_claim_context import ClaimContextV2
from google_work_agent.application.use_cases.execution_attempt.dispatch_connector_write import (
    DispatchConnectorWriteCommandV1,
    DispatchConnectorWriteHandler,
)
from google_work_agent.application.use_cases.execution_attempt.recover_existing_result import (
    RecoverExistingResultCommand,
    RecoverExistingResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.store_success import (
    StoreSuccessCommand,
    StoreSuccessHandler,
)
from google_work_agent.application.use_cases.recovery.lookup_unknown_result import (
    LookupUnknownResultHandler,
)
from google_work_agent.application.use_cases.resource_ref.resolve_resource_ref import (
    ResolveResourceRefHandler,
)
from google_work_agent.application.use_cases.run.begin_verification import (
    BeginVerificationCommand,
    BeginVerificationHandler,
)
from google_work_agent.application.use_cases.verification.store_verification import (
    StoreVerificationCommand,
    StoreVerificationHandler,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    VerifyEffectHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourceSnapshot,
    ResourceType,
)
from google_work_agent.ports.connector.mcp_client_port import (
    MCPRestartResultV1,
    MCPRuntimeMetadata,
    MCPToolCallResultV1,
    MCPToolDescriptorV1,
)
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1

_ARGUMENTS: dict[str, object] = {
    "task_list_id": "list-1",
    "payload": {"title": "Task"},
}
_ARGUMENTS_HASH = calculate_canonical_json_hash(_ARGUMENTS)
_RECOVERY_FINGERPRINT = "e" * 64


class _RuntimeHandle:
    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata("RUNNING", "1", "1", "1", 0, None, 0, "mcp-1")

    def list_tools(self) -> list[MCPToolDescriptorV1]:
        return []

    def call_tool(self, tool_id: str, arguments: object, timeout_ms: int) -> MCPToolCallResultV1:
        raise AssertionError((tool_id, arguments, timeout_ms))

    def restart_once(self) -> MCPRestartResultV1:
        return MCPRestartResultV1(1, False, None)

    def close(self) -> None:
        return None


class _DeterministicMcpClient:
    process_instance_id = "mcp-1"

    def __init__(self, descriptors: list[MCPToolDescriptorV1]) -> None:
        self._descriptors = descriptors
        self.calls: list[tuple[str, dict[str, object]]] = []

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        del payload
        return "signature-1"

    def list_tools(self, connector_id: str) -> list[MCPToolDescriptorV1]:
        assert connector_id == GOOGLE_WORKSPACE_CONNECTOR_ID
        return self._descriptors

    def call_tool(
        self,
        connector_id: str,
        tool_id: str,
        arguments: object,
        timeout_ms: int,
    ) -> MCPToolCallResultV1:
        assert connector_id == GOOGLE_WORKSPACE_CONNECTOR_ID
        assert timeout_ms == 30_000
        assert isinstance(arguments, dict)
        call_arguments = cast(dict[str, object], arguments)
        self.calls.append((tool_id, call_arguments))
        if tool_id == "gmail_search_threads":
            payload = {"request_id": "read-1", "items": [], "total_count": 0}
        elif tool_id == "tasks_create_task":
            payload = {
                "request_id": "write-1",
                "item": {
                    "fixture_snapshot_id": "snapshot-1",
                    "resource_type": "task",
                    "resource_id": "task-1",
                    "parent_id": "list-1",
                    "version": "1",
                    "recovery_fingerprint": _RECOVERY_FINGERPRINT,
                    "payload": {"title": "Task"},
                },
            }
        elif tool_id == "tasks_get_task":
            payload = {
                "request_id": "verify-1",
                "item": {
                    "resource_type": "task",
                    "resource_id": call_arguments["task_id"],
                    "parent_id": "list-1",
                    "payload": {"title": "Task", "status": "needsAction"},
                },
            }
        elif tool_id == "search_by_recovery_fingerprint":
            payload = {
                "request_id": "recovery-1",
                "items": [
                    {
                        "resource_id": "task-recovered",
                        "recovery_fingerprint": _RECOVERY_FINGERPRINT,
                    }
                ],
            }
        else:
            raise AssertionError(f"unexpected MCP tool: {tool_id}")
        return MCPToolCallResultV1(1, tool_id, "OK", payload, None)

    def restart_once(self, connector_id: str) -> MCPRestartResultV1:
        assert connector_id == GOOGLE_WORKSPACE_CONNECTOR_ID
        return MCPRestartResultV1(1, False, None)


class _CheckpointFacts:
    def __init__(self) -> None:
        self.binding = WorkflowBindingV1(
            1,
            "workflow-1",
            "run-1",
            "thread-1",
            "SIX_ROLE_BASELINE",
            "graph-v1",
            "AUTO",
            1,
        )
        self.checkpoint = GraphCheckpointEnvelopeV1(
            1,
            "checkpoint-1",
            1,
            "run-1",
            "thread-1",
            "SIX_ROLE_BASELINE",
            "graph-v1",
            "MAIN",
            None,
            None,
            None,
            None,
            None,
            (),
            1,
            b"checkpoint",
        )

    def load_workflow_binding(self, run_id: str) -> WorkflowBindingV1 | None:
        return self.binding if run_id == "run-1" else None

    def load_same_run_checkpoint(
        self, run_id: str, thread_id: str
    ) -> GraphCheckpointEnvelopeV1 | None:
        if (run_id, thread_id) == ("run-1", "thread-1"):
            return self.checkpoint
        return None

    def store_same_run_checkpoint(self, checkpoint: GraphCheckpointEnvelopeV1) -> None:
        self.checkpoint = checkpoint


def _connector_ports() -> tuple[
    SignedToolRegistry,
    _DeterministicMcpClient,
    McpConnectorReadAdapter,
    McpConnectorWriteAdapter,
]:
    registry = load_signed_tool_registry()
    client = _DeterministicMcpClient(
        registry.descriptor_expectations(GOOGLE_WORKSPACE_CONNECTOR_ID)
    )
    runtime_registry = ConnectorRuntimeRegistry()
    runtime_registry.register(GOOGLE_WORKSPACE_CONNECTOR_ID, _RuntimeHandle())
    read_port = McpConnectorReadAdapter(
        runtime_registry=runtime_registry,
        mcp_client=client,
        internal_bindings=(
            google_workspace_internal_read_binding("search_by_recovery_fingerprint"),
        ),
    )
    return (
        registry,
        client,
        read_port,
        McpConnectorWriteAdapter(runtime_registry=runtime_registry, mcp_client=client),
    )


def _seed_write_state(database_path: Path, *, unknown: bool) -> None:
    action_status = "UNKNOWN_RESULT" if unknown else "EXECUTING"
    attempt_status = "UNKNOWN_RESULT" if unknown else "EXECUTING"
    action_version = 3 if unknown else 2
    attempt_version = 2 if unknown else 1
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'WAITING_APPROVAL',
                      'thread-1', 'AUTO', '{}', 0, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO plans (
                id, run_id, revision_no, status, summary_text, created_at_ms,
                review_status, review_version, review_disposition
            ) VALUES ('plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 1,
                      'PASSED', 1, 'PASS');
            """
        )
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, connector_id, position, tool_name, effect_type,
                approval_requirement, verification_policy, recovery_policy, status,
                arguments_json, arguments_hash, expected_json, version,
                created_at_ms, updated_at_ms
            ) VALUES ('action-1', 'plan-1', 'google_workspace', 1, 'tasks_create_task',
                      'CREATE', 'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', ?,
                      ?, ?, ?, ?, 1, 1);
            """,
            (
                action_status,
                dumps(_ARGUMENTS, sort_keys=True),
                _ARGUMENTS_HASH,
                dumps({"payload": {"title": "Task"}}, sort_keys=True),
                action_version,
            ),
        )
        connection.execute(
            """
            INSERT INTO approvals (
                id, action_id, approval_no, action_version, status,
                approved_by_account_id, arguments_snapshot_json,
                canonical_arguments_hash, source_snapshot_json, source_snapshot_hash,
                policy_version, tool_schema_version, idempotency_key,
                recovery_fingerprint, approved_at_ms, expires_at_ms, consumed_at_ms
            ) VALUES ('approval-1', 'action-1', 1, 1, 'CONSUMED', 'account-1',
                      ?, ?, '{}', ?, 'policy-v1', 'schema-v1', ?, ?, 1, 100, 2);
            """,
            (
                dumps(_ARGUMENTS, sort_keys=True),
                _ARGUMENTS_HASH,
                "b" * 64,
                "c" * 64,
                _RECOVERY_FINGERPRINT,
            ),
        )
        connection.execute(
            """
            INSERT INTO execution_attempts (
                id, approval_id, attempt_no, status, version, started_at_ms
            ) VALUES ('attempt-1', 'approval-1', 1, ?, ?, 2);
            """,
            (attempt_status, attempt_version),
        )
        if not unknown:
            connection.execute(
                """
                INSERT INTO command_receipts (
                    command_id, command_type, request_hash, aggregate_type, aggregate_id,
                    status, result_code, result_version, response_json,
                    created_at_ms, completed_at_ms
                ) VALUES ('begin-execution-attempt:attempt-1', 'BeginExecutionAttempt', ?,
                          'ExecutionAttempt', 'attempt-1', 'APPLIED',
                          'TRANSITION_APPLIED', 1, ?, 2, 3);
                """,
                (
                    "d" * 64,
                    dumps(
                        {
                            "applied": True,
                            "attempt_id": "attempt-1",
                            "attempt_status": "EXECUTING",
                        },
                        sort_keys=True,
                    ),
                ),
            )
        connection.commit()


def _snapshot(resource_id: str) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id=f"snapshot-{resource_id}",
        resource_type=ResourceType.TASK,
        resource_id=resource_id,
        parent_id="list-1",
        related_resource_ids=("list-1",),
        version="1",
        recovery_fingerprint=_RECOVERY_FINGERPRINT,
        payload={"title": "Task", "status": "needsAction"},
    )


def _verify_and_store(
    database_path: Path,
    *,
    registry: SignedToolRegistry,
    read_port: McpConnectorReadAdapter,
    action_version: int,
    suffix: str,
) -> None:
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 20)
    checkpoint = _CheckpointFacts()
    begin = BeginVerificationHandler(
        unit_of_work_factory=factory,
        checkpoint_port=cast(CheckpointPort, checkpoint),
        now_ms=lambda: 20,
        resume_target_registry=ResumeTargetRegistry(
            node_registry=NodeRegistry("graph-v1"),
            graph_version="graph-v1",
        ),
    )(
        BeginVerificationCommand(
            f"begin-verification-{suffix}",
            "f" * 64,
            "run-1",
            "action-1",
            "attempt-1",
        )
    )
    assert begin.applied is True
    verifier = VerifyEffectHandler(
        connector_read=read_port,
        tool_registry=registry,
        unit_of_work_factory=factory,
        resolve_resource_ref=ResolveResourceRefHandler(unit_of_work_factory=factory),
    )
    verification = verifier(
        verifier.project_persisted_query(
            run_id="run-1",
            action_id="action-1",
            execution_attempt_id="attempt-1",
        )
    )
    assert verification.status == "VERIFIED"
    stored = StoreVerificationHandler(unit_of_work_factory=factory, now_ms=lambda: 21)(
        StoreVerificationCommand(
            f"store-verification-{suffix}",
            "9" * 64,
            f"verification-{suffix}",
            "run-1",
            "action-1",
            "attempt-1",
            action_version,
            verification,
        )
    )
    assert stored.applied is True
    assert stored.action_status == "VERIFIED"


def test_retrieval_application__uses_connector_read_adapter__through_mcp_port() -> None:
    registry, client, read_port, _write_port = _connector_ports()
    binding = registry.bind_required(GOOGLE_WORKSPACE_CONNECTOR_ID, "gmail_search_threads", "READ")
    plan = cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "route-1",
            "connector_id": GOOGLE_WORKSPACE_CONNECTOR_ID,
            "resource_type": binding.resource_type,
            "operation_kind": "INITIAL",
            "effective_constraints": [],
            "query_identity_hash": "a" * 64,
            "prior_read_result_handle": None,
            "detail_candidate_ref": None,
        },
    )

    result = execute_read(
        plan=plan,
        run_id="run-1",
        binding=binding,
        tool_arguments={"query": "budget"},
        connector_reader=read_port,
        read_result_cache=InMemoryRunRetrievalCache(),
        read_result_handle="read-result-1",
    )

    assert result.status == "COMPLETE"
    assert result.provider_called is True
    assert client.calls == [("gmail_search_threads", {"query": "budget"})]


def test_write_success__crosses_connector_port__then_verifies_with_read_port(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "write-verification-wiring.db"
    _seed_write_state(database_path, unknown=False)
    registry, client, read_port, write_port = _connector_ports()
    claim = ClaimContextV2(
        2,
        "service-1",
        "mcp-1",
        "action-1",
        "approval-1",
        "attempt-1",
        "tasks_create_task",
        _ARGUMENTS_HASH,
        _ARGUMENTS_HASH,
        2,
        100,
        "nonce-1",
        "signature-1",
    )
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)

    dispatched = DispatchConnectorWriteHandler(
        unit_of_work_factory=factory,
        tool_registry=registry,
        connector_write_port=write_port,
    )(
        DispatchConnectorWriteCommandV1(
            "action-1",
            "approval-1",
            "attempt-1",
            "tasks_create_task",
            _ARGUMENTS,
            claim,
        )
    )
    assert dispatched.connector_result.success is True
    assert "claim_context" in client.calls[0][1]
    stored = StoreSuccessHandler(
        unit_of_work_factory=factory,
        now_ms=lambda: 11,
        tool_registry=registry,
    )(
        StoreSuccessCommand(
            "store-success-1",
            "8" * 64,
            "action-1",
            "attempt-1",
            2,
            1,
            _snapshot("task-1"),
        )
    )
    assert stored.action_status == "EXECUTED"

    _verify_and_store(
        database_path,
        registry=registry,
        read_port=read_port,
        action_version=stored.action_version,
        suffix="success",
    )

    assert [tool_id for tool_id, _arguments in client.calls] == [
        "tasks_create_task",
        "tasks_get_task",
    ]
    with connect_sqlite(database_path) as connection:
        facts = connection.execute(
            """
            SELECT
                (SELECT status FROM actions WHERE id='action-1'),
                (SELECT status FROM runs WHERE id='run-1'),
                (SELECT status FROM verifications WHERE id='verification-success');
            """
        ).fetchone()
    assert tuple(facts) == ("VERIFIED", "VERIFYING", "VERIFIED")


def test_unknown_result__uses_read_only_lookup__then_recovers_and_verifies(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "unknown-recovery-wiring.db"
    _seed_write_state(database_path, unknown=True)
    registry, client, read_port, _write_port = _connector_ports()
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 30)
    lookup_handler = LookupUnknownResultHandler(
        connector_read=read_port,
        tool_registry=registry,
        recovery_search_binding=google_workspace_internal_read_binding(
            "search_by_recovery_fingerprint"
        ),
        unit_of_work_factory=factory,
        now_ms=lambda: 30,
    )
    projected = lookup_handler.project_persisted_query(
        run_id="run-1",
        action_id="action-1",
        execution_attempt_id="attempt-1",
        effect="CREATE",
    )
    lookup = lookup_handler(projected.query)
    assert lookup.disposition == "MUTATION_FOUND"
    assert lookup.candidate_resource_refs == ["task-recovered"]

    recovered = RecoverExistingResultHandler(
        unit_of_work_factory=factory,
        now_ms=lambda: 31,
        tool_registry=registry,
    )(
        RecoverExistingResultCommand(
            "recover-existing-1",
            "7" * 64,
            "action-1",
            "attempt-1",
            3,
            2,
            _snapshot("task-recovered"),
        )
    )
    assert recovered.action_status == "EXECUTED"

    _verify_and_store(
        database_path,
        registry=registry,
        read_port=read_port,
        action_version=recovered.action_version,
        suffix="recovery",
    )

    assert [tool_id for tool_id, _arguments in client.calls] == [
        "search_by_recovery_fingerprint",
        "tasks_get_task",
    ]
    with connect_sqlite(database_path) as connection:
        facts = connection.execute(
            """
            SELECT
                (SELECT status FROM actions WHERE id='action-1'),
                (SELECT status FROM execution_attempts WHERE id='attempt-1'),
                (SELECT status FROM command_receipts
                 WHERE command_id LIKE 'system:lookup-unknown-result:%');
            """
        ).fetchone()
    assert tuple(facts) == ("VERIFIED", "SUCCEEDED", "APPLIED")
