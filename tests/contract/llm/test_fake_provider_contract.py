import json
from pathlib import Path

from tests.support.fakes import FakeAPIProviderTransport

from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)


def _manifest(tmp_path: Path) -> Path:
    """Isolated Prompt Runtime Input Contract for this file's synthetic
    PROMPT_REF ("prompt.test") -- this test exercises the fake API provider
    transport contract generically and was never meant to be validated
    against the real production Product Prompt contract."""
    agent_dir = tmp_path / "prompts" / "agent"
    contract_dir = agent_dir / "contracts"
    contract_dir.mkdir(parents=True)
    manifest = agent_dir / "prompt-manifest-v1.0.0.json"
    manifest.write_text(
        json.dumps({"runtime_input_contract": "prompts/agent/contracts/input.json"}),
        encoding="utf-8",
    )
    (contract_dir / "input.json").write_text(
        json.dumps(
            {
                "forbidden_runtime_fields": [],
                "slots": {"prompt.test": {"allowed_root_fields": ["hello"]}},
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_fake_api_provider_transport_obeys_structured_contract(tmp_path: Path) -> None:
    transport = FakeAPIProviderTransport()
    transport.queued_payloads.append(
        ProviderResponsePayload(
            content={"answer": "ok"},
            model="fake-api-model",
            provider_request_id="provider-1",
            input_tokens=7,
            output_tokens=4,
            latency_ms=30,
        )
    )
    provider = StructuredInferenceRuntimeRouter(
        provider_name="generic-api",
        transport=transport,
        model="fake-api-model",
        prompt_manifest_path=_manifest(tmp_path),
    )

    payload = provider.invoke_structured(
        prompt_ref=PromptReference(
            prompt_bundle_version="1",
            prompt_id="prompt.test",
            prompt_version="1",
            content_hash="hash-1",
            agent_role="tester",
            subgraph_name="main",
            node_name="node",
            node_state="draft",
            purpose="contract",
            input_schema_version="1",
            output_schema_version="1",
        ),
        prompt_input={"hello": "world"},
        output_schema=OutputSchemaDefinition(
            schema_version="1",
            json_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        ),
        runtime_policy=RuntimePolicy(),
        api_key="secret-key",
    )

    assert payload.content == {"answer": "ok"}
    assert payload.model == "fake-api-model"
    assert payload.provider_request_id == "provider-1"
