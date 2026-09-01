from typing import cast

import pytest

from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.retrieval.execute_read import (
    RetrievalReadBindingError,
    execute_read,
)
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCacheEntryV1


class _Reader:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        del binding
        self.calls.append(dict(tool_arguments))
        return ConnectorReadResultV1(1, "gmail_search_threads", "req", {}, None, 0)


def _plan() -> SourceFetchPlanV1:
    return cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "r1",
            "connector_id": "google_workspace",
            "resource_type": "GMAIL_THREAD",
            "operation_kind": "NEXT_PAGE",
            "effective_constraints": [],
            "query_identity_hash": "q" * 64,
            "prior_read_result_handle": "prior",
            "detail_candidate_ref": None,
        },
    )


def _binding() -> ValidatedConnectorToolBindingV1:
    return ValidatedConnectorToolBindingV1(
        1,
        "google_workspace",
        "GMAIL_THREAD",
        "gmail_search_threads",
        "READ",
        "in:v1",
        "out:v1",
        "a" * 64,
    )


@pytest.mark.parametrize(
    "run_id,route_id,query_hash",
    [("other", "r1", "q" * 64), ("run", "r2", "q" * 64), ("run", "r1", "x" * 64)],
)
def test_invalid_continuation_binding_prevents_provider_call(
    run_id: str, route_id: str, query_hash: str
) -> None:
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(
        RunRetrievalCacheEntryV1(
            1,
            "prior",
            run_id,
            route_id,
            query_hash,
            ConnectorReadResultV1(1, "gmail_search_threads", "old", {}, "opaque", 1),
            False,
        )
    )
    reader = _Reader()

    with pytest.raises(RetrievalReadBindingError):
        execute_read(
            plan=_plan(),
            run_id="run",
            binding=_binding(),
            tool_arguments={"query": "bounded"},
            connector_reader=reader,
            read_result_cache=cache,
            read_result_handle="new",
        )

    assert reader.calls == []


def test_exhausted_continuation_does_not_restart_provider_read() -> None:
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(
        RunRetrievalCacheEntryV1(
            1,
            "prior",
            "run",
            "r1",
            "q" * 64,
            ConnectorReadResultV1(1, "gmail_search_threads", "old", {}, None, 1),
            True,
        )
    )
    reader = _Reader()

    result = execute_read(
        plan=_plan(),
        run_id="run",
        binding=_binding(),
        tool_arguments={"query": "bounded"},
        connector_reader=reader,
        read_result_cache=cache,
        read_result_handle="new",
    )

    assert result.status == "EXHAUSTED"
    assert not result.provider_called
    assert reader.calls == []
