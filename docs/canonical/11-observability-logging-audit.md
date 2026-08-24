# 11. 관측성 · 로그 · 감사 설계서

> **Authority:** observability/log/trace/audit projection, sanitization과 retention. Domain/Workflow lifecycle 의미는 관측 event로 재정의하지 않는다.  
> **상태:** Draft v2.23 · **기준일:** 2026-08-25 · **외부 Telemetry:** Production 기본 OFF

## 0. 사람이 먼저 볼 것

- **Domain Store:** 제품 사실
- **Trace:** 왜 그렇게 판단·호출했는지
- **Audit:** 승인·정책·Write·검증의 안전 기록
- **Evaluation Artifact:** 후보 비교 결과

`Evaluation Artifact`는 `13 Evaluation`이 정의한 비교 결과의 저장·관측 채널일 뿐 제품 상태 authority가 아니다.

## 1. 채널

| 채널 | 목적 | 저장 |
| --- | --- | --- |
| Operational Log | Process·Adapter·Startup | Sanitized JSONL |
| Trace | Run·Node·Agent·Tool·성능 | SQLite `trace_events` |
| Audit | 승인·정책·실행·검증·복구 | SQLite `audit_events` |
| SSE | React 진행 Projection | 제한 Buffer·재생성 |
| Metric | Local 집계 | Trace·Audit 계산 |
| Evaluation Artifact | Candidate·Case·Trial·Grader 결과 | 13 Evaluation artifact store; exact repository placement는 16이 소유 |

Domain Store가 사실 기준점이며 Trace·SSE·Evaluation Report는 제품 상태를 대체하지 않는다. Evaluation artifact의 semantic set은 13이, exact repository placement/naming은 16이 소유한다. 이 문서는 **Observability concern**의 Event/Log/Trace/Audit schema·retention·sanitization을 소유하지만 Domain lifecycle command·state·guard·transition semantics를 정의하지 않는다. Audit/Trace Event 이름은 concern-owning Domain/Workflow/Policy 계약에서 발생한 사실의 관측 projection이며, 관측 taxonomy만으로 새 제품 상태나 허용 전이를 만들 수 없다.

### 1.1 SSE Projection ownership

SSE는 durable Domain Event Store가 아니다. `sse_event.project_run_event`가 typed fact를 `RunSseEventV1`로 변환하고 `SseEventBufferPort`에 append한다. P0 `InMemorySseEventBuffer`는 10 Infrastructure가 제공하는 configured capacity/terminal-retention/query-bound의 bounded process-local replay만 제공한다. `Last-Event-ID` cursor가 만료되거나 process restart로 Buffer가 사라지면 API는 `CURSOR_EXPIRED`를 반환하고 React가 Run Snapshot으로 복구한다.

Required lifecycle Audit는 Domain mutation/Receipt와 같은 UoW에 들어가며 실패하면 command를 rollback한다. Diagnostic Trace와 SSE publish는 **post-commit**이며 실패해도 이미 commit된 Domain mutation을 rollback하지 않는다. Trace/SSE 실패가 외부 Connector Write 재전송을 유발해서도 안 된다.

## 2. Correlation

제품 Runtime 공통:

```
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
connector_id?
provider_request_id
```

평가 Runtime 추가:

```
main_experiment_id?      # A | B | C | D | E
experiment_id?           # compatibility-only reproduction alias; current decision key is main_experiment_id
dataset_suite_id?        # current 13 Evaluation registered suite ID
episode_variant_id?      # Product Episode variant only
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
evaluation_environment_hash?
runner_version?
hardware_profile_id?
concurrency_limit?
timeout_profile?
```

평가 필드는 제품 일반 실행에 강제로 저장하지 않는다. Experiment Runner가 명시적으로 시작한 Run에만 연결한다.

## 3. Event Envelope

```
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

```
LIFECYCLE API WORKFLOW AGENT RETRIEVAL LLM DOMAIN MCP CONNECTOR PROVIDER
VERIFICATION SECURITY PERSISTENCE INSTALLER DIAGNOSTIC EVALUATION
```

Payload·Metadata 최대 16 KiB. 원문 대신 수량·Hash·상태·지연을 기록한다.

## 4. JSONL Log

```
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
- Connector·Provider read·write·verification. P0 Google Workspace는 `connector_id=google_workspace`로 기록
- SQLite transaction·busy·migration·backup
- Evaluation item·candidate·trial·grader·budget stop

평가 전용 Event 예:

