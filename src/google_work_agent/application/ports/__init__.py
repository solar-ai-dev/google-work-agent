"""Application-owned capability ports."""

from google_work_agent.application.ports.connector_execution import (
    ConnectorExecutionPort,
    ConnectorWriteRequest,
    PreparedConnectorWrite,
)
from google_work_agent.application.ports.connector_read import (
    ConnectorReadPort,
    ConnectorReadRequest,
    ConnectorReadResult,
)

__all__ = [
    "ConnectorExecutionPort",
    "ConnectorReadPort",
    "ConnectorReadRequest",
    "ConnectorReadResult",
    "ConnectorWriteRequest",
    "PreparedConnectorWrite",
]
