"""Real production-composition LangGraph certification scenarios."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from tests.support.fakes.langgraph_e2e import LangGraphE2EGeminiTransport
from tests.support.production_runtime import build_test_production_container

from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.api import composition
from google_work_agent.api.app import create_app
from google_work_agent.api.container import ApiContainer

_BOOTSTRAP_SECRET = "langgraph-real-production-e2e-bootstrap"
_SERVICE_INSTANCE_ID = "langgraph-real-production-e2e-service"
_API_HEADERS = {
    "Origin": "http://127.0.0.1:8000",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_answer_only__reaches_terminal_through__real_production_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        tmp_path / "answer-only" / profile.value,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as client:
        _bootstrap(client)
        conversation_id = _create_conversation(client, "answer-only")
        run_id = _start_run(client, conversation_id, "E2E:ANSWER_ONLY explain status")
        snapshot = _wait_for_status(client, run_id, {"COMPLETED"})

    assert snapshot["terminal_result_kind"] == "SUCCESS"
    assert snapshot["actions"] == []
    final_messages = [
        str(message["content"])
        for message in cast(list[dict[str, object]], snapshot["messages"])
        if message["role"] == "ASSISTANT"
    ]
    assert final_messages == ["현재 요청을 처리할 준비가 되어 있습니다."]
    invoked = {
        str(item["prompt_id"]) for item in transport.invocations if item.get("kind") == "invoke"
    }
    assert {
        "request_understanding.identify_goal",
        "request_understanding.detect_ambiguity",
        "planning.outline_answer",
        "planning.compose_answer",
    }.issubset(invoked)
    assert not any(prompt_id.startswith("tool_routing.") for prompt_id in invoked)
    assert not any(prompt_id.startswith("retrieval.") for prompt_id in invoked)
    assert not any(prompt_id.startswith("work_analysis.") for prompt_id in invoked)
    assert not any(prompt_id.startswith("review.") for prompt_id in invoked)


@pytest.mark.parametrize(
    ("scenario", "expected_tool"),
    [
        ("GMAIL_READ", "gmail_search_threads"),
        ("TASKS_READ", "tasks_list_tasks"),
        ("CALENDAR_READ", "calendar_list_events"),
    ],
)
@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_google_reads_reach__terminal_through_actual__retrieval_and_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_tool: str,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / scenario.lower() / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as client:
        _bootstrap(client)
        conversation_id = _create_conversation(client, scenario.lower())
        run_id = _start_run(client, conversation_id, f"E2E:{scenario} read evidence")
        snapshot = _wait_for_status(client, run_id, {"COMPLETED"})
        checkpoint_port = container.checkpoint_port
        assert checkpoint_port is not None
        retrieval_head = checkpoint_port.load_retrieval_head(run_id)
        workflow_binding = checkpoint_port.load_workflow_binding(run_id)

    assert snapshot["terminal_result_kind"] == "SUCCESS"
    assert snapshot["actions"] == []
    final_messages = [
        str(message["content"])
        for message in cast(list[dict[str, object]], snapshot["messages"])
        if message["role"] == "ASSISTANT"
    ]
    assert final_messages == [
        {
            "GMAIL_READ": "선택한 메일의 핵심 내용은 deterministic Gmail evidence입니다.",
            "TASKS_READ": "확인한 태스크의 핵심 내용은 E2E task입니다.",
            "CALENDAR_READ": "확인한 일정의 핵심 내용은 E2E event입니다.",
        }[scenario]
    ]
    assert workflow_binding is not None
    assert retrieval_head is not None
    assert retrieval_head.run_id == run_id
    assert retrieval_head.langgraph_thread_id == workflow_binding.langgraph_thread_id
    assert retrieval_head.retrieval_revision >= 1
    assert retrieval_head.retrieval_artifact_id
    read_events = [
        event for event in _mcp_events(runtime_root) if event["tool_name"] == expected_tool
    ]
    assert len(read_events) == 1
    invoked = {
        str(item["prompt_id"])
        for item in transport.invocations
        if item.get("kind") == "invoke"
    }
    assert "tool_routing.select_tool_if_needed" not in invoked
    assert "retrieval.plan_query" in invoked
    assert not any(prompt_id.startswith("work_analysis.") for prompt_id in invoked)


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_selected_gmail_resource__uses_exact_detail__without_routing_or_query_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "selected-gmail-read" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as client:
        _bootstrap(client)
        resources = client.get(
            "/api/v1/resources/gmail",
            params={"query": "E2E", "page_size": 1},
            headers={"X-API-Contract-Version": "1"},
        )
        assert resources.status_code == 200, resources.text
        item = cast(list[dict[str, object]], resources.json()["items"])[0]
        run_id = _start_run(
            client,
            _create_conversation(client, "selected-gmail-read"),
            "E2E:GMAIL_READ summarize selected evidence",
            entry_mode="RESOURCE_SELECTED",
            selected_resource_handles=[str(item["selection_handle"])],
        )
        snapshot = _wait_for_status(client, run_id, {"COMPLETED"})

    assert snapshot["terminal_result_kind"] == "SUCCESS"
    assert any(
        "deterministic Gmail evidence" in str(message["content"])
        for message in cast(list[dict[str, object]], snapshot["messages"])
        if message["role"] == "ASSISTANT"
    )
    names = [event["tool_name"] for event in _mcp_events(runtime_root)]
    assert names.count("gmail_search_threads") == 1  # Sidebar listing only.
    assert names.count("gmail_get_thread") == 1
    invoked = [
        str(item["prompt_id"])
        for item in transport.invocations
        if item.get("kind") == "invoke"
    ]
    assert "tool_routing.select_tool_if_needed" not in invoked
    assert not any(prompt_id.startswith("retrieval.") for prompt_id in invoked)
    assert not any(prompt_id.startswith("work_analysis.") for prompt_id in invoked)
    assert invoked == [
        "request_understanding.identify_goal",
        "planning.outline_answer",
        "planning.compose_answer",
    ]


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_approved_write_executes__claims_and_verifies__through_real_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "approved-write" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as client:
        _bootstrap(client)
        conversation_id = _create_conversation(client, "approved-write")
        run_id = _start_run(client, conversation_id, "E2E:APPROVED_WRITE create task")
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        actions = cast(list[dict[str, object]], waiting["actions"])
        assert len(actions) == 1
        approval = client.post(
            f"/api/v1/actions/{actions[0]['action_id']}/approve",
            json={
                "api_contract_version": "1",
                "command_id": "approve-e2e-write",
                "expected_version": actions[0]["version"],
            },
        )
        assert approval.status_code == 200, approval.text
        completed = _wait_for_status(client, run_id, {"COMPLETED"})

    assert completed["terminal_result_kind"] == "SUCCESS"
    events = _mcp_events(runtime_root)
    names = [event["tool_name"] for event in events]
    assert names.count("tasks_create_task") == 1
    assert "tasks_get_task" in names
    write_arguments = next(
        cast(dict[str, object], event["arguments"])
        for event in events
        if event["tool_name"] == "tasks_create_task"
    )
    assert isinstance(write_arguments.get("claim_context"), dict)
    invoked = {
        str(item["prompt_id"])
        for item in transport.invocations
        if item.get("kind") == "invoke"
    }
    assert "tool_routing.select_tool_if_needed" not in invoked
    assert "retrieval.plan_query" in invoked
    assert "work_analysis.extract_work_facts" in invoked
    assert "work_analysis.detect_duplicate_conflict_candidates" not in invoked
    assert "review.inspect_action_scope_and_route" in invoked
    assert "review.inspect_constraints_and_policy_summary" not in invoked


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_partial_approval__executes_only__the_approved_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "partial-approval" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as client:
        _bootstrap(client)
        conversation_id = _create_conversation(client, "partial-approval")
        run_id = _start_run(client, conversation_id, "E2E:PARTIAL_APPROVAL create both")
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        actions = cast(list[dict[str, object]], waiting["actions"])
        assert len(actions) == 2
        task_action = next(item for item in actions if item["tool_name"] == "tasks_create_task")
        calendar_action = next(
            item for item in actions if item["tool_name"] == "calendar_create_event"
        )
        _approve_action(client, task_action, "approve-partial-task")
        _reject_action(client, calendar_action, "reject-partial-calendar")
        completed = _wait_for_status(client, run_id, {"COMPLETED"})

    assert completed["terminal_result_kind"] == "PARTIAL"
    names = [event["tool_name"] for event in _mcp_events(runtime_root)]
    assert names.count("tasks_create_task") == 1
    assert "calendar_create_event" not in names


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_rejection_finishes__without_external__write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "rejection" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as client:
        _bootstrap(client)
        conversation_id = _create_conversation(client, "rejection")
        run_id = _start_run(client, conversation_id, "E2E:REJECTION create task")
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        action = cast(list[dict[str, object]], waiting["actions"])[0]
        _reject_action(client, action, "reject-e2e-write")
        completed = _wait_for_status(client, run_id, {"COMPLETED"})

    assert completed["terminal_result_kind"] == "PARTIAL"
    assert "tasks_create_task" not in [event["tool_name"] for event in _mcp_events(runtime_root)]


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_cancel_preempts__waiting_approval__without_external_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "cancel" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as client:
        _bootstrap(client)
        conversation_id = _create_conversation(client, "cancel")
        run_id = _start_run(client, conversation_id, "E2E:CANCEL create task")
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        response = client.post(
            f"/api/v1/runs/{run_id}/cancel",
            json={
                "api_contract_version": "1",
                "command_id": "cancel-e2e-run",
                "expected_version": cast(dict[str, object], waiting["run"])["version"],
            },
        )
        assert response.status_code == 200, response.text
        cancelled = _wait_for_status(client, run_id, {"CANCELLED"})

    assert cancelled["terminal_result_kind"] == "CANCELLED"
    assert "tasks_create_task" not in [event["tool_name"] for event in _mcp_events(runtime_root)]


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_failed_not_sent__write_can_be__retried_with_fresh_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "failed-retry" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container), base_url="http://127.0.0.1:8000", headers=_API_HEADERS
    ) as client:
        _bootstrap(client)
        run_id = _start_run(
            client,
            _create_conversation(client, "failed-retry"),
            "E2E:FAILED_RETRY create task",
        )
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        action = cast(list[dict[str, object]], waiting["actions"])[0]
        _approve_action(client, action, "approve-failed-retry-1")
        failed = _wait_for_action_status(client, run_id, {"FAILED"})
        failed_action = cast(list[dict[str, object]], failed["actions"])[0]
        prepared = client.post(
            f"/api/v1/actions/{failed_action['action_id']}/prepare-retry",
            json={
                "api_contract_version": "1",
                "command_id": "prepare-failed-retry",
                "expected_version": failed_action["version"],
            },
        )
        assert prepared.status_code == 200, prepared.text
        reviewed = _wait_for_action_command(client, run_id, "APPROVE_ACTION")
        retry_action = cast(list[dict[str, object]], reviewed["actions"])[0]
        _approve_action(client, retry_action, "approve-failed-retry-2")
        completed = _wait_for_status(client, run_id, {"COMPLETED"})

    assert completed["terminal_result_kind"] == "SUCCESS"
    names = [event["tool_name"] for event in _mcp_events(runtime_root)]
    assert names.count("tasks_create_task") == 2


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_unknown_result__recovers_without__blind_resend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "unknown-result" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container), base_url="http://127.0.0.1:8000", headers=_API_HEADERS
    ) as client:
        _bootstrap(client)
        run_id = _start_run(
            client,
            _create_conversation(client, "unknown-result"),
            "E2E:UNKNOWN_RESULT create task",
        )
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        _approve_action(
            client,
            cast(list[dict[str, object]], waiting["actions"])[0],
            "approve-unknown-result",
        )
        completed = _wait_for_status(client, run_id, {"COMPLETED"}, timeout_seconds=30)

    assert completed["terminal_result_kind"] == "SUCCESS"
    names = [event["tool_name"] for event in _mcp_events(runtime_root)]
    assert names.count("tasks_create_task") == 1
    assert "search_by_recovery_fingerprint" in names


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_verification_mismatch__requires_explicit__partial_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "verification-mismatch" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container), base_url="http://127.0.0.1:8000", headers=_API_HEADERS
    ) as client:
        _bootstrap(client)
        run_id = _start_run(
            client,
            _create_conversation(client, "verification-mismatch"),
            "E2E:VERIFICATION_MISMATCH create event",
        )
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        action = cast(list[dict[str, object]], waiting["actions"])[0]
        _approve_action(
            client,
            action,
            "approve-verification-mismatch",
            calendar_conflict_acknowledged=True,
        )
        recovery = _wait_for_status(client, run_id, {"RECOVERY_REQUIRED"})
        current_action = cast(list[dict[str, object]], recovery["actions"])[0]
        response = client.post(
            f"/api/v1/runs/{run_id}/resolve-recovery",
            json={
                "api_contract_version": "1",
                "command_id": "accept-verification-mismatch",
                "expected_version": cast(dict[str, object], recovery["run"])["version"],
                "target": {
                    "target_kind": "ACTION",
                    "action_id": current_action["action_id"],
                },
                "resolution_kind": "ACCEPT_PARTIAL",
            },
        )
        assert response.status_code == 200, response.text
        completed = _wait_for_status(client, run_id, {"COMPLETED"})

    assert completed["terminal_result_kind"] == "PARTIAL"
    names = [event["tool_name"] for event in _mcp_events(runtime_root)]
    assert names.count("calendar_create_event") == 1
    invoked = {
        str(item["prompt_id"])
        for item in transport.invocations
        if item.get("kind") == "invoke"
    }
    assert "work_analysis.detect_duplicate_conflict_candidates" not in invoked


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_reauth_restores_safe__retry_and_completes__after_fresh_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "reauth" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container), base_url="http://127.0.0.1:8000", headers=_API_HEADERS
    ) as client:
        _bootstrap(client)
        run_id = _start_run(
            client,
            _create_conversation(client, "reauth"),
            "E2E:REAUTH create task",
        )
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        _approve_action(
            client, cast(list[dict[str, object]], waiting["actions"])[0], "approve-reauth"
        )
        reauth = _wait_for_status(client, run_id, {"REAUTH_REQUIRED"})
        response = client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={
                "api_contract_version": "1",
                "command_id": "resume-reauth",
                "expected_version": cast(dict[str, object], reauth["run"])["version"],
                "resume_kind": "REAUTH_COMPLETED",
            },
        )
        assert response.status_code == 200, response.text
        restored = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        failed_action = cast(list[dict[str, object]], restored["actions"])[0]
        assert failed_action["status"] == "FAILED"
        prepared = client.post(
            f"/api/v1/actions/{failed_action['action_id']}/prepare-retry",
            json={
                "api_contract_version": "1",
                "command_id": "prepare-reauth-retry",
                "expected_version": failed_action["version"],
            },
        )
        assert prepared.status_code == 200, prepared.text
        reviewed = _wait_for_action_command(client, run_id, "APPROVE_ACTION")
        retry_action = cast(list[dict[str, object]], reviewed["actions"])[0]
        _approve_action(client, retry_action, "approve-reauth-retry")
        completed = _wait_for_status(client, run_id, {"COMPLETED"})

    assert completed["terminal_result_kind"] == "SUCCESS"
    names = [event["tool_name"] for event in _mcp_events(runtime_root)]
    assert names.count("tasks_create_task") == 2


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_recovery_recheck__resumes_verification__without_repeating_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "recovery" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container), base_url="http://127.0.0.1:8000", headers=_API_HEADERS
    ) as client:
        _bootstrap(client)
        run_id = _start_run(
            client,
            _create_conversation(client, "recovery"),
            "E2E:RECOVERY create event",
        )
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        _approve_action(
            client,
            cast(list[dict[str, object]], waiting["actions"])[0],
            "approve-recovery",
            calendar_conflict_acknowledged=True,
        )
        recovery = _wait_for_status(client, run_id, {"RECOVERY_REQUIRED"})
        recovery_projection = cast(dict[str, object], recovery["recovery"])
        assert "RECHECK" in cast(
            list[str], recovery_projection["allowed_resolution_kinds"]
        )
        response = client.post(
            f"/api/v1/runs/{run_id}/resolve-recovery",
            json={
                "api_contract_version": "1",
                "command_id": "recheck-recovery",
                "expected_version": cast(dict[str, object], recovery["run"])["version"],
                "target": recovery_projection["target"],
                "resolution_kind": "RECHECK",
            },
        )
        assert response.status_code == 200, response.text
        completed = _wait_for_status(client, run_id, {"COMPLETED"})

    assert completed["terminal_result_kind"] == "SUCCESS"
    names = [event["tool_name"] for event in _mcp_events(runtime_root)]
    assert names.count("calendar_create_event") == 1
    assert names.count("calendar_get_event") == 2


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_restart_recreates__production_composition_and__resumes_durable_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "restart-resume" / profile.value
    first_transport = LangGraphE2EGeminiTransport()
    first_container = _build_container(
        runtime_root,
        transport=first_transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(first_container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as first_client:
        _bootstrap(first_client)
        run_id = _start_run(
            first_client,
            _create_conversation(first_client, "restart-resume"),
            "E2E:RESTART_RESUME create task",
        )
        interrupted = _wait_for_status(first_client, run_id, {"WAITING_CONFIRMATION"})
        original_interrupt = cast(dict[str, object], interrupted["pending_interrupt"])

    second_transport = LangGraphE2EGeminiTransport()
    second_container = _build_container(
        runtime_root,
        transport=second_transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    assert second_container is not first_container
    with TestClient(
        create_app(second_container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as second_client:
        _bootstrap(second_client, command_suffix="restart")
        restored = _wait_for_status(second_client, run_id, {"WAITING_CONFIRMATION"})
        restored_interrupt = cast(dict[str, object], restored["pending_interrupt"])
        assert restored_interrupt["interrupt_id"] == original_interrupt["interrupt_id"]
        response = second_client.post(
            f"/api/v1/runs/{run_id}/confirm",
            json={
                "api_contract_version": "1",
                "command_id": "confirm-after-restart",
                "expected_version": cast(dict[str, object], restored["run"])["version"],
                "interrupt_id": restored_interrupt["interrupt_id"],
                "response_kind": "FREE_TEXT",
                "selected_option": None,
                "free_text": "Use task-list-e2e.",
            },
        )
        assert response.status_code == 200, response.text
        waiting = _wait_for_status(second_client, run_id, {"WAITING_APPROVAL"})
        _approve_action(
            second_client,
            cast(list[dict[str, object]], waiting["actions"])[0],
            "approve-after-restart",
        )
        completed = _wait_for_status(second_client, run_id, {"COMPLETED"})

    assert completed["terminal_result_kind"] == "SUCCESS"
    names = [event["tool_name"] for event in _mcp_events(runtime_root)]
    assert names.count("tasks_create_task") == 1


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_retrieval_cache_loss__restarts_from_durable__checkpoint_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "retrieval-cache-loss" / profile.value
    first_transport = LangGraphE2EGeminiTransport(
        crash_prompt_id="retrieval.select_evidence"
    )
    first_container = _build_container(
        runtime_root,
        transport=first_transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(first_container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as first_client:
        _bootstrap(first_client)
        run_id = _start_run(
            first_client,
            _create_conversation(first_client, "retrieval-cache-loss"),
            "E2E:RETRIEVAL_CACHE_LOSS create task",
        )
        _wait_for_prompt(first_transport, "retrieval.select_evidence")
        interrupted = _wait_for_status(first_client, run_id, {"RETRIEVING"})
        assert cast(dict[str, object], interrupted["run"])["finished_at_ms"] is None

    second_transport = LangGraphE2EGeminiTransport()
    second_container = _build_container(
        runtime_root,
        transport=second_transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    assert second_container is not first_container
    with TestClient(
        create_app(second_container),
        base_url="http://127.0.0.1:8000",
        headers=_API_HEADERS,
    ) as second_client:
        _bootstrap(second_client, command_suffix="cache-restart")
        replanned = _wait_for_status(second_client, run_id, {"WAITING_APPROVAL"})
        replanned_action = cast(list[dict[str, object]], replanned["actions"])[0]
        assert replanned_action["status"] in {"PROPOSED", "MODIFIED"}
        assert "tasks_create_task" not in [
            event["tool_name"] for event in _mcp_events(runtime_root)
        ]
        _approve_action(second_client, replanned_action, "approve-after-cache-restart")
        completed = _wait_for_status(second_client, run_id, {"COMPLETED"})

    assert completed["terminal_result_kind"] == "SUCCESS"
    names = [event["tool_name"] for event in _mcp_events(runtime_root)]
    assert names.count("tasks_create_task") == 1


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_review_issue__uses_real_back__edge_before_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "review-back-edge" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container), base_url="http://127.0.0.1:8000", headers=_API_HEADERS
    ) as client:
        _bootstrap(client)
        run_id = _start_run(
            client,
            _create_conversation(client, "review-back-edge"),
            "E2E:REVIEW_BACK_EDGE create task",
        )
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        _approve_action(
            client,
            cast(list[dict[str, object]], waiting["actions"])[0],
            "approve-review-back-edge",
        )
        completed = _wait_for_status(client, run_id, {"COMPLETED"})

    prompt_ids = [
        str(item["prompt_id"])
        for item in transport.invocations
        if item.get("kind") == "invoke"
    ]
    assert "review.recheck_affected_dimensions" in prompt_ids
    assert completed["terminal_result_kind"] == "SUCCESS"
    assert [event["tool_name"] for event in _mcp_events(runtime_root)].count(
        "tasks_create_task"
    ) == 1


@pytest.mark.parametrize("profile", tuple(GraphProfile))
def test_context_adjustment__reenters_retrieval_and__requires_revised_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> None:
    runtime_root = tmp_path / "context-adjustment" / profile.value
    transport = LangGraphE2EGeminiTransport()
    container = _build_container(
        runtime_root,
        transport=transport,
        monkeypatch=monkeypatch,
        profile=profile,
    )
    with TestClient(
        create_app(container), base_url="http://127.0.0.1:8000", headers=_API_HEADERS
    ) as client:
        _bootstrap(client)
        run_id = _start_run(
            client,
            _create_conversation(client, "context-adjustment"),
            "E2E:CONTEXT_ADJUSTMENT create task",
        )
        waiting = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        preview = cast(dict[str, object], waiting["context_preview"])
        assert preview["adjustment_allowed"] is True
        response = client.post(
            f"/api/v1/runs/{run_id}/context-adjustments",
            json={
                "schema_version": 1,
                "command_id": "adjust-context-e2e",
                "expected_version": cast(dict[str, object], waiting["run"])["version"],
                "expected_retrieval_revision": preview["retrieval_revision"],
                "adjustment_kind": "RETRIEVE_MORE",
                "segment_ids": None,
                "requested_information": "Retrieve additional deterministic E2E evidence.",
            },
        )
        assert response.status_code == 200, response.text
        revised = _wait_for_status(client, run_id, {"WAITING_APPROVAL"})
        revised_preview = cast(dict[str, object], revised["context_preview"])
        assert cast(int, revised_preview["retrieval_revision"]) > cast(
            int, preview["retrieval_revision"]
        )
        _approve_action(
            client,
            cast(list[dict[str, object]], revised["actions"])[0],
            "approve-revised-context",
        )
        completed = _wait_for_status(client, run_id, {"COMPLETED"})

    retrieval_prompts = [
        item
        for item in transport.invocations
        if item.get("prompt_id") == "retrieval.plan_query"
    ]
    assert len(retrieval_prompts) >= 2
    assert completed["terminal_result_kind"] == "SUCCESS"
    assert [event["tool_name"] for event in _mcp_events(runtime_root)].count(
        "tasks_create_task"
    ) == 1


def _build_container(
    runtime_root: Path,
    *,
    transport: LangGraphE2EGeminiTransport,
    monkeypatch: pytest.MonkeyPatch,
    profile: GraphProfile,
) -> ApiContainer:
    monkeypatch.setattr(composition, "GeminiHTTPClient", lambda: transport)
    container = build_test_production_container(
        runtime_root=runtime_root,
        bootstrap_secret=_BOOTSTRAP_SECRET,
        service_instance_id=_SERVICE_INSTANCE_ID,
        mcp_module_name="tests.fakes.langgraph_e2e_mcp_server",
        keyring_store=SessionMemorySecretStore(),
        graph_profile=profile,
    )
    return replace(container, client_address_resolver=lambda _request: "127.0.0.1")


def _bootstrap(client: TestClient, *, command_suffix: str = "initial") -> None:
    bootstrap = client.post(
        "/api/v1/session/bootstrap",
        json={
            "schema_version": 1,
            "bootstrap_secret": _BOOTSTRAP_SECRET,
            "frontend_api_contract_version": "1",
        },
    )
    assert bootstrap.status_code == 200, bootstrap.text
    credential = client.put(
        "/api/v1/credentials/llm/gemini",
        json={
            "schema_version": 1,
            "command_id": f"e2e-store-gemini-{command_suffix}",
            "api_key": "e2e-gemini-key",
            "storage_mode": "SESSION_ONLY",
        },
    )
    assert credential.status_code == 200, credential.text
    settings = client.put(
        "/api/v1/settings",
        headers={"X-API-Contract-Version": "1"},
        json={
            "schema_version": 1,
            "command_id": "e2e-settings",
            "settings_patch": {
                "schema_version": 1,
                "preferred_llm_mode": "API_LLM",
                "external_llm_consent": True,
                "default_tasklist_id": "task-list-e2e",
                "default_calendar_id": "calendar-e2e",
            },
        },
    )
    assert settings.status_code == 200, settings.text


def _create_conversation(client: TestClient, suffix: str) -> str:
    response = client.post(
        "/api/v1/conversations",
        json={
            "schema_version": 1,
            "command_id": f"create-conversation-{suffix}",
            "title": f"E2E {suffix}",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["conversation_id"])


def _start_run(
    client: TestClient,
    conversation_id: str,
    request_text: str,
    *,
    entry_mode: str = "AGENT_SEARCH",
    selected_resource_handles: list[str] | None = None,
) -> str:
    response = client.post(
        "/api/v1/runs",
        json={
            "api_contract_version": "1",
            "command_id": f"start-{request_text.split(':', maxsplit=1)[-1].split()[0].lower()}",
            "conversation_id": conversation_id,
            "request_text": request_text,
            "entry_mode": entry_mode,
            "selected_resource_handles": selected_resource_handles or [],
            "requested_mode": "API_LLM",
        },
    )
    assert response.status_code == 202, response.text
    return str(response.json()["run_id"])


def _approve_action(
    client: TestClient,
    action: dict[str, object],
    command_id: str,
    *,
    calendar_conflict_acknowledged: bool = False,
) -> None:
    response = client.post(
        f"/api/v1/actions/{action['action_id']}/approve",
        json={
            "api_contract_version": "1",
            "command_id": command_id,
            "expected_version": action["version"],
            "calendar_conflict_acknowledged": calendar_conflict_acknowledged,
        },
    )
    assert response.status_code == 200, response.text


def _reject_action(client: TestClient, action: dict[str, object], command_id: str) -> None:
    response = client.post(
        f"/api/v1/actions/{action['action_id']}/reject",
        json={
            "api_contract_version": "1",
            "command_id": command_id,
            "expected_version": action["version"],
            "reason_code": "USER_REJECTED",
        },
    )
    assert response.status_code == 200, response.text


def _wait_for_status(
    client: TestClient,
    run_id: str,
    expected: set[str],
    *,
    timeout_seconds: float = 20,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/runs/{run_id}",
            headers={"X-API-Contract-Version": "1"},
        )
        assert response.status_code == 200, response.text
        last = cast(dict[str, object], response.json())
        run = last.get("run")
        if isinstance(run, dict) and run.get("status") in expected:
            return last
        time.sleep(0.02)
    raise AssertionError(f"run did not reach {sorted(expected)}: {last}")


def _wait_for_action_status(
    client: TestClient,
    run_id: str,
    expected: set[str],
    *,
    timeout_seconds: float = 20,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/runs/{run_id}",
            headers={"X-API-Contract-Version": "1"},
        )
        assert response.status_code == 200, response.text
        last = cast(dict[str, object], response.json())
        actions = last.get("actions")
        if isinstance(actions, list) and any(
            isinstance(action, dict) and action.get("status") in expected for action in actions
        ):
            return last
        time.sleep(0.02)
    raise AssertionError(f"action did not reach {sorted(expected)}: {last}")


def _wait_for_prompt(
    transport: LangGraphE2EGeminiTransport,
    prompt_id: str,
    *,
    timeout_seconds: float = 20,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if any(
            item.get("kind") == "invoke" and item.get("prompt_id") == prompt_id
            for item in transport.invocations
        ):
            return
        time.sleep(0.02)
    raise AssertionError(f"external LLM fake did not reach {prompt_id}")


def _wait_for_action_command(
    client: TestClient,
    run_id: str,
    expected_command: str,
    *,
    timeout_seconds: float = 20,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/runs/{run_id}",
            headers={"X-API-Contract-Version": "1"},
        )
        assert response.status_code == 200, response.text
        last = cast(dict[str, object], response.json())
        actions = last.get("actions")
        if isinstance(actions, list) and any(
            isinstance(action, dict)
            and expected_command in cast(list[str], action.get("next_allowed_commands", []))
            for action in actions
        ):
            return last
        time.sleep(0.02)
    raise AssertionError(f"action did not allow {expected_command}: {last}")


def _mcp_events(runtime_root: Path) -> list[dict[str, object]]:
    path = runtime_root / "cache" / "langgraph-e2e-mcp-events.jsonl"
    assert path.is_file(), f"MCP event log was not created: {path}"
    return [cast(dict[str, object], json.loads(line)) for line in path.read_text().splitlines()]