```
EVALUATION_ITEM_STARTED
EVALUATION_ITEM_COMPLETED
NODE_ORACLE_RUN_COMPLETED
NODE_LIVE_RUN_COMPLETED
TRAJECTORY_GRADED
END_STATE_GRADED
GRADER_DISAGREEMENT_RECORDED
EXPERIMENT_BUDGET_STOPPED
```

### 5.1 Component Circuit · Run Budget 관측 projection

Runtime operational event identity:
- `COMPONENT_CIRCUIT_OPENED(component, retry_at_ms, failure_code)`
- `COMPONENT_CIRCUIT_PROBE_SUCCEEDED(component)`
- `COMPONENT_CIRCUIT_REOPENED(component, retry_at_ms, failure_code)`
- `RUN_BUDGET_EXHAUSTED(run_id, budget_kind, used, limit)`

Metric/Diagnostic projection은 `circuit_kind + connector_id? + llm_runtime? + state + retry_at_ms` 및 bounded used/limit만 노출한다. `CONNECTOR` key는 connector_id로 correlation하고 Provider 이름을 Core circuit enum으로 승격하지 않는다. OAuth/LLM secret, raw MCP/Provider payload, Prompt text는 event attribute에 넣지 않는다. Circuit event는 Domain truth가 아니며 06/10 operational control state를 관측한다.

## 6. Audit 필수 Event

