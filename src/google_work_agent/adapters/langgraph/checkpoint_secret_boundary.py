"""Fail-closed secret boundary for LangGraph checkpoint persistence."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from google_work_agent.application.observability import (
    SanitizationError,
    assert_persistence_value_secret_free,
    is_forbidden_persistence_key,
)


class SecretBoundaryCheckpointer(BaseCheckpointSaver[Any]):
    """Guard every LangGraph checkpoint write before delegating to the real saver.

    The underlying SQLite saver serializes checkpoint metadata separately from the
    checkpoint blob and persists pending-write channel names as plaintext. Guarding
    only the serializer would therefore leave bypasses. This wrapper validates all
    write surfaces before the delegate can persist any bytes.
    """

    def __init__(self, delegate: Any) -> None:
        if delegate is None:
            raise TypeError("delegate checkpointer is required")
        self._delegate = delegate
        super().__init__(serde=delegate.serde)

    @property
    def config_specs(self) -> list[Any]:
        return list(self._delegate.config_specs)

    def get_tuple(self, config: Any) -> Any:
        return self._delegate.get_tuple(config)

    def list(
        self,
        config: Any,
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
        assert_persistence_value_secret_free(config)
        assert_persistence_value_secret_free(checkpoint)
        assert_persistence_value_secret_free(metadata)
        assert_persistence_value_secret_free(new_versions)
        return self._delegate.put(config, checkpoint, metadata, new_versions)

    def put_writes(
        self,
        config: Any,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        assert_persistence_value_secret_free(config)
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

    async def aget_tuple(self, config: Any) -> Any:
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(
        self,
        config: Any,
        *,
        filter: dict[str, Any] | None = None,
        before: Any = None,
        limit: int | None = None,
    ) -> AsyncIterator[Any]:
        items = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for item in items:
            yield item

    async def aput(
        self,
        config: Any,
        checkpoint: Any,
        metadata: Any,
        new_versions: Any,
    ) -> Any:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: Any,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)
