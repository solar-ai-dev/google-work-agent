"""FastAPI surface for the local product core."""

from google_work_agent.api.app import create_app
from google_work_agent.api.container import API_CONTRACT_VERSION, ApiContainer

__all__ = ["API_CONTRACT_VERSION", "ApiContainer", "create_app"]
