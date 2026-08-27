from tests.support.fakes import FakeAPIProviderTransport

from google_work_agent.adapters.llm.gemini.structured_inference import (
    GeminiStructuredInferenceAdapter,
)
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)


def test_fake_api_provider_transport_obeys_structured_contract() -> None:
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
    provider = GeminiStructuredInferenceAdapter(
        provider_name="generic-api",
        transport=transport,
        model="fake-api-model",
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
