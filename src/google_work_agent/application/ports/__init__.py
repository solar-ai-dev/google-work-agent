"""Application-owned capability ports."""

from google_work_agent.application.ports.connector_read import (
    ConnectorReadPort,
    ConnectorReadRequest,
    ConnectorReadResult,
)

__all__ = ["ConnectorReadPort", "ConnectorReadRequest", "ConnectorReadResult"]
