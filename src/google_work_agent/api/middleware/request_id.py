"""Assign one correlation identifier to each HTTP request."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from google_work_agent.api.container import ApiContainer


def install_request_id_middleware(app: FastAPI, container: ApiContainer) -> None:
    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = container.id_generator.new_uuid()
        return await call_next(request)
