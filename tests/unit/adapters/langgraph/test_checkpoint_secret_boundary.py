import sqlite3
from copy import deepcopy
from secrets import token_urlsafe

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite import SqliteSaver

from google_work_agent.adapters.langgraph.checkpoint_secret_boundary import (
    SecretBoundaryCheckpointer,
)
from google_work_agent.application.observability import SanitizationError


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
        allowed_config = {
            "configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}
        }
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


def test_workflow_graph_composition_wraps_product_checkpointer() -> None:
    from google_work_agent.adapters.langgraph.graph_composition import (
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
            waiting_confirmation=noop,
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