```
RUN_STARTED
RUN_ANALYSIS_STARTED
RUN_RETRIEVAL_STARTED
RUN_PLANNING_STARTED
CONFIRMATION_REQUESTED
CONFIRMATION_RESUMED
PLAN_PUBLISHED
READ_PLAN_PUBLISHED
POLICY_CONFIRMATION_RECORDED
REVIEW_RESULT_RECORDED
ACTION_PROPOSED
ACTION_MODIFIED
ACTION_APPROVED
ACTION_REJECTED
ACTION_CANCELLED
ACTION_EXPIRED
ACTION_REFRESHED
ACTION_RETRY_PREPARED
ACTION_READ_CLAIMED
ACTION_READ_EXECUTED
ACTION_READ_VERIFIED
ACTION_READ_FAILED
APPROVAL_REVOKED
APPROVAL_EXPIRED
APPROVAL_CONSUMED
POLICY_BLOCKED
RUN_CANCEL_REQUESTED
RUN_CANCELLED
RUN_BLOCKED
RUN_VERIFICATION_STARTED
RUN_COMPLETED
RUN_REAUTH_REQUIRED
RUN_REAUTH_RESUMED
EXECUTION_CLAIMED
EXECUTION_DISPATCH_STARTED
EXECUTION_CLAIM_ABORTED
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

필수 lifecycle Audit mapping의 Command key set은 **Domain State Transition Contract의 current lifecycle command-family closed set과 exact equality**여야 한다. `ResolveRecovery`처럼 disposition coverage가 별도로 필요한 Command는 owning State Contract의 current disposition set도 누락 0으로 검증한다. 숫자 count를 별도 authority로 복제하지 않는다. 같은 command replay는 새 Audit를 중복 append하지 않는다.

| Lifecycle Command | Required Audit event |
| --- | --- |
| `StartRun` | `RUN_STARTED` |
| `StartAnalysis` | `RUN_ANALYSIS_STARTED` |
| `BeginRetrieval` | `RUN_RETRIEVAL_STARTED` |
| `BeginPlanning` | `RUN_PLANNING_STARTED` |
| `RequestConfirmation` | `CONFIRMATION_REQUESTED` |
| `ResumeConfirmation` | `CONFIRMATION_RESUMED` |
| `CompleteAnswerOnlyRun` | `RUN_COMPLETED(completion_mode=ANSWER_ONLY)` |
| `CompleteReadOnlyRun` | `RUN_COMPLETED(completion_mode=READ_ONLY)` |
| `PublishPlan` | `PLAN_PUBLISHED` |
| `PublishReadOnlyPlan` | `READ_PLAN_PUBLISHED` |
| `BlockRun` | `RUN_BLOCKED` + policy-origin이면 `POLICY_BLOCKED` |
| `BeginVerification` | `RUN_VERIFICATION_STARTED` |
| `CompleteWriteRun` | `RUN_COMPLETED(completion_mode=WRITE)` |
| `RequestCancel` | `RUN_CANCEL_REQUESTED` |
| `FinalizeCancel` | `RUN_CANCELLED` |
| `RequireReauth` | `RUN_REAUTH_REQUIRED` |
| `ResumeAfterReauth` | `RUN_REAUTH_RESUMED` |
| `RequireRecovery` | `RECOVERY_REQUIRED` |
| `ResolveRecovery(RECHECK)` | `RECOVERY_RESOLVED(resolution=RECHECK)` only when applied=true |
| `ResolveRecovery(ACCEPT_PARTIAL)` | `RECOVERY_RESOLVED(resolution=ACCEPT_PARTIAL)` + `RUN_COMPLETED(completion_mode=PARTIAL)` |
| `ResolveRecovery(CREATE_CORRECTIVE_PLAN)` | `RECOVERY_RESOLVED(resolution=CREATE_CORRECTIVE_PLAN)` + `RUN_PLANNING_STARTED` |
| `ResolveRecovery(CANCEL)` | `RECOVERY_RESOLVED(resolution=CANCEL)` + `RUN_CANCELLED` |
| `ResolveRecovery(FAIL)` | `RECOVERY_RESOLVED(resolution=FAIL)` |
| `ApproveAction` | `ACTION_APPROVED` |
| `ModifyAction` | `ACTION_MODIFIED` + ACTIVE Approval revoke 시 `APPROVAL_REVOKED` |
| `RejectAction` | `ACTION_REJECTED` + ACTIVE Approval revoke 시 `APPROVAL_REVOKED` |
| `CancelPendingAction` | `ACTION_CANCELLED` + ACTIVE Approval revoke 시 `APPROVAL_REVOKED` |
| `ExpireApproval` | `ACTION_EXPIRED` + `APPROVAL_EXPIRED` |
| `RefreshExpiredAction` | `ACTION_REFRESHED` |
| `ClaimReadAction` | `ACTION_READ_CLAIMED` |
| `CompleteReadAction` | `ACTION_READ_EXECUTED` |
| `FinalizeReadAction` | `ACTION_READ_VERIFIED` |
| `FailReadAction` | `ACTION_READ_FAILED` |
| `ClaimExecution` | `EXECUTION_CLAIMED` + `APPROVAL_CONSUMED` |
| `BeginExecutionAttempt` | `EXECUTION_DISPATCH_STARTED` |
| `AbortClaimedExecution` | `EXECUTION_CLAIM_ABORTED` |
| `StoreSuccess` | `EXECUTION_SUCCEEDED` |
| `MarkFailed` | `EXECUTION_FAILED` |
| `MarkUnknownResult` | `EXECUTION_UNKNOWN_RESULT` |
| `RecoverExistingResult` | `EXECUTION_RECOVERED` |
| `ResolveAsFailed` | `EXECUTION_FAILED(recovered_from_unknown=true)` |
| `StoreVerification(VERIFIED)` | `VERIFICATION_VERIFIED` |
| `StoreVerification(MISMATCH)` | `VERIFICATION_MISMATCH` |
| `PrepareWriteRetry` | `ACTION_RETRY_PREPARED` |

`RecordReviewResult`는 lifecycle Command가 아닌 Application persistence operation이며 `REVIEW_RESULT_RECORDED`를 같은 short UoW에 기록한다. `POLICY_CONFIRMATION_RECORDED`는 Policy Confirmation Receipt persistence event다. 이 두 event를 Domain lifecycle Command로 승격하지 않는다.

안전 Command의 Audit 저장 실패는 Command 실패다. `POLICY_CONFIRMATION_RECORDED`는 `confirmation_receipt_id`, `interrupt_id`, `confirmation_kind(SCOPE_EXPANSION|DUPLICATE_OVERRIDE|CONFLICT_OVERRIDE)`, `decision(APPROVED|DECLINED)`, `decision_context_hash`, 관련 Run·Resource/Route ID만 allowlist로 기록하고 질문/응답 원문이나 Connector Source 본문은 기록하지 않는다. APPROVED Receipt는 LangGraph Checkpoint의 `PolicyConfirmationReceiptV1`과 동일 ID/Context Hash를 가져 Approval Snapshot이 참조할 수 있어야 한다. P0 Audit는 Application-level append-only이며 암호학적 Tamper Evidence는 P1 검토다.

### 6.1 Reauth Audit mapping

보안 민감 재인증 전이는 관측 owner에서 다음 event identity로 닫는다.

- `RUN_REAUTH_REQUIRED`: `RequireReauth`가 applied되어 Run이 재인증 suspend 경계에 들어간 사실. `run_id`, `reason_code`, connector/account reference, checkpoint presence만 기록하고 token/secret/raw credential은 기록하지 않는다.
- `RUN_REAUTH_RESUMED`: `ResumeAfterReauth`가 registered same-run resume target 검증을 통과해 재개된 사실. `run_id`, `graph_version`, owner subgraph, resume target ref의 bounded identifier만 기록한다.

08의 `Receipt/Audit` 표기는 위 event에 매핑하며 다른 문서가 별도 reauth event 이름을 발명하지 않는다.


### 6.2 Workflow handoff / operational replay events

Trace event closed additions:

```text
WORKFLOW_HANDOFF_STAGED
WORKFLOW_HANDOFF_SUBMIT_RESULT
WORKFLOW_HANDOFF_REDRIVEN
WORKFLOW_HANDOFF_CONSUMED
WORKFLOW_HANDOFF_BINDING_BLOCKED
EXTERNAL_LLM_SCOPE_PUBLISHED
OPERATIONAL_COMMAND_RESERVED
OPERATIONAL_COMMAND_RECOVERY_REQUIRED
OPERATIONAL_COMMAND_RECONCILED
```

Handoff events record `handoff_id`, `trigger_command_id`, `run_id`, target kind/stage/semantic owner, checkpoint generation, status/reason code and payload hash only. Confirmation free text, ContextAdjustment requested text, raw checkpoint/control payload are not logged. `EXTERNAL_LLM_SCOPE_PUBLISHED` records scope revision/hash and bounded source/data-class enums before provider call.

## 7. Sanitization

Pipeline:

```
Schema 검증 → Field Allowlist → Secret·PII Redaction → 길이 제한 → Sink Projection
```

금지:

- OAuth Token·API Key·Authorization·Cookie
- Bootstrap·Session·PKCE
- Connector Source·Draft 전체 본문
- P0 Gmail 첨부파일 bytes·Staging File 원문·로컬 파일 경로
- 첨부파일 filename·전체 content SHA-256 같은 불필요한 식별 정보
- LLM Prompt·Completion
- MCP 전체 Request·Response
- Approval Snapshot 전체
- Home Path·Windows User Name

평가 Artifact에도 실제 사용자 데이터, Credential, 전체 Prompt·Completion을 포함하지 않는다. 합성 Fixture의 원문은 Dataset 디렉터리에서만 관리하고 Trace에는 ID·Hash만 기록한다.

## 8. 보존

- App Log 14일
- Terminal Run Trace: owning Run의 configured `retention_days`와 동일하며 default 30일 (`1..30`)
- Audit 90일 고정
- Evaluation Raw Result는 Experiment Config에 명시한 기간
- Purge Batch 최대 500 Row
- Active Write·Migration·Restore 중 Purge 금지

## 9. Prompt Registry Trace

```
prompt_bundle_version
prompt_semantic_bundle_version
prompt_input_contract_version
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

