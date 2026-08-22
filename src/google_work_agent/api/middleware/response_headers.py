"""Apply version and browser-security headers to Local API responses."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from google_work_agent.api.container import ApiContainer


def install_response_header_middleware(app: FastAPI, container: ApiContainer) -> None:
    @app.middleware("http")
    async def response_header_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Api-Contract-Version"] = container.api_contract_version
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response
