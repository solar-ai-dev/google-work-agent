"""Own FastAPI startup and shutdown lifecycle orchestration."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from google_work_agent.api.container import ApiContainer


def build_lifespan(container: ApiContainer) -> Callable[[FastAPI], AsyncIterator[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container
        startup_tasks: list[asyncio.Future[None]] = [
            asyncio.ensure_future(callback()) for callback in container.startup_callbacks
        ]
        container.local_run_coordinator.start()
        try:
            yield
        finally:
            try:
                for task in startup_tasks:
                    if not task.done():
                        task.cancel()
                if startup_tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*startup_tasks, return_exceptions=True),
                        timeout=30,
                    )
                container.local_run_coordinator.stop()
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
