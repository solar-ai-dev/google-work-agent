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
_TRANSPORT = LangGraphE2EGeminiTransport()


def _build_app() -> FastAPI:
    with patch.object(composition, "GeminiHTTPClient", return_value=_TRANSPORT):
        container = build_test_production_container(
            host=_HOST,
            port=_PORT,
            runtime_root=_RUNTIME_ROOT,
            bootstrap_secret=_BOOTSTRAP_SECRET,
            service_instance_id=_SERVICE_INSTANCE_ID,
            mcp_module_name="tests.fakes.langgraph_e2e_mcp_server",
            keyring_store=SessionMemorySecretStore(),
            graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        )
    container = replace(container, client_address_resolver=lambda _request: _HOST)
    application = create_app(container)
    application.add_api_route(
        "/__e2e__/state/{run_id}",
        _product_state,
        methods=["GET"],
        include_in_schema=False,
    )
    debug_route = application.router.routes.pop()
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
    application.router.routes.insert(frontend_index, debug_route)
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
        run_count = cast(int, connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        command_count = cast(
            int,
            connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0],
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
        "audit_events": audit_events,
        "run_count": run_count,
        "command_count": command_count,
        "mcp_events": _mcp_events(),
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
    if not _MCP_EVENTS_PATH.is_file():
        return []
    return [
        cast(dict[str, object], json.loads(line))
        for line in _MCP_EVENTS_PATH.read_text(encoding="utf-8").splitlines()
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
