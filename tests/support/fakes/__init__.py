"""Test doubles used by product-core tests."""

from tests.support.fakes.clock import FakeClock
from tests.support.fakes.google_gateway import (
    FakeGoogleGateway,
    GoogleGatewayCallRecord,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
)
from tests.support.fakes.identity import DeterministicUUID
from tests.support.fakes.keyring import FakeKeyring
from tests.support.fakes.mcp_transport import (
    FakeMCPTransport,
    MCPCallRecord,
    QueuedMCPFailure,
)
from tests.support.fakes.sqlite_faults import (
    FaultInjectingSQLiteError,
    SQLiteFaultPlan,
    SQLiteFaultStage,
    fault_injecting_unit_of_work_factory,
)
from tests.support.fakes.workflow_runtime import (
    FakeWorkflowRuntime,
    WorkflowCallRecord,
    WorkflowFailure,
)

__all__ = [
    "DeterministicUUID",
    "FakeClock",
    "FakeGoogleGateway",
    "FakeKeyring",
    "FakeMCPTransport",
    "FakeWorkflowRuntime",
    "FaultInjectingSQLiteError",
    "GoogleGatewayCallRecord",
    "GoogleGatewayFault",
    "GoogleGatewayFaultKind",
    "MCPCallRecord",
    "QueuedMCPFailure",
    "SQLiteFaultPlan",
    "SQLiteFaultStage",
    "WorkflowCallRecord",
    "WorkflowFailure",
    "fault_injecting_unit_of_work_factory",
]
