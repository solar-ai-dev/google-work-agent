# 11. Google Work Agent · 관측성 · 로그 · 감사 설계서

> **상태:** Draft v2.11 · **기준일:** 2026-08-13 · **외부 Telemetry:** Production 기본 OFF

## 먼저 읽기

- **Domain Store**는 제품 사실의 기준점이다.
- **Trace**는 판단·호출·성능 원인을 설명한다.
- **Audit**는 승인·정책·Write·Verification의 안전 기록이다.
- **Evaluation Artifact**는 후보 비교 결과다.
- 평가에서 BTS, Process, Efficiency, Reliability를 분리하며 비용이 Safety/업무 실패를 상쇄하는 단일 점수는 만들지 않는다.

## 1. 채널

| 채널 | 목적 | 저장 |
|---|---|---|
| Operational Log | Process·Adapter·Startup | Sanitized JSONL |
| Trace | Run·Node·Agent·Tool·성능 | SQLite `trace_events` |
| Audit | 승인·정책·실행·검증·복구 | SQLite `audit_events` |
| SSE | React 진행 Projection | 제한 Buffer·재생성 |
| Metric | Local 집계 | Trace·Audit 계산 |
| Evaluation Artifact | Candidate·Case·Trial·Grader 결과 | `experiments/results/` |

Domain Store가 사실 기준점이며 Trace·SSE·Evaluation Report는 제품 상태를 대체하지 않는다.

## 2. Correlation

제품 Runtime 공통:

```text
app_instance_id
service_instance_id
request_id
command_id
conversation_id
run_id
langgraph_thread_id
plan_id
action_id
approval_id
execution_attempt_id
verification_id
llm_call_id
mcp_request_id
provider_request_id
google_request_id
```

평가 Runtime 추가:

```text
experiment_id
evaluation_item_id
case_id
user_prompt_id
fixture_snapshot_id
candidate_config_hash
trial_index
projection_version
upstream_mode?       # ORACLE | LIVE
target_node_id?
grader_version
scoring_contract_version?
```

평가 필드는 제품 일반 실행에 강제로 저장하지 않는다. Experiment Runner가 명시적으로 시작한 Run에만 연결한다.

## 3. Event Envelope

```text
schema_version
event_name
event_category
occurred_at_ms
severity
component
environment
release_version
request_id?
command_id?
run_id?
action_id?
result_code?
status?
duration_ms?
attributes
```

Category:

```text
LIFECYCLE API WORKFLOW AGENT RETRIEVAL LLM DOMAIN MCP GOOGLE
VERIFICATION SECURITY PERSISTENCE INSTALLER DIAGNOSTIC EVALUATION
```

Payload·Metadata 최대 16 KiB. 원문 대신 수량·Hash·상태·지연을 기록한다.

## 4. JSONL Log

```text
%LOCALAPPDATA%/GoogleWorkAgent/logs/
launcher-*.jsonl
service-*.jsonl
mcp-*.jsonl
```

- 파일당 10 MiB
- 14일
- Directory 200 MiB
- DEBUG라도 Secret·원문 금지

## 5. Trace Taxonomy

- Launcher·Installer lifecycle
- API request·command·SSE
- Run·Graph·Node·Interrupt
- Agent invocation·repair·handoff
- Retrieval page·candidate·detail·budget
- LLM runtime·token·latency·fallback
- MCP process·handshake·tool
- Google read·write·verification
- SQLite transaction·busy·migration·backup
- Evaluation item·candidate·trial·grader·budget stop

평가 전용 Event 예:

```text
EVALUATION_ITEM_STARTED
EVALUATION_ITEM_COMPLETED
NODE_ORACLE_RUN_COMPLETED
NODE_LIVE_RUN_COMPLETED
TRAJECTORY_GRADED
END_STATE_GRADED
GRADER_DISAGREEMENT_RECORDED
EXPERIMENT_BUDGET_STOPPED
```

