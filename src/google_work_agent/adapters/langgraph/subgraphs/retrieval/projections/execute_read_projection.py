from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.orchestration.retrieval_v2_contracts import SourceFetchPlanV1
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort, JsonValue
from google_work_agent.ports.connector.contracts import ValidatedConnectorToolBindingV1
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCachePort


class ExecuteReadInput(TypedDict):
    plan: SourceFetchPlanV1
    run_id: str
    binding: ValidatedConnectorToolBindingV1
    tool_arguments: dict[str, JsonValue]
    connector_reader: ConnectorReadPort
    read_result_cache: RunRetrievalCachePort
    read_result_handle: str


def project_execute_read_input(state: Mapping[str, object]) -> ExecuteReadInput:
    inputs = state.get("operation_inputs")
    value = inputs.get("execute_read") if isinstance(inputs, Mapping) else None
    if not isinstance(value, Mapping):
        raise ValueError("missing typed input projection for retrieval.execute_read")
    return cast(ExecuteReadInput, dict(value))
