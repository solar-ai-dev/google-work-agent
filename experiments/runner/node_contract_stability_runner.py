"""Node Contract Stability Runner.

Repeatedly invokes each of the 8 LLM Nodes' real ``invoke_*_llm`` methods
against one fixed, deterministic, synthetic input (see
``node_contract_fixtures.py``) using the real production
``StructuredLLMRuntime``/``LLMRuntimeService`` machinery -- the exact same
``_validate_or_repair`` (shape -> semantic -> Schema Repair) path the
product Runtime uses -- and records whether each call's FINAL output
satisfies the Node's own Typed Output Contract.

This measures ONLY structural/contract stability -- "did the Node return
the shape it promised" -- never whether the model's business judgment
(status choice, which evidence, plan content) was correct. No Gold label,
no grader, no expected_status is used anywhere in this file.

Mirrors ``r84_gate_runner.py``'s ``_build_gate_provider`` pattern
(construct ``OllamaStructuredLLMProvider`` directly, bypassing the product
LOCAL_GPU hardware-capability gate, which exists to protect product
dispatch, not offline tooling) and reuses the D-2/Node-Contract-Audit
``PromptRepairSchemaRepairer`` so a real Schema Repair attempt is made
whenever a Node's sibling ``<namespace>.repair`` prompt is ``RUNTIME_ACTIVE``
(today: none of them are, so every repair attempt fails closed by design --
see the Audit report's Repair Boundary section).

Sanitized recording only: no Prompt/Completion text, no raw structured
output, and no Gmail body ever gets written to the ledger -- only the
correlation/outcome fields section 10 of the audit instructions asked for.

Usage:
    .venv-cpu/Scripts/python.exe experiments/runner/node_contract_stability_runner.py \\
        [--iterations N] [--model MODEL_ID] [--only NODE_ID ...] [--endpoint URL]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import node_contract_fixtures as fixtures  # noqa: E402

from google_work_agent.adapters.llm.ollama import (  # noqa: E402
    OllamaHTTPClient,
    OllamaStructuredLLMProvider,
)
from google_work_agent.application.llm import (  # noqa: E402
    LLMRuntimeService,
    PromptRepairSchemaRepairer,
    PromptRepairToolCallRepairer,
)
from google_work_agent.application.observability import ObservabilityContext  # noqa: E402
from google_work_agent.application.workflows.api_acquisition import (  # noqa: E402
    ApiDiscoveryAcquisitionAgent,
)
from google_work_agent.application.workflows.context_retrieval import (  # noqa: E402
    EVIDENCE_SELECTION_OUTPUT_SCHEMA,
    SUFFICIENCY_OUTPUT_SCHEMA,
    ContextRetrievalAgent,
    _budget_projection,
    _segment_prompt_projection,
    validate_evidence_selection_output_v1,
    validate_sufficiency_output_v1,
)
from google_work_agent.application.workflows.plan_review import PlanReviewAgent  # noqa: E402
from google_work_agent.application.workflows.prompt_registry import (  # noqa: E402
    default_prompt_manifest_path,
    load_prompt_reference_for_evaluation,
    resolve_instruction_text,
)
from google_work_agent.application.workflows.request_understanding import (  # noqa: E402
    RequestUnderstandingAgent,
)
from google_work_agent.application.workflows.solution_planning import (  # noqa: E402
    SolutionPlanningAgent,
)
from google_work_agent.application.workflows.work_analysis import WorkAnalysisAgent  # noqa: E402
from google_work_agent.ports import (  # noqa: E402
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    RuntimePolicy,
    StructuredLLMResult,
)

DEFAULT_OLLAMA_MODEL_ID = "qwen2.5:7b"
DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
MANIFEST_PATH = default_prompt_manifest_path()


@dataclass
class RecordingEventRecorder:
    """Captures event NAMES only (see application/llm.py's event_recorder
    calls) -- never attributes, which may embed prompt_content_hash but
    never Prompt/Completion text itself; still, only names are kept here."""

    events: list[str] = field(default_factory=list)

    def record(self, **kwargs: object) -> None:
        self.events.append(str(kwargs.get("event_name")))


@dataclass
class InvocationRecord:
    node_name: str
    agent_role: str
    provider: str
    model_id: str
    prompt_id: str
    prompt_version: str
    prompt_status: str
    input_schema_version: str
    output_schema_version: str
    attempt_no: int
    first_pass_valid: bool
    repair_invoked: bool
    repair_recovered: bool
    final_contract_valid: bool
    failure_reason_code: str | None
    uncaught_exception: bool
    duration_ms: int


@dataclass
class _DirectOllamaRuntime:
    """A ``StructuredLLMRuntime`` that dispatches straight to
    ``LLMRuntimeService._invoke_provider`` with a fixed
    ``OllamaStructuredLLMProvider``, bypassing ``_invoke_locked`` ->
    ``_resolve_provider`` (settings_service/router/hardware-capability gate)
    entirely. Mirrors ``r84_gate_runner.py``'s exact rationale: that gate
    protects PRODUCT dispatch, not offline Node tooling -- see this file's
    module docstring. ``_invoke_provider`` is intentionally reused (not
    reimplemented) so the real Schema Repair loop still runs.
    """

    service: LLMRuntimeService
    provider: OllamaStructuredLLMProvider

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Any,
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Any = None,
    ) -> StructuredLLMResult:
        return self.service._invoke_provider(  # noqa: SLF001 - intentional reuse, see class docstring
            provider=self.provider,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            output_schema=output_schema,
            requested_mode=RequestedRuntimeMode.LOCAL_GPU,
            trace_context=trace_context,
            fallback_reason=None,
            semantic_validate=semantic_validate,
        )

    def invoke_tool_call(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Any,
        tools: Any,
        mapper: Any,
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Any = None,
    ) -> StructuredLLMResult:
        return self.service._invoke_tool_call_provider(  # noqa: SLF001 - see class docstring
            provider=self.provider,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            tools=tools,
            mapper=mapper,
            output_schema=output_schema,
            requested_mode=RequestedRuntimeMode.LOCAL_GPU,
            trace_context=trace_context,
            semantic_validate=semantic_validate,
        )


def _build_runtime(
    *, model_id: str, endpoint: str
) -> tuple[_DirectOllamaRuntime, RecordingEventRecorder]:
    provider = OllamaStructuredLLMProvider(
        provider_name="ollama",
        transport=OllamaHTTPClient(),
        endpoint=endpoint,
        model_id=model_id,
        # Mirrors r84_gate_runner.py::_build_gate_provider's resolve_text and
        # dev.py's production wiring: resolve_instruction_text does not gate
        # on activation_status (only the PromptReference-producing loaders
        # do), so this correctly assembles real instruction content for both
        # the INITIAL (RUNTIME_ACTIVE) prompt and, when Schema Repair fires,
        # the DRAFT ".repair" prompt loaded via prompt_loader above.
        resolve_instruction_text=lambda prompt_ref: resolve_instruction_text(
            prompt_ref.prompt_id, MANIFEST_PATH
        ),
    )
    recorder = RecordingEventRecorder()
    service = LLMRuntimeService(
        settings_service=lambda: (_ for _ in ()).throw(  # pragma: no cover - unused
            RuntimeError("settings_service must not be called by the stability runner")
        ),
        # status_service/api_provider/router are never touched: _invoke_locked
        # (which reads them) is bypassed entirely by _DirectOllamaRuntime below.
        # credential_service is never touched either -- only read when
        # provider.runtime is API_LLM, and this provider's runtime is LOCAL_GPU.
        status_service=None,  # type: ignore[arg-type]
        credential_service=None,  # type: ignore[arg-type]
        api_provider=None,  # type: ignore[arg-type]
        ollama_provider_factory=lambda model, settings: provider,  # unused
        router=None,  # type: ignore[arg-type]
        runtime_policy=RuntimePolicy(local_timeout_seconds=180),
        event_recorder=recorder,
        # DEV-only: load_prompt_reference_for_evaluation reads a sibling
        # ".repair" slot's real content regardless of activation_status, the
        # same official Gate-evaluation loader r84_gate_runner.py uses.
        # Production's PromptRepairSchemaRepairer default (prompt_loader=None
        # -> load_prompt_reference) is untouched and still fails closed on
        # DRAFT; this runner is the only caller that opts into the DEV path.
        schema_repairer=PromptRepairSchemaRepairer(
            manifest_path=MANIFEST_PATH,
            prompt_loader=load_prompt_reference_for_evaluation,
        ),
        tool_call_schema_repairer=PromptRepairToolCallRepairer(
            manifest_path=MANIFEST_PATH,
            prompt_loader=load_prompt_reference_for_evaluation,
        ),
    )
    return _DirectOllamaRuntime(service=service, provider=provider), recorder


def _invoke_one(
    *,
    node_name: str,
    agent_role: str,
    call: Any,
    prompt_ref_getter: Any,
    recorder: RecordingEventRecorder,
    model_id: str,
) -> InvocationRecord:
    prompt_ref = prompt_ref_getter()
    started = time.perf_counter()
    recorder.events.clear()
    failure_reason_code: str | None = None
    uncaught_exception = False
    attempt_no = 0
    final_contract_valid = False
    try:
        result = call()
        attempt_no = result.structured_output_attempts
        final_contract_valid = True
    except LLMInvocationError as error:
        failure_reason_code = error.code.value
    except Exception as error:  # noqa: BLE001 - record every failure mode, never crash the run
        uncaught_exception = True
        failure_reason_code = type(error).__name__
    duration_ms = int((time.perf_counter() - started) * 1000)
    repair_invoked = "LLM_REPAIR_REQUESTED" in recorder.events
    return InvocationRecord(
        node_name=node_name,
        agent_role=agent_role,
        provider="ollama",
        model_id=model_id,
        prompt_id=prompt_ref.prompt_id,
        prompt_version=prompt_ref.prompt_version,
        prompt_status="RUNTIME_ACTIVE",
        input_schema_version=prompt_ref.input_schema_version,
        output_schema_version=prompt_ref.output_schema_version,
        attempt_no=attempt_no,
        first_pass_valid=final_contract_valid and attempt_no == 1,
        repair_invoked=repair_invoked,
        repair_recovered=final_contract_valid and attempt_no > 1,
        final_contract_valid=final_contract_valid,
        failure_reason_code=failure_reason_code,
        uncaught_exception=uncaught_exception,
        duration_ms=duration_ms,
    )


NODE_NAMES = [
    "request_understanding.classify",
    "acquisition.plan_sources",
    "context.select_evidence",
    "context.assess_sufficiency",
    "analysis.analyze",
    "planning.answer_only",
    "planning.draft_plan",
    "review.inspect",
]


def run_node(
    node_name: str,
    *,
    llm_runtime: _DirectOllamaRuntime,
    recorder: RecordingEventRecorder,
    model_id: str,
    iterations: int,
) -> list[InvocationRecord]:
    records: list[InvocationRecord] = []
    agent: Any
    if node_name == "request_understanding.classify":
        agent = RequestUnderstandingAgent(llm_runtime=llm_runtime, manifest_path=MANIFEST_PATH)
        request = fixtures.new_request("김대리 메일 확인해서 이번 주 할 일 정리해줘.")
        for _ in range(iterations):
            records.append(
                _invoke_one(
                    node_name=node_name,
                    agent_role="request_understanding",
                    call=lambda: agent.invoke_classify_llm(request),
                    prompt_ref_getter=lambda: agent.prompt_ref,
                    recorder=recorder,
                    model_id=model_id,
                )
            )
    elif node_name == "acquisition.plan_sources":
        # gateway is never touched: invoke_plan_sources_llm/plan_sources never call it
        # (only acquire() does, which this node's stability check never exercises).
        agent = ApiDiscoveryAcquisitionAgent(
            llm_runtime=llm_runtime,
            gateway=None,  # type: ignore[arg-type]
            manifest_path=MANIFEST_PATH,
        )
        kwargs = fixtures.acquisition_agent_kwargs()
        for _ in range(iterations):
            records.append(
                _invoke_one(
                    node_name=node_name,
                    agent_role="api_discovery_acquisition",
                    call=lambda: agent.invoke_plan_sources_llm(**kwargs),
                    prompt_ref_getter=lambda: agent.prompt_ref,
                    recorder=recorder,
                    model_id=model_id,
                )
            )
    elif node_name == "context.select_evidence":
        # Calls llm_runtime.invoke_structured directly (not agent.select_evidence(),
        # which returns EvidenceSelectionOutputV1/wraps its own bespoke
        # SEMANTIC_REVISION retry, not a StructuredLLMResult) so this measures
        # the single Node call -- prompt + schema + validator -- like every
        # other node here, consistent with the Node Contract Audit's scope.
        agent = ContextRetrievalAgent(llm_runtime=llm_runtime, manifest_path=MANIFEST_PATH)
        kwargs = fixtures.context_select_evidence_kwargs(agent)
        segments = cast("list[Any]", kwargs["segments"])
        select_acquisition_result = cast("dict[str, Any]", kwargs["acquisition_result"])
        context_budget = agent._context_budget  # noqa: SLF001 - offline tooling, see class docstring
        prompt_input = {
            "request_intent": kwargs["request_intent"],
            "acquisition_status": select_acquisition_result["status"],
            "acquisition_missing_slots": list(select_acquisition_result["missing_slots"]),
            "source_content_is_untrusted": True,
            "segments": [_segment_prompt_projection(segment) for segment in segments],
            "context_budget": _budget_projection(context_budget),
        }
        for _ in range(iterations):
            records.append(
                _invoke_one(
                    node_name=node_name,
                    agent_role="context_retriever",
                    call=lambda: llm_runtime.invoke_structured(
                        prompt_ref=agent.select_prompt_ref,
                        prompt_input=prompt_input,
                        output_schema=EVIDENCE_SELECTION_OUTPUT_SCHEMA,
                        trace_context=ObservabilityContext(
                            run_id="stability", llm_call_id=node_name
                        ),
                        semantic_validate=lambda payload: validate_evidence_selection_output_v1(
                            payload, segments=segments, context_budget=context_budget
                        ),
                    ),
                    prompt_ref_getter=lambda: agent.select_prompt_ref,
                    recorder=recorder,
                    model_id=model_id,
                )
            )
    elif node_name == "context.assess_sufficiency":
        # Same rationale as context.select_evidence above: call
        # llm_runtime.invoke_structured directly rather than
        # agent.assess_sufficiency(), which returns a
        # (SufficiencyOutputV1, dict) tuple, not a StructuredLLMResult.
        agent = ContextRetrievalAgent(llm_runtime=llm_runtime, manifest_path=MANIFEST_PATH)
        kwargs = fixtures.context_assess_sufficiency_kwargs()
        sufficiency_acquisition_result = cast("dict[str, Any]", kwargs["acquisition_result"])
        prompt_input = {
            "request_intent": kwargs["request_intent"],
            "acquisition_status": sufficiency_acquisition_result["status"],
            "acquisition_missing_slots": list(sufficiency_acquisition_result["missing_slots"]),
            "context_bundle": kwargs["context_bundle"],
            "evidence_drafts": kwargs["evidence_drafts"],
            "source_content_is_untrusted": True,
        }
        for _ in range(iterations):
            records.append(
                _invoke_one(
                    node_name=node_name,
                    agent_role="context_retriever",
                    call=lambda: llm_runtime.invoke_structured(
                        prompt_ref=agent.sufficiency_prompt_ref,
                        prompt_input=prompt_input,
                        output_schema=SUFFICIENCY_OUTPUT_SCHEMA,
                        trace_context=ObservabilityContext(
                            run_id="stability", llm_call_id=node_name
                        ),
                        semantic_validate=validate_sufficiency_output_v1,
                    ),
                    prompt_ref_getter=lambda: agent.sufficiency_prompt_ref,
                    recorder=recorder,
                    model_id=model_id,
                )
            )
    elif node_name == "analysis.analyze":
        agent = WorkAnalysisAgent(llm_runtime=llm_runtime, manifest_path=MANIFEST_PATH)
        kwargs = fixtures.analysis_analyze_kwargs()
        for _ in range(iterations):
            records.append(
                _invoke_one(
                    node_name=node_name,
                    agent_role="work_analysis",
                    call=lambda: agent.invoke_analyze_llm(**kwargs),
                    prompt_ref_getter=lambda: agent.analyze_prompt_ref,
                    recorder=recorder,
                    model_id=model_id,
                )
            )
    elif node_name == "planning.answer_only":
        agent = SolutionPlanningAgent(llm_runtime=llm_runtime, manifest_path=MANIFEST_PATH)
        kwargs = fixtures.planning_answer_only_kwargs()
        for _ in range(iterations):
            records.append(
                _invoke_one(
                    node_name=node_name,
                    agent_role="solution_planning",
                    call=lambda: agent.invoke_answer_only_llm(**kwargs),
                    prompt_ref_getter=lambda: agent.answer_only_prompt_ref,
                    recorder=recorder,
                    model_id=model_id,
                )
            )
    elif node_name == "planning.draft_plan":
        agent = SolutionPlanningAgent(llm_runtime=llm_runtime, manifest_path=MANIFEST_PATH)
        kwargs = fixtures.planning_draft_plan_kwargs()
        for _ in range(iterations):
            records.append(
                _invoke_one(
                    node_name=node_name,
                    agent_role="solution_planning",
                    call=lambda: agent.invoke_draft_plan_llm(**kwargs),
                    prompt_ref_getter=lambda: agent.draft_plan_prompt_ref,
                    recorder=recorder,
                    model_id=model_id,
                )
            )
    elif node_name == "review.inspect":
        agent = PlanReviewAgent(llm_runtime=llm_runtime, manifest_path=MANIFEST_PATH)
        kwargs = fixtures.review_inspect_kwargs()
        for _ in range(iterations):
            records.append(
                _invoke_one(
                    node_name=node_name,
                    agent_role="plan_review",
                    call=lambda: agent.invoke_inspect_llm(**kwargs),
                    prompt_ref_getter=lambda: agent.inspect_prompt_ref,
                    recorder=recorder,
                    model_id=model_id,
                )
            )
    else:
        raise ValueError(f"unknown node_name: {node_name}")
    return records


def _print_summary(all_records: dict[str, list[InvocationRecord]]) -> None:
    print(
        f"\n{'Node':<32}{'Calls':>7}{'1st-pass':>10}{'Repair':>8}{'Recovered':>11}"
        f"{'Final OK':>10}{'Rate':>8}{'Uncaught':>10}{'Gate':>18}"
    )
    for node_name, records in all_records.items():
        calls = len(records)
        first_pass = sum(1 for r in records if r.first_pass_valid)
        repair = sum(1 for r in records if r.repair_invoked)
        recovered = sum(1 for r in records if r.repair_recovered)
        final_ok = sum(1 for r in records if r.final_contract_valid)
        uncaught = sum(1 for r in records if r.uncaught_exception)
        rate = f"{final_ok}/{calls}"
        multi_repair = any(r.attempt_no > 2 for r in records)
        if calls >= 50:
            gate = (
                "EXPERIMENT_READY"
                if final_ok >= 49 and uncaught == 0 and not multi_repair
                else "CONTRACT_UNSTABLE"
            )
        else:
            gate = "SMOKE_ONLY"
        print(
            f"{node_name:<32}{calls:>7}{first_pass:>10}{repair:>8}{recovered:>11}"
            f"{final_ok:>10}{rate:>8}{uncaught:>10}{gate:>18}"
        )
        for index, record in enumerate(records):
            if not record.final_contract_valid or record.uncaught_exception:
                print(
                    f"    call[{index}] failure_reason_code={record.failure_reason_code} "
                    f"uncaught_exception={record.uncaught_exception} "
                    f"repair_invoked={record.repair_invoked} duration_ms={record.duration_ms}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description="Node Contract Stability Runner")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--model", default=DEFAULT_OLLAMA_MODEL_ID)
    parser.add_argument("--endpoint", default=DEFAULT_OLLAMA_ENDPOINT)
    parser.add_argument("--only", action="append", default=None, choices=NODE_NAMES)
    parser.add_argument("--output", default=None, help="Optional path to write JSON ledger")
    args = parser.parse_args()

    targets = args.only or NODE_NAMES
    llm_runtime, recorder = _build_runtime(model_id=args.model, endpoint=args.endpoint)

    print(f"fixture_set_version={fixtures.FIXTURE_SET_VERSION}")
    print(f"provider=ollama model_id={args.model} endpoint={args.endpoint}")
    print(f"iterations={args.iterations}")

    all_records: dict[str, list[InvocationRecord]] = {}
    for node_name in targets:
        print(f"\n=== {node_name} ===", flush=True)
        records = run_node(
            node_name,
            llm_runtime=llm_runtime,
            recorder=recorder,
            model_id=args.model,
            iterations=args.iterations,
        )
        all_records[node_name] = records

    _print_summary(all_records)

    if args.output:
        payload = {
            "fixture_set_version": fixtures.FIXTURE_SET_VERSION,
            "model_id": args.model,
            "iterations": args.iterations,
            "records": {
                node_name: [record.__dict__ for record in records]
                for node_name, records in all_records.items()
            },
        }
        Path(args.output).write_text(
            json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        print(f"\nledger written: {args.output}")


if __name__ == "__main__":
    main()
