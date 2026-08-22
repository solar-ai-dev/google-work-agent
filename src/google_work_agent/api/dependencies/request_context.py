"""Resolve the API composition container from one HTTP request."""

from typing import cast

from fastapi import Request

from google_work_agent.api.container import ApiContainer


def get_api_container(request: Request) -> ApiContainer:
    return cast("ApiContainer", request.app.state.container)
