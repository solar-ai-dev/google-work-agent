"""Canonical Retrieval deterministic operation: execute_read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort, JsonValue
from google_work_agent.ports.connector.contracts import ValidatedConnectorToolBindingV1
from google_work_agent.ports.system.run_retrieval_cache_port import (
    RunRetrievalCacheEntryV1,
    RunRetrievalCachePort,
)


class RetrievalReadBindingError(ValueError):
    """A read or continuation is outside its frozen route/query binding."""


@dataclass(frozen=True, slots=True)
class RetrievalReadExecutionV1:
    schema_version: Literal[1]
    status: Literal["COMPLETE", "EXHAUSTED"]
    read_result_handle: str
    tool_id: str
    total_count: int | None
    provider_called: bool


def execute_read(
    *,
    plan: SourceFetchPlanV1,
    run_id: str,
    binding: ValidatedConnectorToolBindingV1,
    tool_arguments: dict[str, JsonValue],
    connector_reader: ConnectorReadPort,
    read_result_cache: RunRetrievalCachePort,
    read_result_handle: str,
) -> RetrievalReadExecutionV1:
    """Execute one registry-validated READ and keep its opaque continuation cache-local."""
    _validate_binding(plan, binding)
    arguments = dict(tool_arguments)
    if "page_token" in arguments or "next_page_token" in arguments:
        raise RetrievalReadBindingError("raw continuation must come only from Run Retrieval Cache")

    if plan["operation_kind"] == "NEXT_PAGE":
        prior_handle = plan["prior_read_result_handle"]
        if prior_handle is None:
            raise RetrievalReadBindingError("NEXT_PAGE requires a prior read-result handle")
        resolution = read_result_cache.resolve_read_result(
            prior_handle,
            run_id,
            plan["route_id"],
            plan["query_identity_hash"],
        )
        if resolution.status == "EXHAUSTED":
            entry = resolution.entry
            if entry is None:
                raise RetrievalReadBindingError("EXHAUSTED cache result requires an entry")
            return RetrievalReadExecutionV1(
                schema_version=1,
                status="EXHAUSTED",
                read_result_handle=entry.read_result_handle,
                tool_id=entry.read_result.tool_id,
                total_count=entry.read_result.total_count,
                provider_called=False,
            )
        if resolution.status != "FOUND" or resolution.entry is None:
            raise RetrievalReadBindingError(
                f"invalid retrieval continuation binding: {resolution.status}"
            )
        continuation = resolution.entry.read_result.next_page_token
        if continuation is None:
            raise RetrievalReadBindingError("FOUND continuation entry has no page token")
        arguments["page_token"] = continuation

    result = connector_reader.execute_read(binding, arguments)
    read_result_cache.put_read_result(
        RunRetrievalCacheEntryV1(
            schema_version=1,
            read_result_handle=read_result_handle,
            run_id=run_id,
            route_id=plan["route_id"],
            query_identity_hash=plan["query_identity_hash"],
            read_result=result,
            continuation_exhausted=result.next_page_token is None,
        )
    )
    return RetrievalReadExecutionV1(
        schema_version=1,
        status="COMPLETE",
        read_result_handle=read_result_handle,
        tool_id=result.tool_id,
        total_count=result.total_count,
        provider_called=True,
    )


def _validate_binding(
    plan: SourceFetchPlanV1,
    binding: ValidatedConnectorToolBindingV1,
) -> None:
    if binding.effect != "READ":
        raise RetrievalReadBindingError("retrieval can execute READ bindings only")
    if binding.connector_id != plan["connector_id"]:
        raise RetrievalReadBindingError("connector binding differs from frozen route")
    if coarse_resource_category(binding.resource_type) != coarse_resource_category(
        plan["resource_type"]
    ):
        raise RetrievalReadBindingError("resource binding differs from frozen route")


__all__ = ["RetrievalReadBindingError", "RetrievalReadExecutionV1", "execute_read"]
