"""Test doubles used by product-core tests."""

from tests.support.fakes.clock import FakeClockPort
from tests.support.fakes.google_gateway import (
    FakeGoogleGateway,
    GoogleGatewayCallRecord,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
)
from tests.support.fakes.identity import DeterministicUUID
from tests.support.fakes.keyring import FakeKeyring
from tests.support.fakes.llm import (
    FakeAPIProviderTransport,
    FakeHardwareProbe,
    FakeOllamaTransport,
    FakeSchemaRepairer,
    approved_model,
)
from tests.support.fakes.mcp_transport import (
    FakeMCPClientPort,
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
    "FakeClockPort",
    "FakeGoogleGateway",
    "FakeHardwareProbe",
    "FakeKeyring",
    "FakeOllamaTransport",
    "FakeSchemaRepairer",
    "FakeAPIProviderTransport",
    "FakeMCPClientPort",
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
    "approved_model",
    "fault_injecting_unit_of_work_factory",
]
