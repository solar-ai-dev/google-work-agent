# 11. Google Work Agent · 관측성 · 로그 · 감사 설계서

> **상태:** Draft v2.2 · **외부 Telemetry:** Production 기본 OFF

## 1. 채널

| 채널 | 목적 | 저장 |
|---|---|---|
| Operational Log | Process·Adapter·Startup | Sanitized JSONL |
| Trace | Run·Node·Agent·Tool·성능 | SQLite `trace_events` |
| Audit | 승인·정책·실행·검증·복구 | SQLite `audit_events` |
| SSE | React 진행 Projection | 제한 Buffer·재생성 |
| Metric | Local 집계 | Trace·Audit 계산 |

Domain Store가 사실 기준점이며 Trace·SSE는 상태를 대체하지 않는다.

## 2. Correlation

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

Category: LIFECYCLE, API, WORKFLOW, AGENT, RETRIEVAL, LLM, DOMAIN, MCP, GOOGLE, VERIFICATION, SECURITY, PERSISTENCE, INSTALLER, DIAGNOSTIC.

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

## 6. Audit 필수 Event

```text
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

안전 Command의 Audit 저장 실패는 Command 실패다. P0 Audit는 Application-level append-only이며 암호학적 Tamper Evidence는 P1 검토다.

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

## 8. 보존

- App Log 14일
- Trace 30일
- Audit 90일
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

Prompt 원문은 기록하지 않는다. 평가 Report는 `case_id`, `fixture_snapshot_id`, `user_prompt_id`, `prompt_id`, `model_id`, `graph_version`을 연결한다.

## 10. Diagnostic Bundle

포함: Manifest, System Summary, Health, Sanitized Logs, Trace·Audit·Migration Summary
제외: DB·Backup 원본, Keyring, Google 원문, Prompt·Completion, Approval Snapshot
최대 20 MiB, 최근 24시간 또는 Run 하나. 자동 업로드 금지.

## 11. Local Alert

즉시 표시:
- Service·DB·Migration 실패
- MCP 반복 종료
- OAuth 재인증
- UNKNOWN_RESULT·RECOVERY_REQUIRED
- Contract Version 불일치
- Signature·Manifest 오류

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
