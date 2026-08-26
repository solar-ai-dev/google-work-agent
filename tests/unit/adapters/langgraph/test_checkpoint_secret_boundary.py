import asyncio
import sqlite3
from copy import deepcopy
from pathlib import Path
from secrets import token_urlsafe
from typing import Any, TypedDict

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.checkpoint_secret_boundary import (
    SecretBoundaryCheckpointer,
)
from google_work_agent.ports.observability_events import SanitizationError


def _secret(prefix: str) -> str:
    return f"{prefix}-{token_urlsafe(24)}"


def _checkpointer() -> tuple[sqlite3.Connection, SecretBoundaryCheckpointer]:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    return connection, SecretBoundaryCheckpointer(SqliteSaver(connection))


def test_checkpoint_boundary_preserves_allowed_metadata_and_round_trips() -> None:
    connection, checkpointer = _checkpointer()
    try:
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {
            "state": {
                "credential_state": "READY",
                "token_expired": True,
                "page_token_present": True,
                "continuation_hash": "sha256:checkpoint-safe",
                "provider_status_code": 401,
            }
        }
        checkpoint["channel_versions"] = {"state": 1}
        config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
        metadata = {
            "source": "input",
            "step": -1,
            "parents": {},
            "credential_state": "READY",
            "token_expired": True,
            "page_token_present": True,
            "continuation_hash": "sha256:checkpoint-safe",
            "provider_status_code": 401,
        }

        stored_config = checkpointer.put(config, checkpoint, metadata, {"state": 1})
        restored = checkpointer.get_tuple(stored_config)

        assert restored is not None
        state = restored.checkpoint["channel_values"]["state"]
        assert state["credential_state"] == "READY"
        assert state["token_expired"] is True
        assert state["page_token_present"] is True
        assert state["continuation_hash"] == "sha256:checkpoint-safe"
        assert state["provider_status_code"] == 401
        assert restored.metadata["credential_state"] == "READY"
        assert restored.metadata["token_expired"] is True
        assert restored.metadata["page_token_present"] is True
        assert restored.metadata["continuation_hash"] == "sha256:checkpoint-safe"
        assert restored.metadata["provider_status_code"] == 401
    finally:
        connection.close()


def test_checkpoint_boundary_rejects_random_secret_in_checkpoint_metadata_and_writes() -> None:
    connection, checkpointer = _checkpointer()
    try:
        allowed_checkpoint = empty_checkpoint()
        allowed_config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
        stored_config = checkpointer.put(
            allowed_config,
            allowed_checkpoint,
            {"source": "input", "step": -1, "parents": {}},
            {},
        )

        access_token = _secret("access")
        refresh_token = _secret("refresh")
        authorization = f"Bearer {_secret('authorization')}"

        secret_checkpoint = deepcopy(empty_checkpoint())
        secret_checkpoint["channel_values"] = {
            "state": {
                "provider": {
                    "headers": {"Authorization": authorization},
                    "oauth": {
                        "access_token": access_token,
                        "refreshToken": refresh_token,
                    },
                }
            }
        }
        secret_checkpoint["channel_versions"] = {"state": 1}
        with pytest.raises(SanitizationError):
            checkpointer.put(
                allowed_config,
                secret_checkpoint,
                {"source": "loop", "step": 0, "parents": {}},
                {"state": 1},
            )

        with pytest.raises(SanitizationError):
            checkpointer.put(
                allowed_config,
                empty_checkpoint(),
                {
                    "source": "loop",
                    "step": 0,
                    "parents": {},
                    "provider": {"oauth": {"access_token": access_token}},
                },
                {},
            )

        with pytest.raises(SanitizationError):
            checkpointer.put_writes(
                stored_config,
                [("state", {"provider": {"oauth": {"refreshToken": refresh_token}}})],
                "task-1",
            )

        with pytest.raises(SanitizationError):
            checkpointer.put_writes(
                stored_config,
                [("access_token", "opaque-value")],
                "task-2",
            )

        database_dump = "\n".join(connection.iterdump())
        assert access_token not in database_dump
        assert refresh_token not in database_dump
        assert authorization not in database_dump
    finally:
        connection.close()


def test_checkpoint_boundary_rejects_raw_credential_object_fail_closed() -> None:
    class ProviderCredential:
        def __init__(self, secret_value: str) -> None:
            self.access_token = secret_value
            self.expires_at_ms = 1234

    connection, checkpointer = _checkpointer()
    try:
        secret_value = _secret("opaque-credential")
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {
            "state": {"credential_object": ProviderCredential(secret_value)}
        }
        checkpoint["channel_versions"] = {"state": 1}
        config = {"configurable": {"thread_id": "thread-raw", "checkpoint_ns": ""}}

        with pytest.raises(SanitizationError):
            checkpointer.put(
                config,
                checkpoint,
                {"source": "input", "step": -1, "parents": {}},
                {"state": 1},
            )

        database_dump = "\n".join(connection.iterdump())
        assert secret_value not in database_dump
    finally:
        connection.close()


class _CompiledGraphState(TypedDict):
    count: int
    credential_state: str
    token_expired: bool
    page_token_present: bool
    continuation_hash: str
    provider_status_code: int


def _increment_compiled_state(state: _CompiledGraphState) -> dict[str, object]:
    return {"count": state["count"] + 1}


def _compiled_graph(checkpointer: SecretBoundaryCheckpointer) -> Any:
    builder = StateGraph(_CompiledGraphState)
    builder.add_node("increment", _increment_compiled_state)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile(checkpointer=checkpointer)