## 6. Audit 필수 Event

```text
POLICY_CONFIRMATION_RECORDED
ACTION_PROPOSED
ACTION_MODIFIED
ACTION_APPROVED
ACTION_REJECTED
ACTION_EXPIRED
APPROVAL_CONSUMED
POLICY_BLOCKED
EXECUTION_CLAIMED
EXECUTION_SUCCEEDED
EXECUTION_FAILED
EXECUTION_UNKNOWN_RESULT
EXECUTION_RECOVERED
VERIFICATION_VERIFIED
VERIFICATION_MISMATCH
RECOVERY_REQUIRED
RECOVERY_RESOLVED
BACKUP_CREATED
RESTORE_COMPLETED
MIGRATION_COMPLETED
PURGE_COMPLETED
DIAGNOSTIC_BUNDLE_EXPORTED
```

`ACTION_REJECTED`는 성공한 Domain mutation과 같은 UoW에서 기록하며 `run_id`, `plan_id`, `action_id`, `command_id`, actor, 이전/신규 상태, optional `reason_code` 존재 여부와 outcome을 포함한다. Action arguments, Gmail body 등 원문 콘텐츠는 복제하지 않는다. 실패·Version conflict·receipt replay에서는 새 Reject Audit을 만들지 않는다.

안전 Command의 Audit 저장 실패는 Command 실패다.


`POLICY_CONFIRMATION_RECORDED`는 `confirmation_receipt_id`, `interrupt_id`, `confirmation_kind(SCOPE_EXPANSION|DUPLICATE_OVERRIDE|CONFLICT_OVERRIDE)`, `decision(APPROVED|DECLINED)`, `decision_context_hash`, 관련 Run·Resource/Route ID만 allowlist로 기록한다. 질문/응답 원문과 Google 본문은 기록하지 않는다. APPROVED Audit은 LangGraph Checkpoint의 `PolicyConfirmationReceiptV1`과 동일 ID/Context Hash를 가져 Approval Snapshot이 참조할 수 있어야 한다.
 P0 Audit는 Application-level append-only이며 암호학적 Tamper Evidence는 P1 검토다.

## 7. Sanitization

Pipeline:

```text
Schema 검증 → Field Allowlist → Secret·PII Redaction → 길이 제한 → Sink Projection
```

금지:

- OAuth Token·API Key·Authorization·Cookie
- Bootstrap·Session·PKCE
- Gmail·Draft 전체 본문
- LLM Prompt·Completion
- MCP 전체 Request·Response
- Approval Snapshot 전체
- Home Path·Windows User Name

평가 Artifact에도 실제 사용자 데이터, Credential, 전체 Prompt·Completion을 포함하지 않는다. 합성 Fixture의 원문은 Dataset 디렉터리에서만 관리하고 Trace에는 ID·Hash만 기록한다.

## 8. 보존

- App Log 14일
- Trace 30일
- Audit 90일
- Evaluation Raw Result는 Experiment Config에 명시한 기간
- Purge Batch 최대 500 Row
- Active Write·Migration·Restore 중 Purge 금지

## 9. Prompt Registry Trace

```text
prompt_bundle_version
prompt_id
prompt_version
content_hash
agent_role
subgraph_name
node_name
node_state
purpose
input_schema_version
output_schema_version
repair_of_llm_call_id?
revision_no?
```

Prompt 원문은 기록하지 않는다.

## 9.1 Evaluation Trace 계약

평가 Report는 다음을 연결한다.

```text
experiment_id
experiment_kind
evaluation_item_id
case_id
fixture_snapshot_id
user_prompt_id
projection_version
candidate_config_hash
trial_index
prompt_id
model_id
graph_version
upstream_mode?
target_node_id?
grader_version
```

기록해야 하는 집계:

