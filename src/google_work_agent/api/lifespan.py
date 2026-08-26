"""Own FastAPI startup and shutdown lifecycle orchestration."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from google_work_agent.api.container import ApiContainer


def build_lifespan(container: ApiContainer) -> Callable[[FastAPI], AsyncIterator[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container
        for callback in container.startup_callbacks:
            await callback()
        try:
            yield
        finally:
            _run_shutdown_callbacks(container.shutdown_callbacks)

    return lifespan


def _run_shutdown_callbacks(callbacks: tuple[Callable[[], None], ...]) -> None:
    first_error: Exception | None = None
    for callback in callbacks:
        try:
            callback()
        except Exception as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error
