"""Fail-closed secret boundary for LangGraph checkpoint persistence."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver, get_checkpoint_metadata

from google_work_agent.application.observability import (
    SanitizationError,
    assert_persistence_value_secret_free,
    is_forbidden_persistence_key,
)


class SecretBoundaryCheckpointer(BaseCheckpointSaver[Any]):
    """Guard every sync LangGraph checkpoint write before delegating to the real saver.

    The production runtime uses the synchronous ``SqliteSaver``. This decorator
    intentionally implements only the sync capabilities that saver supports; async
    methods remain the ``BaseCheckpointSaver`` fail-closed ``NotImplementedError``
    methods rather than converting the sync saver into an async-capable one.

    SQLite persists checkpoint metadata separately from the checkpoint blob and
    pending-write channel names as plaintext. Guarding only the serializer would
    therefore leave bypasses.
    """

    def __init__(self, delegate: Any) -> None:
        if delegate is None:
            raise TypeError("delegate checkpointer is required")
        self._delegate = delegate
        super().__init__(serde=delegate.serde)

    @property
    def config_specs(self) -> list[Any]:
        return self._delegate.config_specs

    def get_tuple(self, config: Any) -> Any:
        return self._delegate.get_tuple(config)

    def list(
        self,
        config: Any | None,
        *,
        filter: dict[str, Any] | None = None,
        before: Any = None,
        limit: int | None = None,
    ) -> Iterator[Any]:
        return self._delegate.list(config, filter=filter, before=before, limit=limit)

    def put(
        self,
        config: Any,
        checkpoint: Any,
        metadata: Any,
        new_versions: Any,
    ) -> Any:
        _assert_persisted_config_identity_secret_free(config)
        assert_persistence_value_secret_free(checkpoint)
        # SqliteSaver persists get_checkpoint_metadata(config, metadata), not the
        # full RunnableConfig. Validating that exact projection avoids rejecting
        # non-persistent runtime objects while still covering user metadata.
        assert_persistence_value_secret_free(get_checkpoint_metadata(config, metadata))
        return self._delegate.put(config, checkpoint, metadata, new_versions)

    def put_writes(
        self,
        config: Any,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        _assert_persisted_config_identity_secret_free(config)
        assert_persistence_value_secret_free(task_id)
        assert_persistence_value_secret_free(task_path)
        for channel, value in writes:
            if is_forbidden_persistence_key(channel):
                raise SanitizationError(f"secret checkpoint channel rejected: {channel}")
            assert_persistence_value_secret_free(value)
        self._delegate.put_writes(config, writes, task_id, task_path)

    def delete_thread(self, thread_id: str) -> None:
        self._delegate.delete_thread(thread_id)

    def get_next_version(self, current: Any, channel: Any) -> Any:
        return self._delegate.get_next_version(current, channel)

    def get_delta_channel_history(
        self,
        *,
        config: Any,
        channels: Sequence[str],
    ) -> Any:
        return self._delegate.get_delta_channel_history(config=config, channels=channels)


def _assert_persisted_config_identity_secret_free(config: Any) -> None:
    """Validate only config fields that the synchronous SQLite saver persists."""

    if not isinstance(config, Mapping):
        return
    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        return
    for key in ("thread_id", "checkpoint_ns", "checkpoint_id"):
        if key in configurable:
            assert_persistence_value_secret_free(configurable[key])
