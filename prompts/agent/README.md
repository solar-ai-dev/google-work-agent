# Active Prompt Bundle

- Current: `prompt-manifest-v0.8.2.json` (`0.8.2-r8.3`)
- Runtime selection key excludes `failure_reason_code`; failure-specific instructions are assembly metadata.
- Prompt text must not depend on evaluator/grader/gold terminology.

# Prompt Bundle R8.2

최신 Prompt Manifest: `prompt-manifest-v0.8.2.json`

- Prompt bundle: `0.8.2-r8.3`
- Semantic bundle: `semantic-r8.3-v1`
- Runtime Slot Key: `agent_role + subgraph_name + node_name + node_state + purpose + input_schema_version + output_schema_version`
- `failure_reason_code`는 Runtime Slot Key가 아니라 `BASE_PLUS_FAILURE_BLOCK` assembly metadata다.
- `SINGLE_BASELINE`과 `THREE_STAGE`는 기존 SIX specialist Prompt를 wrapper로 연속 호출하지 않고 profile 전용 fused Prompt를 사용한다.
- E06-B B1/B2는 `CONTEXT_READY_V1` 전용 Prompt이며 Google Read를 수행하지 않는다.
- 모든 R8.2 Prompt는 현재 `DRAFT`다. DEV → Node HOLDOUT → Safety Gate 전 Runtime 활성화 금지.
- v0.1~v0.7 Manifest와 기존 `assembled/`는 R7 이전 provenance 보존용이며 R8.2 Runtime 선택 기준이 아니다.
