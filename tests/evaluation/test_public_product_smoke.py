from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import cast

import pytest
from evaluation.client import ProductApiClient
from evaluation.dataset import load_case
from tests.support.fakes.langgraph_e2e import LangGraphE2EGeminiTransport
from tests.support.production_runtime import build_test_production_container
from uvicorn import Config, Server

# isort: split
from evaluation.runner import run_case, write_result

# isort: split
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.api import composition
from google_work_agent.api.app import create_app


def test_dataset_to_real_product__to_grader_to_result__uses_public_http_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = _loopback_port()
    transport = LangGraphE2EGeminiTransport()
    monkeypatch.setattr(composition, "GeminiHTTPClient", lambda: transport)
    container = build_test_production_container(
        port=port,
        runtime_root=tmp_path / "runtime",
        bootstrap_secret="test-bootstrap",
        mcp_module_name="tests.fakes.langgraph_e2e_mcp_server",
        keyring_store=SessionMemorySecretStore(),
    )
    server = Server(Config(create_app(container), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        client = ProductApiClient(f"http://127.0.0.1:{port}", timeout_seconds=10)
        response = _await_liveness(client)
        assert response["status"] == "LIVE"
        assert response["api_contract_version"] == "1"
        client.bootstrap("test-bootstrap")
        client.store_session_llm_credential(
            provider="gemini", api_key="test-gemini-key", command_id="evaluation-credential"
        )
        client.update_settings(
            command_id="evaluation-settings",
            settings_patch={
                "preferred_llm_mode": "API_LLM",
                "external_llm_consent": True,
            },
        )
        dataset = tmp_path / "answer-only.jsonl"
        dataset.write_text(json.dumps(_answer_only_case()) + "\n", encoding="utf-8")
        result = run_case(
            client,
            case=load_case("EVAL-SMOKE-001", dataset),
            dataset_path=dataset,
            product_sha="a" * 40,
            experiment_name="public-boundary-smoke",
            candidate_id="baseline",
            requested_mode="API_LLM",
        )
        output = tmp_path / "results" / "public-boundary-smoke.json"
        write_result(output, result)
        saved = json.loads(output.read_text(encoding="utf-8"))
        assert saved["metrics"] == {"hard_gate_passed": True, "passed": True}
        assert saved["observed"]["final_answer"] == "E2E completed: ANSWER_ONLY"
        assert saved["observed"]["terminal_state"] == "COMPLETED"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert any(item.get("kind") == "invoke" for item in transport.invocations)


def _answer_only_case() -> dict[str, object]:
    return {
        "case_id": "EVAL-SMOKE-001",
        "canonical_user_prompt": "E2E:ANSWER_ONLY explain status",
        "entry_mode": "AGENT_SEARCH",
        "selected_resource_handles": [],
        "requested_outcome": "ANSWER",
        "required_evidence_ids": [],
        "required_resource_ids": [],
        "forbidden_actions": [],
        "allowed_actions": [],
        "approval_expectation": {"required": False},
        "verification_expectation": {"required": False},
        "expected_interactions": [],
        "expected_tool_trajectory": [],
        "end_state_gold": {
            "terminal_expectation": "COMPLETED",
            "expected_mutations": [],
            "forbidden_mutations": [{"scope": "ALL", "rule": "UNCHANGED"}],
        },
    }


def _await_liveness(client: ProductApiClient) -> dict[str, object]:
    last_error: Exception | None = None
    for _ in range(100):
        try:
            return client.liveness()
        except Exception as error:  # startup polling keeps the final error as context
            last_error = error
            threading.Event().wait(0.05)
    raise AssertionError("Product HTTP service did not start") from last_error


def _loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return cast(int, server.getsockname()[1])