### 9.1 Evaluation Trace 계약

평가 Report는 다음을 연결한다.

```
main_experiment_id       # A | B | C | D | E
experiment_id?           # compatibility-only reproduction alias
dataset_suite_id         # current 13 Evaluation registered suite ID
episode_variant_id?      # Product Episode variant only
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
scoring_contract_version
```

기록해야 하는 집계:

```
llm_call_count
provider_http_request_count
mcp_tool_call_count
provider_api_call_count
input_token_count
output_token_count
cost_usd
p50_latency_ms
p95_latency_ms
repair_count
revision_count
retrieval_round_count
```

규칙:

- `ORACLE`과 `LIVE` Node Run을 같은 결과로 합치지 않는다.
- Candidate Config Hash가 다른 결과를 같은 후보 집계에 합치지 않는다.
- Budget Stop·Partial Run은 Full Run과 동일 순위로 비교하지 않는다.
- Safety·Tool·Argument·End-state 결과는 결정적 Grader 결과를 우선한다.
- LLM Judge 결과에는 `grader_version`과 Human Calibration 상태를 기록한다.

## 10. Diagnostic Bundle

포함: Manifest, System Summary, Health, Sanitized Logs, Trace·Audit·Migration Summary

제외: DB·Backup 원본, Keyring, Connector 원문, Prompt·Completion, Approval Snapshot, 실험 Gold 원문

크기 상한은 configured `DIAGNOSTIC_BUNDLE_MAX_BYTES`, 기본 시간 범위는 configured `DIAGNOSTIC_BUNDLE_DEFAULT_WINDOW_MS`를 사용하며 사용자가 명시한 Run 하나를 scope로 선택할 수도 있다. exact 숫자는 `10 Infrastructure` configuration만 소유한다. 자동 업로드 금지.

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