```text
llm_call_count
provider_http_request_count
mcp_tool_call_count
mcp_tool_call_count
mcp_read_tool_call_count
google_provider_api_call_count
input_token_count
output_token_count
cost_usd
p50_latency_ms
p95_latency_ms
repair_count
revision_count
retrieval_round_count
hard_contract_pass?
semantic_task_pass?
business_task_success?
score_denominator_group?   # CORE | STRESS | HOLDOUT
```

- 제품 수준의 Google 접근량은 `mcp_tool_call_count`와 `mcp_read_tool_call_count`로 본다.
- `google_provider_api_call_count`는 Google Work MCP Server 내부 Adapter가 실제 Provider HTTP/API 요청을 수행한 횟수다. Pagination·N+1·Provider 효율을 관찰하기 위한 하위 지표이며 Core의 직접 Provider API 호출을 의미하지 않는다.
- Core에서 Provider API/SDK 직접 호출이 탐지되면 별도 효율 지표가 아니라 아키텍처 계약 위반으로 기록한다.

규칙:

- `ORACLE`과 `LIVE` Node Run을 같은 결과로 합치지 않는다.
- Candidate Config Hash가 다른 결과를 같은 후보 집계에 합치지 않는다.
- Budget Stop·Partial Run은 Full Run과 동일 순위로 비교하지 않는다.
- Safety·Tool·Argument·End-state 결과는 결정적 Grader 결과를 우선한다.
- `business_task_success`는 Hard Contract + calibrated task-semantic 결과로 계산하며 Cost·Latency로 보정하지 않는다.
- Core·Stress·Holdout 집계를 하나의 headline denominator로 합치지 않는다.
- LLM Judge 결과에는 `grader_version`과 Human Calibration 상태를 기록한다.

## 10. Diagnostic Bundle

포함: Manifest, System Summary, Health, Sanitized Logs, Trace·Audit·Migration Summary

제외: DB·Backup 원본, Keyring, Google 원문, Prompt·Completion, Approval Snapshot, 실험 Gold 원문

최대 20 MiB, 최근 24시간 또는 Run 하나. 자동 업로드 금지.

## 11. Local Alert

즉시 표시:

- Service·DB·Migration 실패
- MCP 반복 종료
- OAuth 재인증
- UNKNOWN_RESULT·RECOVERY_REQUIRED
- Contract Version 불일치
- Signature·Manifest 오류

Experiment Runner에서는 별도로 다음을 실패로 표시한다.

- Dataset·Projection Reference 불일치
- Candidate Config 의도 외 Diff
- Holdout 누수
- Grader Version 누락
- Budget 상한 초과

## 12. Command·Claim 관측 계약

Trace·Audit Event:

```text
COMMAND_RECEIVED
COMMAND_REPLAYED
COMMAND_REJECTED_HASH_MISMATCH
COMMAND_APPLIED
CLAIM_TOKEN_ISSUED
CLAIM_TOKEN_REJECTED
CLAIM_TOKEN_CONSUMED
OAUTH_CONNECTION_STARTED
OAUTH_CONNECTION_COMPLETED
OAUTH_CONNECTION_REVOKED
```

기록 가능: `command_id`, `command_type`, Request Hash 앞 12자리, Aggregate ID, 결과 코드, Claim Token Version, 거절 사유.

기록 금지: Claim Token 원문, Service–MCP Session Key, Authorization Code, PKCE Verifier, Access·Refresh Token.

---

## 13. Failure·Retry·Query Trace

Agent 개별실험과 Runtime Prompt 재시도를 분석하기 위해 다음 Trace Attribute를 추가한다.

```text
failure_reason_codes
failure_origin
detected_by
runtime_disposition
experiment_disposition
retry_kind
attempt_no
parent_attempt_id
previous_llm_call_id
changed_field_paths
stop_reason
query_attempt_id
budget_profile
prompt_slot_id
prompt_activation_status
```

규칙:

