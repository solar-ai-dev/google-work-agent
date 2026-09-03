"""Test-only browser Product E2E host using the real production composition."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from fastapi import FastAPI
from tests.support.fakes.langgraph_e2e import LangGraphE2EGeminiTransport
from tests.support.production_runtime import build_test_production_container
from uvicorn import Config, Server

from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.api import composition
from google_work_agent.api.app import create_app

_BOOTSTRAP_SECRET = "browser-product-e2e-bootstrap-secret"
_SERVICE_INSTANCE_ID = "browser-product-e2e-service"
_HOST = "127.0.0.1"
_PORT = int(os.environ.get("GWA_BROWSER_E2E_PORT", "18765"))
_RUNTIME_ROOT = Path(os.environ["GWA_BROWSER_E2E_RUNTIME_ROOT"]).resolve()
_DATABASE_PATH = _RUNTIME_ROOT / "data" / "google_work_agent.db"
_MCP_EVENTS_PATH = _RUNTIME_ROOT / "cache" / "langgraph-e2e-mcp-events.jsonl"
_MCP_STATE_PATH = _RUNTIME_ROOT / "cache" / "langgraph-e2e-mcp-state.json"
_MCP_RUNTIME_EVENTS_PATH = (
    _RUNTIME_ROOT / "cache" / "langgraph-e2e-mcp-runtime-events.jsonl"
)
_TRANSPORT = LangGraphE2EGeminiTransport(
    crash_prompt_id=os.environ.get("GWA_BROWSER_E2E_CRASH_PROMPT_ID"),
    crash_scenario=os.environ.get("GWA_BROWSER_E2E_CRASH_SCENARIO"),
)
_KEYRING_STORE = SessionMemorySecretStore()
_KEYRING_STORE.put("DEVELOPMENT/llm-api-key/gemini", b"browser-product-e2e-gemini-key")
_CHECKPOINT_PORT: Any | None = None


def _build_app() -> FastAPI:
    global _CHECKPOINT_PORT
    with patch.object(composition, "GeminiHTTPClient", return_value=_TRANSPORT):
        container = build_test_production_container(
            host=_HOST,
            port=_PORT,
            runtime_root=_RUNTIME_ROOT,
            bootstrap_secret=_BOOTSTRAP_SECRET,
            service_instance_id=_SERVICE_INSTANCE_ID,
            mcp_module_name="tests.fakes.langgraph_e2e_mcp_server",
            keyring_store=_KEYRING_STORE,
            graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        )
    _CHECKPOINT_PORT = container.checkpoint_port
    container = replace(container, client_address_resolver=lambda _request: _HOST)
    application = create_app(container)
    test_routes: list[Any] = []
    for path, endpoint, methods in (
        ("/__e2e__/state/{run_id}", _product_state, ["GET"]),
        ("/__e2e__/fault/reauth-complete", _complete_reauth, ["POST"]),
    ):
        application.add_api_route(
            path,
            endpoint,
            methods=methods,
            include_in_schema=False,
        )
        test_routes.append(application.router.routes.pop())
    frontend_index = next(
        (
            index
            for index, route in enumerate(application.router.routes)
            if any(
                getattr(child, "path", None) == "/{path:path}"
                for child in getattr(getattr(route, "original_router", None), "routes", ())
            )
        ),
        len(application.router.routes),
    )
    application.router.routes[frontend_index:frontend_index] = test_routes
    return application


def _product_state(run_id: str) -> dict[str, object]:
    with connect_sqlite(_DATABASE_PATH) as connection:
        run = _one(
            connection,
            """
            SELECT id, conversation_id, status, langgraph_thread_id,
                   terminal_result_kind, finished_at_ms
              FROM runs
             WHERE id = ?
            """,
            (run_id,),
        )
        plans = _all(
            connection,
            "SELECT id, status, revision_no FROM plans WHERE run_id = ? ORDER BY revision_no",
            (run_id,),
        )
        actions = _all(
            connection,
            """
            SELECT a.id, a.tool_name, a.status, a.effect_type, a.connector_id,
                   a.verification_policy, a.position
              FROM actions AS a
              JOIN plans AS p ON p.id = a.plan_id
             WHERE p.run_id = ?
             ORDER BY p.revision_no, a.position
            """,
            (run_id,),
        )
        dependencies = _all(
            connection,
            """
            SELECT d.action_id, d.depends_on_action_id
              FROM action_dependencies AS d
              JOIN actions AS a ON a.id = d.action_id
              JOIN plans AS p ON p.id = a.plan_id
             WHERE p.run_id = ?
             ORDER BY d.action_id, d.depends_on_action_id
            """,
            (run_id,),
        )
        approvals = _all(
            connection,
            """
            SELECT ap.id, ap.action_id, ap.status
              FROM approvals AS ap
              JOIN actions AS a ON a.id = ap.action_id
              JOIN plans AS p ON p.id = a.plan_id
             WHERE p.run_id = ?
             ORDER BY ap.approved_at_ms
            """,
            (run_id,),
        )
        attempts = _all(
            connection,
            """
            SELECT ea.id, ap.action_id, ea.status, ea.attempt_no
              FROM execution_attempts AS ea
              JOIN approvals AS ap ON ap.id = ea.approval_id
              JOIN actions AS a ON a.id = ap.action_id
              JOIN plans AS p ON p.id = a.plan_id
             WHERE p.run_id = ?
             ORDER BY ea.started_at_ms
            """,
            (run_id,),
        )
        verifications = _all(
            connection,
            """
            SELECT v.id, ap.action_id, v.status, v.verification_no
              FROM verifications AS v
              JOIN execution_attempts AS ea ON ea.id = v.execution_attempt_id
              JOIN approvals AS ap ON ap.id = ea.approval_id
              JOIN actions AS a ON a.id = ap.action_id
              JOIN plans AS p ON p.id = a.plan_id
             WHERE p.run_id = ?
             ORDER BY v.verified_at_ms
            """,
            (run_id,),
        )
        messages = _all(
            connection,
            "SELECT id, role, content FROM messages WHERE run_id = ? ORDER BY created_at_ms, id",
            (run_id,),
        )
        workflow_binding = _one(
            connection,
            """
            SELECT workflow_key, langgraph_thread_id, graph_profile, graph_version
              FROM workflow_bindings
             WHERE run_id = ?
            """,
            (run_id,),
        )
        audit_events = _all(
            connection,
            """
            SELECT event_type, outcome, action_id
              FROM audit_events
             WHERE run_id = ?
             ORDER BY id
            """,
            (run_id,),
        )
        recovery = _one(
            connection,
            """
            SELECT reason, scope, action_id, execution_attempt_id, verification_id, version
              FROM recovery_contexts
             WHERE run_id = ?
            """,
            (run_id,),
        )
        workflow_handoffs = _all(
            connection,
            """
            SELECT handoff_id, execution_kind, status, run_sequence,
                   checkpoint_id, checkpoint_generation, applied_checkpoint_generation
              FROM workflow_handoffs
             WHERE run_id = ?
             ORDER BY run_sequence
            """,
            (run_id,),
        )
        run_count = cast(int, connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        command_count = cast(
            int,
            connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0],
        )
        command_receipts = _all(
            connection,
            """
            SELECT command_id, command_type, aggregate_type, aggregate_id, status
              FROM command_receipts
             ORDER BY created_at_ms, command_id
            """,
            (),
        )
    return {
        "run": run,
        "plans": plans,
        "actions": actions,
        "action_dependencies": dependencies,
        "approvals": approvals,
        "execution_attempts": attempts,
        "verifications": verifications,
        "messages": messages,
        "workflow_binding": workflow_binding,
        "workflow_handoffs": workflow_handoffs,
        "checkpoint": _checkpoint_state(run_id),
        "recovery": recovery,
        "audit_events": audit_events,
        "run_count": run_count,
        "command_count": command_count,
        "command_receipts": command_receipts,
        "mcp_events": _mcp_events(),
        "mcp_state": _mcp_state(),
        "mcp_runtime_events": _json_lines(_MCP_RUNTIME_EVENTS_PATH),
        "llm_invocations": [
            {
                "kind": item.get("kind"),
                "prompt_id": item.get("prompt_id"),
                "scenario": item.get("scenario"),
                "has_confirmation_response": _has_confirmation_response(item),
            }
            for item in _TRANSPORT.invocations
        ],
    }


def _complete_reauth() -> dict[str, object]:
    state = _mcp_state()
    state["reauth_required"] = False
    _MCP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _MCP_STATE_PATH.with_suffix(".reauth.tmp")
    temporary_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    temporary_path.replace(_MCP_STATE_PATH)
    return {"reauth_required": False}


def _checkpoint_state(run_id: str) -> dict[str, object]:
    if _CHECKPOINT_PORT is None:
        return {}
    binding = _CHECKPOINT_PORT.load_workflow_binding(run_id)
    if binding is None:
        return {}
    checkpoint = _CHECKPOINT_PORT.load_same_run_checkpoint(
        run_id,
        binding.langgraph_thread_id,
    )
    if checkpoint is None:
        return {}
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "checkpoint_generation": checkpoint.checkpoint_generation,
        "langgraph_thread_id": checkpoint.langgraph_thread_id,
    }


def _has_confirmation_response(invocation: Mapping[str, object]) -> bool:
    prompt_input = invocation.get("prompt_input")
    return isinstance(prompt_input, Mapping) and "confirmation_response" in prompt_input


def _one(connection: Any, query: str, parameters: tuple[object, ...]) -> dict[str, object]:
    row = connection.execute(query, parameters).fetchone()
    if row is None:
        return {}
    return dict(row)


def _all(
    connection: Any, query: str, parameters: tuple[object, ...]
) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def _mcp_events() -> list[dict[str, object]]:
    return _json_lines(_MCP_EVENTS_PATH)


def _mcp_state() -> dict[str, object]:
    if not _MCP_STATE_PATH.is_file():
        return {}
    return cast(
        dict[str, object],
        json.loads(_MCP_STATE_PATH.read_text(encoding="utf-8")),
    )


def _json_lines(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    return [
        cast(dict[str, object], json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


app = _build_app()


def main() -> None:
    Server(
        Config(
            app,
            host=_HOST,
            port=_PORT,
            access_log=False,
            proxy_headers=False,
            server_header=False,
            date_header=False,
        )
    ).run()


if __name__ == "__main__":
    main()
