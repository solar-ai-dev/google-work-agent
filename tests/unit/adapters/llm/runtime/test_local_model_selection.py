from dataclasses import dataclass

from google_work_agent.adapters.llm.runtime.local_model_selection import (
    LocalModelSelectionResolver,
)
from google_work_agent.ports.llm.local_model_catalog_port import InstalledLocalModelV1
from google_work_agent.ports.llm.local_model_profile import (
    LocalInferenceClass,
    LocalModelProfileV1,
)
from google_work_agent.ports.llm.runtime_selection import (
    LlmRuntimeSelectionV1,
    LocalRuntimeActivationStatus,
    LocalRuntimeRequirementsV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import ApprovedModelInfo


@dataclass(frozen=True)
class _Catalog:
    models: tuple[InstalledLocalModelV1, ...]

    def list_installed_models(self) -> tuple[InstalledLocalModelV1, ...]:
        return self.models


def _profile() -> LocalModelProfileV1:
    return LocalModelProfileV1(
        schema_version=1,
        profile_id="test-profile",
        runtime="OLLAMA",
        worker_model_id="qwen3.5:4b",
        reasoning_model_id="qwen3.5:9b",
        default_inference_class=LocalInferenceClass.REASONING,
        prompt_inference_classes=(
            ("request_understanding.identify_goal", LocalInferenceClass.WORKER),
        ),
    )


def _selection(*models: ApprovedModelInfo) -> LlmRuntimeSelectionV1:
    return LlmRuntimeSelectionV1(
        schema_version=1,
        deployment_profile="LOCAL_CAPABLE",
        selected_model=models[-1] if models else None,
        ollama_endpoint_policy="FIXED_LOOPBACK_OLLAMA_V1",
        model_manifest_hash="a" * 64 if models else None,
        product_decision_hash="b" * 64 if models else None,
        local_runtime_activation_status=LocalRuntimeActivationStatus.ACTIVE,
        requirements=LocalRuntimeRequirementsV1(4, 8 * 1024**3, 4 * 1024**3, "WINDOWS", "AMD64"),
        release_version="test",
        approved_models=models,
        local_model_profile=_profile(),
    )


def test_signed_local_models__allow_only__manifest_models() -> None:
    worker = ApprovedModelInfo("qwen3.5:4b", "OLLAMA", "1", "1", digest="a" * 64)
    reasoning = ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1", digest="b" * 64)
    resolver = LocalModelSelectionResolver(
        runtime_selection=_selection(worker, reasoning),
        catalog=_Catalog(
            (
                InstalledLocalModelV1("qwen2.5:7b", "c" * 64),
                InstalledLocalModelV1("qwen3.5:4b", "a" * 64),
                InstalledLocalModelV1("qwen3.5:9b", "b" * 64),
            )
        ),
    )

    assert [(item.model_id, item.approved, item.selected) for item in resolver.list_options()] == [
        ("qwen2.5:7b", False, False),
        ("qwen3.5:4b", True, True),
        ("qwen3.5:9b", True, True),
    ]
    assert resolver.get_selected_model() == reasoning
    assert (
        resolver.get_model_for_prompt("request_understanding.identify_goal") == worker
    )
    assert resolver.get_model_for_prompt("planning.compose_answer") == reasoning


def test_development_profile__approves_only__installed_profile_models() -> None:
    resolver = LocalModelSelectionResolver(
        runtime_selection=_selection(),
        catalog=_Catalog(
            (
                InstalledLocalModelV1("qwen2.5:7b", "sha256:" + "c" * 64),
                InstalledLocalModelV1("qwen3.5:4b", "sha256:" + "d" * 64),
                InstalledLocalModelV1("qwen3.5:9b", "sha256:" + "e" * 64),
            )
        ),
        allow_development_models=True,
    )

    worker = resolver.get_model_for_prompt("request_understanding.identify_goal")
    reasoning = resolver.get_model_for_prompt("review.inspect_goal_and_evidence")
    assert worker is not None and worker.model_id == "qwen3.5:4b"
    assert reasoning is not None and reasoning.model_id == "qwen3.5:9b"
    assert resolver.get_approved_model("qwen2.5:7b") is None


def test_profile_readiness__requires_both__profile_models() -> None:
    worker = ApprovedModelInfo("qwen3.5:4b", "OLLAMA", "1", "1")
    reasoning = ApprovedModelInfo("qwen3.5:9b", "OLLAMA", "1", "1")
    resolver = LocalModelSelectionResolver(
        runtime_selection=_selection(worker, reasoning),
        catalog=_Catalog(
            (InstalledLocalModelV1("qwen3.5:9b", None),)
        ),
    )

    assert resolver.get_selected_model() is None
    assert resolver.get_model_for_prompt("planning.compose_answer") is None
    assert [(item.model_id, item.installed, item.selected) for item in resolver.list_options()] == [
        ("qwen3.5:9b", True, True),
        ("qwen3.5:4b", False, True),
    ]