```
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

기록 가능: `command_id`, `command_type`, Request Hash 앞 12자리, Aggregate ID, 결과 코드, Claim Token Version, 거절 사유, Attachment 수·총 byte 수 같은 비식별 집계.

Claim V2 검증 Trace는 `version`, 검증 단계, 거절 reason code만 기록한다. `approval_arguments_hash`, `execution_arguments_hash`, Nonce, Signature, Attachment content hash 원문은 일반 Log·Trace에 기록하지 않는다.

기록 금지: Claim Token 원문, Service–MCP Session Key, Authorization Code, PKCE Verifier, Access·Refresh Token.

## 13. Agent Failure·Retry·Query 관측 계약

이 절의 failure/retry 의미는 `15 Agent Capability · Failure · Prompt 공통 계약`의 current contract를 직접 참조한다.

Trace 추가 필드:

```
failure_reason_codes
failure_origin
detected_by
runtime_disposition
experiment_disposition
retry_kind
attempt_no
previous_llm_call_id
validator_codes
changed_field_paths
stop_reason
query_attempt_id
budget_profile
```

Prompt Trace는 Base PromptRef와 `activation_status`를 기록하고, `failure_reason_code`는 **Failure Block assembly metadata**로 연결한다. `failure_reason_code`를 Runtime Prompt Slot Key로 사용하지 않는다. Query Trace는 `SEARCH`, `NEXT_PAGE`, `DETAIL_FETCH`, `FREEBUSY`를 구분하고 Retrieval·Score·Threshold Config Version을 기록한다. Pagination 관측에는 `read_result_handle` 식별용 안전 hash, query/page state hash, `has_next_page`, exhaustion/result count 같은 bounded metadata만 기록하며 raw Provider `next_page_token` 원문은 Log·Trace·Audit에 기록하지 않는다.

금지 사항은 유지한다. Prompt·Completion 원문, Connector 원문 전체, Credential, Holdout Gold 원문은 Trace·Audit·Operational Log에 저장하지 않는다.

## 14. Agent Subgraph 관측 계약

Agent 수와 LLM Call 수를 분리해 기록한다.

```
graph_profile
semantic_agent_owner_id
compiled_subgraph_id
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
communication_token_count?     # Typed Handoff payload의 token 추정 합계
required_field_preserved_count?
constraint_loss_count?
evidence_id_loss_count?
contradiction_count?
tool_call_count
duplicate_tool_call_count?
mcp_read_tool_call_count
coordination_wait_ms?
```

- `agent_invocation_count`와 `llm_call_count`를 별도 집계한다.
- 제품 Core의 외부 Connector 호출량은 `connector_id`로 구분한 `mcp_tool_call_count`/`mcp_read_tool_call_count`를 기준으로 본다. `provider_api_call_count`는 각 Connector MCP Server 내부 Adapter가 실제 Provider API를 호출한 횟수로, MCP 내부 효율·pagination/N+1 진단용 보조 지표다. Core에서 Provider API 직접 호출을 허용한다는 의미가 아니다. P0 Google Workspace는 `connector_id=google_workspace`로 집계한다.
- Local State 원문, Prompt 원문, Completion 원문, Connector 원문 전체는 Trace에 저장하지 않는다.
- Handoff는 Agent 간 자유 대화가 아니라 Parent Graph의 Typed Result 이동으로 기록한다.
- Experiment D가 SINGLE/THREE/SIX Architecture 비교의 제품 결정을 소유한다. Architecture diagnostic은 Profile native cost와 동일 `ContextReadySnapshotV1.context_snapshot_id` 기반 post-retrieval decomposition을 분리해 측정하며, controlled post-retrieval diagnostic의 Connector Read 호출은 0이어야 한다.
- Evaluation Summary에는 `safety_contract_pass`, `business_outcome_pass`, `business_task_success`, 선택적으로 `end_state_pass`, `semantic_completion_pass`, `denominator_group(CORE|STRESS|HOLDOUT|PRODUCT_EPISODE|SYNTHETIC_MULTI_CONNECTOR)`, `scoring_contract_version`을 기록한다. Historical result-field alias는 current production Event schema에 추가하지 않고 재현 adapter에서만 변환한다.
- Core·Stress·Holdout을 하나의 headline denominator로 합치지 않는다.
