"""Serve the built frontend and its history fallback."""

from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse, JSONResponse


class FrontendSite(Protocol):
    index_path: Path

    def resolve_asset(self, path: str) -> Path | None: ...


def create_frontend_asset_router(frontend_site: FrontendSite | None) -> APIRouter | None:
    if frontend_site is None:
        return None
    router = APIRouter()

    @router.get("/{path:path}")
    async def frontend_entry(path: str) -> Response:
        if path.startswith("api/") or path.startswith("health/"):
            return JSONResponse(status_code=404, content={"detail": "not found"})
        candidate = frontend_site.resolve_asset(path)
        if candidate is not None and candidate.is_file():
            response = FileResponse(candidate)
            if Path(candidate).name == "index.html":
                response.headers["Cache-Control"] = "no-cache"
            else:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response
        index = frontend_site.resolve_asset("")
        if index is None:
            return JSONResponse(status_code=404, content={"detail": "not found"})
        if "." not in path and path:
            response = FileResponse(index)
            response.headers["Cache-Control"] = "no-cache"
            return response
        if path == "":
            response = FileResponse(index)
            response.headers["Cache-Control"] = "no-cache"
            return response
        return JSONResponse(status_code=404, content={"detail": "not found"})

    return router