- Prompt·Completion 원문은 저장하지 않는다.
- Failure-specific Prompt는 Base `prompt_id`/`prompt_version`/`content_hash`와 assembly metadata인 `failure_reason_code`를 연결한다. `failure_reason_code`를 Runtime Prompt Slot Key로 사용하지 않는다.
- ORACLE, LIVE, MUTATED Node Run을 구분한다.
- 실험 Grader가 사후 발견한 실패는 `detected_by=EXPERIMENT_GRADER`로 기록하며 Runtime 감지처럼 표현하지 않는다.
- Budget Profile과 실제 LLM Call 수를 함께 기록한다.
- Query Attempt에는 Query 원문 전체 대신 정규화된 제약, Hash, Score·Confidence·Stop Reason을 저장한다.


## 14. Effect·Transaction 관측
- Trace/Audit에는 `effect_type`(`READ|CREATE|UPDATE|SEND|DELETE`)과 verification/recovery policy를 기록한다.
- 외부 Adapter 호출 이벤트에는 DB Write Transaction 보유 여부를 테스트/진단 전용 필드로 검증할 수 있다. Production Trace에 DB 내부 상세를 노출하지 않는다.
- Recovery Audit는 `RequireRecovery`·`ResolveRecovery` Command 결과와 연결한다.
- SEND/DELETE의 UNKNOWN_RESULT에서도 원문/수신자 전체를 로그에 저장하지 않는다.
## 15. Agent Subgraph 관측 계약

Agent 수와 LLM Call 수를 분리해 기록한다.

```text
graph_profile
agent_subgraph_id
agent_role
agent_invocation_id
parent_agent_invocation_id?
subgraph_namespace
replay_mode?              # NONE | CONTEXT_READY_REPLAY
context_snapshot_id?
controlled_candidate_id?  # B1_INTEGRATED | B2_STAGED | B3_SPECIALIZED
local_attempt_no
schema_repair_count
semantic_revision_count
handoff_from
handoff_to
handoff_disposition
input_state_hash
output_state_hash
llm_call_id
input_token_count
output_token_count
tool_call_count
mcp_tool_call_count
mcp_read_tool_call_count
communication_token_count
required_field_preservation_rate?
evidence_id_preservation_rate?
constraint_loss_count?
contradiction_introduced?
```

규칙:
- `agent_invocation_count`와 `llm_call_count`를 별도 집계한다.
- Local State 원문, Prompt 원문, Completion 원문, Google 원문 전체는 Trace에 저장하지 않는다.
- Handoff는 Agent 간 자유 대화가 아니라 Parent Graph의 Typed Result 이동으로 기록한다.
- E06-A는 Profile의 실제 native 비용을 측정한다. E06-B는 `CONTEXT_READY_V1`의 동일 `context_snapshot_id`에서 post-retrieval decomposition 차이를 비교하며 MCP Read Tool 호출은 0이어야 한다.
- 평가 실행은 `evaluation_environment_hash`로 model/runtime parameter, hardware profile, concurrency, timeout, fixture, Tool Schema, Policy, Prompt semantic bundle, Graph Profile을 함께 잠근다.

## Claim·Attachment 관측 계약

기록 가능:
```text
claim_version
approval_arguments_hash_prefix
execution_arguments_hash_prefix
claim_reject_reason
attachment_count
attachment_size_bytes_total
attachment_mime_types
```

기록 금지:
- Claim Token·Nonce·Signature 원문
- 전체 Approval Arguments/Snapshot
- Gmail 첨부파일 bytes
- Staging File 원문·Local Path
- Attachment content hash 전체값(필요 시 correlation용 짧은 prefix만)

추가 거절 사유 예:
`CLAIM_VERSION_UNSUPPORTED`, `CLAIM_EXPIRED`, `CLAIM_INSTANCE_MISMATCH`, `CLAIM_ARGUMENTS_MISMATCH`, `CLAIM_NONCE_REUSED`, `ATTACHMENT_HASH_MISMATCH`.