def test_compiled_graph_checkpoint_positive_round_trip_preserves_allowed_metadata() -> None:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    checkpointer = SecretBoundaryCheckpointer(SqliteSaver(connection))
    graph = _compiled_graph(checkpointer)
    config = {
        "configurable": {"thread_id": "compiled-positive"},
        "metadata": {
            "credential_state": "READY",
            "token_expired": True,
            "page_token_present": True,
            "continuation_hash": "sha256:compiled-safe",
            "provider_status_code": 200,
        },
    }

    try:
        first = graph.invoke(
            {
                "count": 0,
                "credential_state": "READY",
                "token_expired": True,
                "page_token_present": True,
                "continuation_hash": "sha256:compiled-safe",
                "provider_status_code": 200,
            },
            config,
        )
        assert first["count"] == 1

        checkpoint_rows = connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()
        assert checkpoint_rows is not None
        assert checkpoint_rows[0] > 0

        snapshot = graph.get_state(config)
        assert snapshot.values["count"] == 1
        assert snapshot.values["credential_state"] == "READY"
        assert snapshot.values["token_expired"] is True
        assert snapshot.values["page_token_present"] is True
        assert snapshot.values["continuation_hash"] == "sha256:compiled-safe"
        assert snapshot.values["provider_status_code"] == 200
        assert snapshot.metadata["credential_state"] == "READY"
        assert snapshot.metadata["token_expired"] is True
        assert snapshot.metadata["page_token_present"] is True
        assert snapshot.metadata["continuation_hash"] == "sha256:compiled-safe"
        assert snapshot.metadata["provider_status_code"] == 200

        second_input: _CompiledGraphState = {
            "count": first["count"],
            "credential_state": "READY",
            "token_expired": True,
            "page_token_present": True,
            "continuation_hash": "sha256:compiled-safe",
            "provider_status_code": 200,
        }
        second = graph.invoke(second_input, config)
        assert second["count"] == 2
        resumed_snapshot = graph.get_state(config)
        assert resumed_snapshot.values["count"] == 2
        assert resumed_snapshot.values["credential_state"] == "READY"
    finally:
        connection.close()


class _SecretCompiledGraphState(TypedDict):
    count: int
    provider: dict[str, object]


def _increment_secret_state(state: _SecretCompiledGraphState) -> dict[str, object]:
    return {"count": state["count"] + 1}


def test_compiled_graph_checkpoint_secret_state_fails_closed_without_raw_db_bytes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "compiled-secret-checkpoint.db"
    connection = sqlite3.connect(database_path, check_same_thread=False)
    checkpointer = SecretBoundaryCheckpointer(SqliteSaver(connection))
    builder = StateGraph(_SecretCompiledGraphState)
    builder.add_node("increment", _increment_secret_state)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    graph = builder.compile(checkpointer=checkpointer)

    access_token = _secret("compiled-access")
    refresh_token = _secret("compiled-refresh")
    authorization = f"Bearer {_secret('compiled-auth')}"
    config = {"configurable": {"thread_id": "compiled-secret"}}

    try:
        with pytest.raises(SanitizationError):
            graph.invoke(
                {
                    "count": 0,
                    "provider": {
                        "headers": {"Authorization": authorization},
                        "oauth": {
                            "access_token": access_token,
                            "refreshToken": refresh_token,
                        },
                    },
                },
                config,
            )
    finally:
        connection.close()

    database_paths = (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    )
    for secret_value in (access_token, refresh_token, authorization):
        persisted_count = sum(
            path.read_bytes().count(secret_value.encode("utf-8"))
            for path in database_paths
            if path.exists()
        )
        assert persisted_count == 0


def test_sync_sqlite_capabilities_are_not_expanded_to_async() -> None:
    connection, checkpointer = _checkpointer()
    config = {"configurable": {"thread_id": "sync-only", "checkpoint_ns": ""}}
    checkpoint = empty_checkpoint()
    metadata = {"source": "input", "step": -1, "parents": {}}

    async def consume_alist() -> None:
        async for _item in checkpointer.alist(config):
            pass

    try:
        with pytest.raises(NotImplementedError):
            asyncio.run(checkpointer.aget_tuple(config))
        with pytest.raises(NotImplementedError):
            asyncio.run(consume_alist())
        with pytest.raises(NotImplementedError):
            asyncio.run(checkpointer.aput(config, checkpoint, metadata, {}))
        with pytest.raises(NotImplementedError):
            asyncio.run(checkpointer.aput_writes(config, [("state", {"count": 1})], "task"))
        with pytest.raises(NotImplementedError):
            asyncio.run(checkpointer.adelete_thread("sync-only"))
    finally:
        connection.close()


def test_workflow_graph_composition_wraps_product_checkpointer() -> None:
    from google_work_agent.adapters.langgraph.main.graph import (
        GraphNodeBindings,
        WorkflowGraphComposition,
    )
    from google_work_agent.adapters.langgraph.profiles import GraphProfile

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        underlying = SqliteSaver(connection)

        def noop(state: object) -> object:
            return state

        bindings = GraphNodeBindings(
            request_understanding=noop,
            tool_route=noop,
            acquisition=noop,
            context_retriever=noop,
            work_analysis=noop,
            planning=noop,
            review=noop,
            single_workflow=noop,
            domain_validation=noop,
            waiting_approval=noop,
            modify_review=noop,
            action_execution=noop,
            recovery=noop,
            finalize=noop,
            stage_one=noop,
            stage_two=noop,
            stage_three=noop,
        )
        composition = WorkflowGraphComposition(
            profile=GraphProfile.SIX_ROLE_BASELINE,
            topology=(
                "request_understanding",
                "acquisition",
                "context_retriever",
                "work_analysis",
                "planning",
                "review",
            ),
            bindings=bindings,
            route_next_node=lambda _state: "end",
            checkpointer=underlying,
        )

        assert isinstance(composition._checkpointer, SecretBoundaryCheckpointer)
    finally:
        connection.close()
