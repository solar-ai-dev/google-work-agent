# 04. 도메인 · 데이터베이스 설계서

> **Authority:** Domain aggregate·persistent fact·transaction/invariant semantics. Lifecycle command/guard는 `Domain State Transition Contract`, repository placement는 `16`이 소유한다.

## 0. 문서 정보

| 항목 | 내용 |
| --- | --- |
| 문서명 | 04. Google Work Agent 도메인 · 데이터베이스 설계서 |
| 상태 | Draft v1.27 |
| 기준일 | 2026-08-24 |
| 대상 | P0 MVP |
| Database | SQLite |
| 저장 형태 | 하나의 제품 DB 파일 · Domain과 LangGraph Checkpoint 논리 분리 |

## 1. 목적과 범위

이 문서는 Google Work Agent의 Domain Aggregate, Entity, Value Object, Table, 관계, **lifecycle 결과의 persistence realization**, Transaction, 동시성, 멱등성, Pagination, N+1 방지, Index, Migration, Backup, Restore와 보존 정책을 정의한다. lifecycle command·허용 source state·guard·transition 자체는 Domain State Transition Contract를 참조하며 이 문서가 재정의하지 않는다.

### 1.1 범위

- Conversation·Run·Plan·Action Domain
- Connector Resource 참조와 Evidence. DB Schema v1.9은 `actions.connector_id`와 `resource_refs.connector_id`를 영속하고 `ResourceRef`의 canonical connector identity를 `(run_id, connector_id, resource_type, resource_id)`로 고정한다. 여기서 `resource_id`는 Connector Provider가 부여한 external resource identifier를 저장하는 canonical persistence field다. current `ResourceRef.resource_type`은 해당 Resource를 만든/선택한 `SignedToolRegistryEntryV1.resource_type`을 exact-copy한다. P0 허용값은 current Signed Tool Registry의 Google Workspace resource vocabulary에 닫혀 있으며 새 Resource Type 추가 시에는 Registry 계약과 새 Migration을 함께 확장한다. 별도 `THREAD|MESSAGE|EVENT` 또는 `EMAIL|TASK|CALENDAR` 변환 vocabulary를 current persistence authority로 두지 않는다.
- Approval·Execution·Verification
- Trace·Audit
- SQLite DDL과 Connection 설정
- Connector Provider API·DB Batch 조회 경계
- Optimistic Lock과 짧은 SQLite Write Lock

### 1.2 비범위

- LangGraph Library Checkpoint Table 내부 Schema
- Tool별 Arguments JSON 상세 Schema
- Connector Provider API Request·Response Schema
- Vector DB·Embedding Index
- Experiment Result 저장소

## 2. 최종 설계 결정

| ID | 결정 | 이유 |
| --- | --- | --- |
| DB-001 | P0는 SQLite 파일 하나를 사용 | Domain과 Checkpoint를 한 번에 Backup·Restore하며 단일 사용자 부하에 충분하다. |
| DB-002 | Domain과 Checkpoint는 논리적으로 분리 | Checkpoint는 Workflow 재개, Domain은 승인·실행 사실의 기준점이다. |
| DB-003 | Connector Sidebar 목록·Local API continuation·Provider browse batch는 React Client Session Cache | 외부 Provider 원본 전체를 로컬에 복제하지 않는다. P0 Google Workspace의 Gmail page mapping, Tasks incomplete/completed batch, Calendar Month materialization은 세션 범위 UI cache이며 Domain 사실이 아니다. |
| DB-004 | 실제 사용 Resource와 최소 Evidence만 저장 | 대화 복구·승인 근거를 유지하면서 원문 보존을 최소화한다. |
| DB-005 | 핵심 관계·상태는 정규화 | Join·Constraint·상태 전이를 DB에서 검증한다. |
| DB-006 | 가변 Arguments와 불변 Snapshot은 JSON | Tool별 구조 변화와 승인 당시 값을 보존한다. |
| DB-007 | 외부 호출과 DB Transaction 분리 | MCP·LLM 외부 호출 중 SQLite Write Lock을 유지하지 않는다. |
| DB-008 | Optimistic Lock + 짧은 BEGIN IMMEDIATE | 분산 Lock 없이 REST Command Retry·브라우저 새로고침·중복 클릭·복합 작업 경쟁을 차단한다. |
| DB-009 | Local Keyset Cursor와 Connector Provider continuation 분리 | 각 저장소와 Connector Provider의 Pagination 계약을 혼용하지 않는다. P0 Google Page Token은 이 일반 계약의 첫 구현이다. |
| DB-010 | Aggregate 단위 Batch 조회 | N+1을 막되 거대한 Join의 Row 곱집합은 피한다. |

## 3. 저장 위치와 소유권

### 3.0 Local API와 상태 기준점

- React Client State와 SSE Event는 화면 Projection이며 승인·실행 사실의 기준점이 아니다.
- FastAPI Route는 Repository SQL을 직접 실행하지 않고 Application use-case boundary를 호출한다.
- 동일 상태 변경 REST Command 재전송은 `command_id + canonical request hash`의 Command Receipt로 판정하고, mutable Aggregate 갱신 경쟁은 `expected_version` 기반 조건부 상태 전이로 차단한다. Write 실행 중복 방지는 이 Command Receipt와 별도로 Approval Snapshot·Action Version·Idempotency Key 계약을 따른다.
- SSE 연결 유실은 Domain 상태를 변경하지 않으며 재연결 후 REST Query로 현재 상태를 복원한다.
- Frontend Sidebar Cache와 Google Page Token은 SQLite에 저장하지 않는다.

```
%LOCALAPPDATA%/GoogleWorkAgent/
├─ data/
│  └─ google_work_agent.db
├─ backups/
│  ├─ pre-migration-<timestamp>.db
│  └─ manifest.json
├─ settings/
│  └─ app-settings.json
└─ logs/
   └─ sanitized-*.log
```

| 데이터 | 기준 저장소 |
| --- | --- |
| Conversation·Run·Plan·Action | SQLite Domain Table |
| Approval·Execution·Verification | SQLite Domain Table |
| Command Receipt | SQLite Domain Table (`command_receipts` durable idempotency/replay authority) |
| Workflow Handoff | SQLite Application-control Table (`workflow_handoffs`; Domain lifecycle authority가 아닌 crash-safe outbox) |
| LangGraph State·Interrupt | 같은 SQLite 파일의 Library 관리 Table |
| Google Sidebar 목록·Local API continuation·Tasks/Calendar materialized browse cache | React Client Session Cache |
| Agent 검색 중간 후보·전체 원문 | 현재 Run 메모리 |
| Gmail 첨부파일 bytes | SQLite 비저장. 사용자 다운로드는 Stream, 발신은 짧은 TTL의 Local Attachment Staging |
| 실제 사용 Resource·Evidence excerpt | SQLite Domain Table |
| Google Refresh Token | Domain/SQLite 비저장. 09/10의 OS Keyring lifecycle 소비 |
| Google Access Token | Domain/SQLite 비저장. Connector MCP Credential Provider process memory only |
| LLM API Key | Domain/SQLite 비저장. 09/10의 `KEYRING | SESSION_ONLY` lifecycle 소비 |
| UI 비밀 아닌 설정 | app-settings.json |
| Experiment Raw Result | 제품 DB와 분리된 Artifact |

## 4. 도메인 경계와 Aggregate

### 4.1 Conversation Aggregate

**Aggregate Root:** `Conversation`

- `Conversation`
- `Message`
- `Run`

불변 조건:

- 현재 DB Schema v1.9에서도 Conversation은 하나의 Google Account에 속한다. 이는 P0 Google Workspace-first 영속 계약이며 Connector-neutral Core의 장기 의미로 승격하지 않는다.
- `0007/0008`은 Action·ResourceRef의 connector identity를 일반화했지만 Conversation 소유권과 Connector Credential/Account 연결까지 일반화하지는 않았다. 두 번째 Connector가 Conversation-level account ownership을 요구하면 별도 새 Migration으로 확장하며 적용 Migration을 소급 수정하지 않는다.
- Conversation당 `finished_at_ms IS NULL`인 Run은 최대 1개다.
- Message는 Conversation에 속하고 선택적으로 Run을 참조한다.

### 4.2 Planning Aggregate

**Aggregate Root:** `Plan`

- `Plan`
- `Action`
- `ActionDependency`
- `ActionEvidence`

불변 조건:

- Plan Revision은 같은 Run 안에서 1부터 증가한다.
- current published Plan이 `SUPERSEDED`로 전이되는 UoW는 해당 Plan Action의 모든 `ACTIVE` Approval을 먼저 `REVOKED`로 만들고 같은 transaction에서 Plan supersession을 commit한다. `SUPERSEDED` Plan 아래에 `ACTIVE` Approval이 남는 snapshot은 불가능하다.
- `SUPERSEDED` Plan의 Action/Approval은 history로 조회할 수 있지만 새 Approval/Attempt/Write authority가 아니다. Action lifecycle conditional write와 Claim은 owning Plan이 current published Plan이며 `Plan.status=WAITING_APPROVAL`인지 함께 검증한다.
- Action의 Position은 Plan 안에서 유일하다.
- 모든 실행 가능한 Action은 최소 1개 Evidence를 가진다.
- Dependency는 자기 자신을 참조하지 않고 DAG여야 한다. Cycle 생성·검사는 deterministic Planning Application operation `planning.build_dependencies`와 `planning.validate_plan`이 수행하고, Domain은 published Plan의 aggregate invariant만 guard한다.

### 4.3 Execution Aggregate

**Aggregate Root:** `Action`

- `Approval`
- `ExecutionAttempt`
- `Verification`

불변 조건:

- Action 수정은 `version`을 증가시킨다.
- Action당 ACTIVE Approval은 최대 1개다.
- Approval당 CLAIMED·EXECUTING·UNKNOWN_RESULT Attempt는 최대 1개다.
- Approval Snapshot과 Domain `arguments_hash`가 현재 Action과 일치하고, Action의 owning Plan이 current published Plan(`WAITING_APPROVAL`)이며 Run이 Claim을 허용하는 `WAITING_APPROVAL | VERIFYING`일 때만 실행권을 Claim한다. `Action=APPROVED + Approval=ACTIVE`만으로는 충분하지 않다. 이 DB Hash는 `07`의 `approval_arguments_hash`에 해당한다.
- `SCOPE_EXPANSION_REQUIRED`, `DUPLICATE_OVERRIDE_REQUIRED`, `CONFLICT_OVERRIDE_REQUIRED`처럼 정책상 별도 사용자 확인이 필요한 결정은 `PolicyConfirmationReceiptV1`로 고정한다. Receipt 원문을 위한 새 Table은 만들지 않고 LangGraph Checkpoint의 Typed State와 append-only `audit_events`로 보존하며, Write Action에 필요한 승인형 Receipt의 ID·결정 Context Hash는 Approval Snapshot JSON에 포함한다. Approval 시점에 필요한 Receipt가 없거나 현재 Action/Evidence/Route와 Context Hash가 맞지 않으면 Approval/Claim을 허용하지 않는다. 이 기능 자체는 기존 JSON Snapshot/Audit Event를 사용하며 별도 Migration을 요구하지 않는다. 이후 `0006~0008`은 Plan Aggregate 무결성과 connector identity라는 별도 concern을 위해 추가되었다.
- 실제 MCP Dispatch Payload의 `execution_arguments_hash`는 Claim 발급 시점의 전송 무결성 값이며 Domain DB에 별도 영속 Column을 추가하지 않는다. 첨부파일 bytes 역시 Domain DB에 저장하지 않는다.
- 모든 성공 Write Attempt는 Effect별 결정적 Verification으로 종료한다. CREATE·UPDATE는 GET 비교, DELETE는 대상 부재/삭제 상태 확인, SEND는 Sent 결과 조회를 사용한다.

### 4.4 Evidence Aggregate

- `ResourceRef`
- `Evidence`

`ResourceRef`는 Connector 원본의 복제본이 아니라 Run에서 실제로 사용한 최소 참조다. `Evidence`는 Action 판단과 승인 설명에 필요한 최소 excerpt만 저장한다.

**Connector 일반화 경계:** Core와 DB Schema v1.9의 ResourceRef identity는 `connector_id + resource_type + resource_id` 조합이며, `resource_id`가 Connector Provider의 external resource identifier를 담는 canonical persistence field다. `0007`이 `connector_id`를 Action/ResourceRef에 추가하고 기존 Google row를 `google_workspace`로 backfill했으며, `0008`이 pre-connector uniqueness를 제거해 connector-aware identity를 단일 권위로 만들었다. current persistence 의미에서 `resource_type`은 `SignedToolRegistryEntryV1.resource_type`의 exact Connector resource identifier다. 모든 Registry resource가 반드시 ResourceRef row를 요구하는 것은 아니지만, 저장되는 ResourceRef는 별도 family enum으로 변환하지 않는다. 신규 Connector/Resource Type 지원 시에는 concern-owned Tool/Registry 계약과 새 Schema Migration으로 허용값을 확장하며 기존 Migration을 소급 수정하지 않는다.

### 4.5 Observability

- `TraceEvent`: 개발·성능·장애 진단. Terminal Run에 귀속된 Trace는 owning Run의 configured `retention_days`와 같은 창을 사용하며 default가 30일이다. 별도 fixed 30-day authority를 만들지 않는다.
- `AuditEvent`: 정책 확인·승인·수정·거절·차단·실행·검증의 안전 기록, 90일 보존

Audit는 더 긴 보존을 위해 Domain Foreign Key를 사용하지 않고 최소 식별자만 저장한다.

## 5. Entity와 Value Object

| 분류 | 구성 |
| --- | --- |
| Entity | Conversation, Message, Run, Plan, Action, ResourceRef, Evidence, Approval, ExecutionAttempt, Verification, CommandReceipt. `GoogleAccount`는 현재 DB Schema v1.9에서도 P0 Connector-specific 계정 Entity이며 Connector-neutral account model은 후속 Migration 설계 대상이다. |
| Join Entity | ActionDependency, ActionEvidence |
| Append Event | TraceEvent, AuditEvent |
| Value Object | CanonicalArguments, ArgumentsHash, SourceSnapshot, PolicyConfirmationReceiptV1, IdempotencyKey, RecoveryContextV1, RecoveryFingerprint, Cursor, RunBudget, VerificationDiff |

### 5.1 ID와 시간

- Domain ID는 Application이 생성한 UUID 문자열을 사용한다.
- `trace_events`, `audit_events`만 순차 읽기 효율을 위해 INTEGER PRIMARY KEY를 사용한다.
- 모든 시간은 UTC Epoch Millisecond INTEGER로 저장한다.
- Timezone 변환은 Application·UI에서 수행한다.

## 6. ERD

```mermaid
erDiagram
    GOOGLE_ACCOUNTS ||--o{ CONVERSATIONS : "계정의 대화"
    CONVERSATIONS ||--o{ MESSAGES : "대화의 메시지"
    CONVERSATIONS ||--o{ RUNS : "대화에서 실행"
    RUNS ||--o{ PLANS : "계획 개정"
    RUNS ||--o{ RESOURCE_REFS : "사용한 자료"
    RUNS ||--o{ EVIDENCE : "수집한 근거"
    RUNS ||--o{ TRACE_EVENTS : "실행 추적"
    PLANS ||--o{ ACTIONS : "계획의 작업"
    ACTIONS ||--o{ ACTION_DEPENDENCIES : "작업 의존성"
    ACTIONS ||--o{ ACTION_EVIDENCE : "작업의 근거"
    EVIDENCE ||--o{ ACTION_EVIDENCE : "근거 연결"
    ACTIONS ||--o{ APPROVALS : "승인 이력"
    APPROVALS ||--o{ EXECUTION_ATTEMPTS : "실행 시도"
    EXECUTION_ATTEMPTS ||--o{ VERIFICATIONS : "결과 검증"
    RESOURCE_REFS o|--o{ ACTIONS : "대상 자료"
    RESOURCE_REFS o|--o{ EVIDENCE : "근거 원본"
    MESSAGES o|--o{ EVIDENCE : "사용자 메시지 근거"
```

## 7. P0 Table 목록

| 영역 | Table | 역할 |
| --- | --- | --- |
| Migration | schema_migrations | Version·Checksum·적용 시각 |
| Account | google_accounts | Google 계정 식별, Credential 비저장 |
| Conversation | conversations | 대화 Timeline의 영속 Root |
| Conversation | messages | 사용자·Agent Text |
| Run | runs | Agent 실행과 Runtime·Budget |
| Planning | plans | Plan Revision |
| Planning | actions | Tool Action 현재 상태 |
| Planning | action_dependencies | Action DAG Edge |
| Context | resource_refs | 사용된 Google Resource 최소 참조 |
| Context | evidence | 최소 근거 excerpt |
| Context | action_evidence | Action·Evidence 다대다 관계 |
| Approval | approvals | 승인 Revision·Snapshot·Hash |
| Execution | execution_attempts | Retry·UNKNOWN_RESULT |
| Verification | verifications | GET expected·actual·diff |
| Observability | trace_events | Run Trace |
| Command | command_receipts | 상태 변경 Command의 durable request identity·적용 결과·replay adjudication |
| Workflow Control | workflow_handoffs | committed Domain/user control → background continuation durable outbox; typed one-shot control payload와 target binding |
| Audit | audit_events | Append-only 안전 기록 |

`command_receipts.aggregate_id`는 여러 Aggregate Command를 포괄하는 논리 상관관계 값이며 모든 Aggregate에 대한 범용 FK를 의미하지 않는다. StartRun처럼 대상 Row 생성과 같은 Transaction에서 identity가 확정되는 Command도 있으므로 polymorphic hard FK를 임의 추가하지 않는다.

## 8. 핵심 Table 설계

### 8.1 runs

- `entry_mode`: AGENT_SEARCH 또는 RESOURCE_SELECTED
- `requested_mode`: `AUTO | LOCAL_GPU | API_LLM`; StartRun에서 immutable snapshot, same-Run restart/resume authority
- `status`: Workflow의 현재 단계
- `langgraph_thread_id`: Checkpoint 재개 Key
- `budget_json`: 호출 수·Token·Retry·시간 상한 Snapshot
- `version`: 낙관적 상태 전이
- `finished_at_ms IS NULL`: Open Run

Partial UNIQUE Index로 Conversation당 Open Run 하나를 보장한다.

### 8.2 plans와 actions

Plan을 수정할 때 기존 Revision을 덮어쓰지 않고 새로운 `revision_no`를 추가한다. Action의 현재 Arguments는 `arguments_json`, 승인 대상 Hash는 `arguments_hash`, 실행 후 기대값은 `expected_json`에 저장한다.

Action 자체의 전체 Revision Table은 P0에서 만들지 않는다. 승인 당시 불변값은 Approval Snapshot, 변경 사실은 Audit로 보존한다.

### 8.3 resource_refs와 evidence

- Connector Provider 전체 원문·Sidebar Cache는 Domain DB에 저장하지 않는다. Resource List의 `selection_handle`은 Local API/Application의 ephemeral authenticated wire identity이며 DB row가 아니다. `RESOURCE_SELECTED` StartRun에서 handle 검증이 끝난 identity만 새 Run의 StartRun UoW 안에서 최소 `ResourceRef`로 materialize한다.
- 동일 `(run_id, connector_id, resource_type, resource_id)`는 한 번만 저장한다. `source` 같은 pre-connector 분류를 canonical uniqueness key로 다시 사용하지 않는다.
- FreeBusy 같은 비Resource 조회 전체 응답은 ResourceRef로 저장하지 않고 Derived Evidence로 필요한 결과만 보존한다.
- `version_token`은 Connector별 Provider version/etag/history/update 의미를 해당 Connector MCP Server Adapter가 정규화한다. P0 Google Workspace에서는 Gmail history/internal date, Google ETag·updated 등이 첫 구현 예다.

### 8.4 approvals

Approval은 Action 현재값과 분리된 승인 이력이다.

- `approval_no`: Action 내 승인 순번
- `action_version`: 승인된 Action Version
- `status`: ACTIVE·EXPIRED·CONSUMED·REVOKED
- `arguments_snapshot_json`: 승인 당시 Arguments
- `source_snapshot_json`: 관련 Resource ID·Version Token 목록
- `idempotency_key`: 한 Approval 실행 문맥
- `recovery_fingerprint`: Connector Write 응답 유실·결과 불명 시 동일 외부 Effect의 기존 결과 후보 탐색

같은 Action Version도 Approval 만료 후 다시 승인할 수 있으므로 `(action_id, action_version)` UNIQUE는 사용하지 않는다. 대신 Action당 ACTIVE Approval 하나만 허용한다.

### 8.5 execution_attempts와 verifications

- Write `FAILED` 재시도는 기존 Approval·Idempotency Key·Attempt를 재사용하지 않는다. `PrepareWriteRetry: FAILED → MODIFIED` 후 Review/Domain Validation을 다시 통과하고 **새 Approval**을 생성하며, 새 Approval의 고유 `approval_id` 때문에 새 `idempotency_key`가 생성된다. 새 Approval에서 첫 `ExecutionAttempt.attempt_no`는 1이다.
- 하나의 Approval에 실행 중·결과 불명 Attempt는 동시에 하나만 존재한다.
- `UNKNOWN_RESULT` 해결 전 새 Approval·새 Write Attempt·새 Write를 만들지 않는다.
- Connector dispatch 결과의 `delivery_certainty`는 `execution_attempts.response_metadata_json.delivery_certainty`에 `NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST` 중 하나로 영속한다. `error_detail_json`은 오류 상세를 담되 전달 확실성의 기준점으로 사용하지 않는다. 별도 Column을 추가하지 않는다.
- `BeginExecutionAttempt(applied=true)` commit은 **dispatch-intent uncertainty cut**이다. 이 commit 이후 결과 persistence 전에 process loss가 발생하면 실제 Connector callable 진입 여부를 추측하지 않고 `MAY_HAVE_BEEN_SENT`로 보수적으로 reconcile한다. `NOT_SENT`는 Begin 전 실패이거나 live Connector/MCP boundary가 provider dispatch 0을 명시적으로 증명한 경우에만 기록한다. 추가 `DISPATCH_STARTED` column/marker를 만들지 않는다.
- Post-Begin process-loss reconciliation은 새 table/status를 만들지 않고 existing durable facts를 phase marker로 사용한다. Repository projection `ExecutionReconciliationCandidateV1`의 closed kinds는 `POST_BEGIN_ORPHAN | UNKNOWN_RESULT_UNRESOLVED | EXECUTED_AWAITING_VERIFICATION | FAILED_AWAITING_CONTINUATION`이다. `POST_BEGIN_ORPHAN`은 Attempt=`EXECUTING` + APPLIED Begin receipt + terminal dispatch result 없음, `UNKNOWN_RESULT_UNRESOLVED`는 Action/Attempt=`UNKNOWN_RESULT` + matching active RecoveryContext 없음, `EXECUTED_AWAITING_VERIFICATION`은 Action=`EXECUTED` + Verification 미완료다. `FAILED_AWAITING_CONTINUATION`은 reconciliation의 deterministic `ResolveAsFailed` Receipt가 존재하고 current cancel intent 또는 다른 approved/executable Action 때문에 automatic continuation이 필요한 경우다; stable FAILED user-decision/retry wait는 제외한다. 이 projection은 startup-only Application reconciliation에서만 소비하며 current live worker ownership을 판단하는 lease가 아니다.
- Reconciliation의 각 state-changing sub-command는 deterministic identity를 사용한다: base `system:execution-attempt-reconcile:<execution_attempt_id>`는 `MarkUnknownResult`, suffix `:recover-existing | :resolve-failed | :require-recovery | :begin-verification | :resolve-recovery-recheck`는 해당 기존 Domain command의 replay identity다. Verification continuation은 `system:execution-attempt-reconcile:<execution_attempt_id>:verification`, resolved-failed automatic continuation은 `...:post-failed` WorkflowHandoff trigger로 dedupe한다. 따라서 `MarkUnknownResult`/`RecoverExistingResult`/`BeginVerification` 중 어느 commit 뒤에 crash가 나도 durable state 또는 staged handoff가 다음 startup phase를 결정한다.
- 모든 성공 Write Attempt는 Effect별 하나 이상의 Verification을 가진다.

### 8.6 Command Receipt durable persistence

상태 변경 Command의 `CommandReceipt`는 HTTP 캐시나 Audit 대체물이 아니라 **Domain DB의 durable idempotency record**다. 최소 논리 필드는 다음과 같다.

```
command_id            # unique command identity
command_type
request_hash           # server-computed canonical request hash
aggregate_id
received_at
status                 # RECEIVED | APPLIED | REJECTED
response_summary       # replay 가능한 결정적 Command 결과 요약
```

필수 DB 의미:

- `command_id`는 단일 Receipt identity이며 같은 ID·같은 `request_hash`는 저장된 `APPLIED | REJECTED` 결과를 replay한다.
- 같은 `command_id`·다른 `request_hash`는 기존 Receipt를 덮어쓰지 않고 conflict로 거부한다. 기존 Receipt의 status/result는 불변이며 Domain mutation은 0건이다. 11 Observability가 요구하는 hash-mismatch 보안 Audit은 별도 append-only event로 기록할 수 있다.
- 신규 Command의 `RECEIVED` 예약, Guard 판정, Domain mutation(허용된 경우), 필수 Audit, 최종 `APPLIED | REJECTED` 결과 확정은 §10.0의 같은 짧은 Transaction에 속한다. Guard/Version/State 때문에 적용되지 않은 **신규 command_id**도 결정적 rejection 결과를 `REJECTED` Receipt로 남겨 이후 같은 ID·같은 hash가 미래의 다른 상태에서 재평가되지 않게 한다.
- `RECEIVED`는 같은 Transaction 안의 중간 상태다. 정상 commit 결과는 `APPLIED | REJECTED`여야 하며 committed `RECEIVED`만 남거나 Domain mutation은 있는데 최종 Receipt가 없는 상태는 정상 성공이 아니다. Startup/Recovery는 이를 추측 적용하지 않고 fail-closed reconcile 대상으로 취급한다.
- Audit Event만으로 Command Receipt를 대체하지 않으며, in-memory dedupe만으로 구현하지 않는다.

현재 적용 Schema에 이 durable relation이 없다면 이는 구현 재량이 아니라 **forward migration이 필요한 Domain DB schema blocker**다. 적용된 과거 Migration을 소급 수정해서 해결하지 않는다.


### 8.7 `workflow_handoffs` — Domain commit → background execution durable outbox

`workflow_handoffs`는 Domain Aggregate가 아니라 **same-Run Application/Workflow control persistence**다. 이 절은 row가 보존해야 하는 durable fact와 DB invariant만 정의한다. Workflow target/precedence는 `06`, typed Port·wire operation은 `07`, startup/live driving order는 `10`이 소유한다.

최소 logical fields:

```text
handoff_id                 TEXT PRIMARY KEY
trigger_command_id          TEXT NOT NULL
run_id                      TEXT NOT NULL
langgraph_thread_id         TEXT NOT NULL
graph_profile               TEXT NOT NULL
graph_version               TEXT NOT NULL
requested_mode              TEXT NOT NULL
execution_kind              START | RESUME
resume_target_json          JSON nullable for START only
checkpoint_id               TEXT nullable for START
checkpoint_generation       INTEGER NOT NULL >= 0
run_sequence                INTEGER NOT NULL >= 1
control_kind                NONE | CONFIRMATION_RESPONSE | CONTEXT_ADJUSTMENT | RETRIEVAL_CACHE_RESTART
control_payload_json        bounded canonical JSON or null
control_payload_hash        nullable SHA-256
status                      PENDING | DISPATCHED | CONSUMED | BLOCKED_BINDING | SUPERSEDED
last_submit_reason          nullable non-ACCEPTED submit reason
execution_admission_json    nullable canonical WorkflowExecutionAdmissionV1
applied_checkpoint_id       TEXT nullable
applied_checkpoint_generation INTEGER nullable
created_at_ms
dispatched_at_ms?
consumed_at_ms?
superseded_at_ms?
version                     optimistic integer
```

Persistence invariants:

- workflow continuation이 필요한 owning mutation은 CommandReceipt/Audit와 `PENDING` handoff stage를 **같은 UoW**에서 commit한다. Handoff stage 실패 시 해당 transaction의 lifecycle mutation도 commit하지 않는다.
- `trigger_command_id` replay는 같은 durable handoff identity를 재사용한다. 같은 command identity로 두 개의 control payload authority를 만들지 않는다.
- `run_sequence`는 server-owned same-Run commit order이며 `UNIQUE(run_id, run_sequence)`로 방어한다. `CONSUMED|SUPERSEDED`만 settled다.
- non-NONE control payload는 unconsumed row에서 hash와 함께 durable해야 하고, settled row에서는 body를 지워도 historical `control_kind/hash`는 보존한다.
- worker visibility 전에 execution admission과 `expected_run_version`이 durable해야 한다. Admission claim/release/settlement는 handoff optimistic version과 owning Run authority epoch를 조건부로 검사하며, stale admitted NORMAL row가 lower-sequence head로 부활해서는 안 된다. Exact callable/result shape는 `07`이 소유한다.
- command-time observed checkpoint/binding과 applied checkpoint evidence는 restart 후 exact replay/reconciliation을 판정할 만큼 durable해야 한다. `active_handoff_id/run_sequence` lineage 자체의 workflow release semantics는 `06/07`을 따른다.
- cancel/terminal supersession은 **durable execution admission이 없는** obsolete unconsumed row만 same-UoW에서 retire할 수 있다. 이미 admission이 있는 row의 stale authority 처리는 admission settlement fence로 결정한다.
- `BLOCKED_BINDING`은 데이터 손실이나 임의 latest-checkpoint 선택으로 해소하지 않는다. Recovery orchestration은 `06/07/10`의 owning contract를 소비한다.

이 절에 startup loop, WEP return-code algorithm, registered target matrix를 다시 적지 않는다. 그런 변경이 발생해도 위 durable fact/invariant가 그대로라면 04는 수정 대상이 아니다.

### 8.8 Retrieval revision readable authority

`RetrievalResultV1.meta.revision`의 Application-readable authority는 Domain row나 Plan revision이 아니다. LangGraph adapter가 successful Retrieval owner checkpoint를 저장할 때 함께 기록하는 typed **`RetrievalHeadV1(run_id, langgraph_thread_id, retrieval_revision, retrieval_artifact_id, checkpoint_id, checkpoint_generation)`** metadata가 단일 readable authority다.

- `CheckpointPort.load_retrieval_head(run_id)`만 Application Query/CAS가 이 값을 읽는 경로다. Application이 `checkpoint_blob`을 deserialize하지 않는다.
- `ContextPreviewResponseV1.retrieval_revision`과 `ContextAdjustmentRequestV1.expected_retrieval_revision` 비교는 같은 `RetrievalHeadV1.retrieval_revision`을 사용한다. Plan revision/Run version으로 대체하지 않는다.
- successful new Retrieval revision의 checkpoint commit과 RetrievalHead 갱신은 같은 checkpointer transaction이다. app restart 후에도 head가 복원되어 stale CAS를 거부할 수 있다.
- RetrievalHead는 workflow projection metadata이고 Domain semantic fact가 아니므로 새 Domain lifecycle command를 만들지 않는다.

## 9. 상태 전이

> **Authority boundary:** 아래 상태/전이 표기는 Domain persistence와 aggregate 정합성을 설명하기 위한 **derivative projection**이다. lifecycle command·허용 source state·guard·transition의 normative semantics는 `Domain State Transition Contract`가 소유한다. 이 절의 derivative state vocabulary가 State Transition Contract와 다르면 State Transition Contract가 우선한다.

### 9.1 Run status persistence vocabulary

04가 소유하는 것은 Run row에 저장되는 status vocabulary와 persistence/invariant realization이다. 허용 source state와 command별 target state는 Domain State Transition Contract를 참조한다.

```text
CREATED | ANALYZING | RETRIEVING | WAITING_CONFIRMATION | PLANNING | WAITING_APPROVAL |
EXECUTING | VERIFYING | CANCEL_REQUESTED | CANCELLED | REAUTH_REQUIRED | RECOVERY_REQUIRED |
COMPLETED | BLOCKED | FAILED
```

현재 Release 승인형 Write에서 Run `EXECUTING` 사용 여부와 같은 lifecycle 의미도 owning State Transition Contract가 최종 authority다. 이 문서는 DB column/constraint/projection에서 해당 값을 안정적으로 보존하는 책임만 가진다.

### 9.2 Action status persistence vocabulary

Action row는 current Domain contract가 사용하는 상태 식별자를 영속할 수 있어야 하며 optimistic version과 immutable execution/verification evidence를 보존한다. exact allowed transition graph·terminal classification·effect별 FAILED semantics는 Domain State Transition Contract를 참조한다.

```text
PROPOSED | MODIFIED | APPROVED | EXPIRED | EXECUTING | EXECUTED | UNKNOWN_RESULT | FAILED |
VERIFIED | MISMATCH | REJECTED | BLOCKED | CANCELLED | DEPENDENCY_BLOCKED
```

Repository는 Application/Domain command의 validated result만 조건부 UPDATE로 반영하며 임의 SQL state setter를 제공하지 않는다.

### 9.3 취소 상태 계약

이 절은 **취소의 persistence projection만** 소유한다. `RequestCancel`·`CancelPendingAction`·`FinalizeCancel`·Recovery CANCEL의 source state/guard/transition은 Domain State Transition Contract가 유일한 lifecycle authority다.

- APPLIED `RequestCancel` Command Receipt는 restart 후에도 `cancel_intent_active`를 재구성할 수 있는 durable source다. 별도 checkpoint-only flag를 authority로 두지 않는다.
- 취소 정리 과정에서 State Contract가 요구하는 pending Action terminalization, ACTIVE Approval revoke, Plan/Run terminal snapshot은 각각의 owning command transaction에서 원자적으로 보존되어야 한다.
- 이미 확정된 execution/verification 사실은 취소 때문에 재작성하지 않으며, 성공한 external effect를 DB 상태 변경으로 rollback한 것처럼 표현하지 않는다.
- exact 허용 상태·우선순위·in-flight 처리 순서는 이 문서에서 반복하지 않고 State Contract를 참조한다.

### 9.4 Verification MISMATCH Recovery 계약

이 절은 **Verification/Recovery persistence projection**만 소유한다. `StoreVerification`, `RequireRecovery`, `ResolveRecovery`의 lifecycle legality와 disposition 의미는 Domain State Transition Contract가 소유한다.

- Verification은 append-only evidence로 남고, 확정된 `MISMATCH` Action/Verification fact는 immutable하다.
- Run은 Action status를 보고 암묵 재계산하지 않고 owning lifecycle command의 결과만 영속한다.
- Recovery 선택이 새 Plan revision 또는 terminal snapshot을 요구하면 기존 MISMATCH/Approval/Attempt/Verification fact를 덮어쓰지 않고 새 durable fact를 추가한다.
- cancel intent와 Recovery가 결합될 때 어떤 disposition이 허용되는지는 State Contract를 그대로 소비하며 이 절에서 별도 matrix를 유지하지 않는다.

### 9.4-A RecoveryContext durable persistence

`RequireRecovery`가 적용되면 04는 State Transition Contract의 `RecoveryContextV1` logical fact를 restart-safe하게 저장한다. 최소 durable 의미는 `reason`, `scope`, optional `action_id/execution_attempt_id/verification_id`, `pre_recovery_status`, optional registered resume target, reason-specific target/reference fingerprint, observed external/verification/contract/checkpoint fingerprint, `last_recheck_input_hash`다.

정확한 physical realization은 Run column 집합, owner-local recovery record, JSON snapshot 중 하나를 선택할 수 있는 04 implementation choice지만 **Checkpoint-only 또는 process-memory-only 저장은 금지**한다. `ResolveRecovery` handler는 이 durable context version과 current state를 읽어 reason/disposition legality와 `NO_PROGRESS`를 판정한다.

Terminal Recovery persistence는 lifecycle owner의 coupled mutation을 그대로 원자화한다.

- `ACCEPT_PARTIAL`: pending Action `CANCELLED`, ACTIVE Approval `REVOKED`, current Plan `COMPLETED`, Run `COMPLETED`, durable result `PARTIAL`.
- `CANCEL`: pending Action `CANCELLED`, ACTIVE Approval `REVOKED`, current Plan `CANCELLED`, Run `CANCELLED`; 외부 mutation이 이미 관측되었으면 result `PARTIAL`, 없으면 `CANCELLED`.
- `FAIL`: unresolved external-delivery uncertainty가 없어야 하며 pending Action `BLOCKED`, ACTIVE Approval `REVOKED`, current Plan `CANCELLED`, Run `FAILED`, result `FAILED`.

기존 `VERIFIED | MISMATCH | FAILED | REJECTED | BLOCKED | CANCELLED | DEPENDENCY_BLOCKED` facts는 위 terminal cleanup에서 다른 결과로 재작성하지 않는다.

## 10. Transaction 경계

### 10.0 Domain 상태 변경 Command의 공통 Receipt 원자성

아래 §10.1~§10.6의 Transaction은 모두 이 공통 prefix/suffix를 상속한다. 특정 절의 축약 그림에 Receipt가 생략되어 있어도 구현에서 생략할 수 없다.

```
BEGIN IMMEDIATE
→ 서버가 Canonical Request Hash 계산
→ command_id Receipt 조회·판정
   - 같은 command_id + 같은 hash: 저장된 기존 APPLIED/REJECTED Command Result 반환, Domain mutation 추가 0
   - 같은 command_id + 다른 hash: 기존 Receipt 불변 + CONFLICT, Domain mutation 0; 필요한 hash-mismatch Audit만 append
   - 신규 command_id: RECEIVED 예약
→ 기존 mutable Aggregate를 갱신하는 Command면 expected_version·허용 source state Guard 판정
   - Guard 통과: Domain mutation / child mutation → 필요한 Audit Event INSERT → Receipt APPLIED + Command Result 저장
   - Guard/State/Version 거절: Domain mutation 0 → 필요한 rejection Audit → Receipt REJECTED + deterministic rejection Result 저장
→ 최종 Receipt가 APPLIED | REJECTED인지 확인
→ COMMIT
```

- Receipt 판정은 Approval revoke, Plan cancel, Action mutation 같은 child mutation보다 먼저 수행한다.
- Receipt·Domain mutation·Audit는 하나의 Transaction으로 commit 또는 rollback한다.
- Repository transaction abstraction/path authority는 16의 `ports/persistence/unit_of_work.py → UnitOfWork`와 SQLite `adapters/persistence/sqlite/unit_of_work.py → SqliteUnitOfWork`가 소유한다. 04는 atomicity invariant만 소유한다.
- Browser가 제공한 `request_hash`, `approval_id`, `idempotency_key`, `source_snapshot`, actor metadata는 영속 권위로 신뢰하지 않는다. Canonical Request Hash와 권위 값은 서버가 현재 Domain 사실에서 계산·resolve한다.
- `applied=false` 또는 State/Version/Receipt conflict이면 외부 MCP Write를 호출하지 않는다.


### 10.0-A Domain lifecycle + handoff atomicity

Continuation-required external control handler는 owning lifecycle mutation을 적용하는 같은 `SqliteUnitOfWork` 안에서 `WorkflowHandoffRepository.stage_pending(...)`까지 완료한 뒤 commit한다. `run.schedule_run_execution`은 이 transaction **밖에서, commit 성공 후** `handoff_id`만 받아 submit한다. 따라서 외부 Connector/LLM I/O를 SQLite transaction 안에 넣지 않으면서도 `commit succeeded / schedule lost` 상태는 durable outbox로 복구한다.

`WorkflowExecutionPort.submit` 결과가 `ALREADY_RUNNING | SHUTTING_DOWN`이어도 Domain transaction을 되돌리지 않고 handoff를 redrive 가능한 상태로 유지한다. `BINDING_MISMATCH`는 handoff를 `BLOCKED_BINDING`으로 만들고 Recovery reconciliation을 요구한다. post-commit path에서 `NOT_COMMITTED`가 반환되면 architecture invariant violation이며 handoff는 `PENDING`으로 보존해 startup reconciliation이 재판정한다.

### 10.1 Run 시작

```
BEGIN IMMEDIATE
→ §10.0 Receipt adjudication
→ Open Run 존재 확인
→ Run INSERT
→ User Message INSERT
→ WorkflowBinding INSERT
→ START WorkflowHandoff(PENDING) INSERT
→ Conversation updated_at 갱신
→ Audit INSERT
→ APPLIED Command Receipt + Command Result 저장
→ COMMIT
```

### 10.2 Plan Aggregate 저장

```
BEGIN IMMEDIATE
→ §10.0 Receipt + Run expected_version adjudication
→ Plan INSERT
→ Action Batch INSERT
→ Dependency Batch INSERT
→ ResourceRef·Evidence Batch INSERT
→ ActionEvidence Batch INSERT
→ Plan WAITING_APPROVAL + Run WAITING_APPROVAL
→ Audit INSERT
→ APPLIED Command Receipt + Command Result 저장
→ COMMIT
```

한 Row마다 Commit하지 않는다.

### 10.3 승인

```
BEGIN IMMEDIATE
→ §10.0 Receipt adjudication
→ Action status·version·arguments_hash 확인
→ Plan review gate PASSED + Source/Policy/Tool Schema 최신 Snapshot 확인
→ 기존 ACTIVE Approval 만료·취소
→ Approval INSERT
→ Action APPROVED + version 증가
→ Audit INSERT
→ APPLIED Command Receipt + Command Result 저장
→ COMMIT
```

### 10.4 실행권 Claim

```
BEGIN IMMEDIATE
→ §10.0 Receipt adjudication
→ durable cancel intent 없음 + Action APPROVED·version 조건부 UPDATE
→ ACTIVE Approval을 CONSUMED로 UPDATE
→ ExecutionAttempt CLAIMED INSERT
→ Audit INSERT
→ APPLIED Command Receipt + Command Result 저장
→ COMMIT
```

`ClaimExecution` COMMIT은 실행권을 획득한 사실만 확정하며 외부 Write dispatch authority가 아니다. Claim commit 이전 Provider/Connector Write는 0건이어야 한다.

Claim commit 뒤 Application은 승인 Snapshot과 final server dispatch arguments로 `ClaimContextV2`를 구성·검증한 다음 **별도 `BeginExecutionAttempt` Command/UoW**를 적용한다.

```text
ClaimExecution COMMIT
→ build ClaimContextV2 (DB Transaction 없음)
→ BEGIN IMMEDIATE
→ §10.0 BeginExecutionAttempt Receipt adjudication
→ current ExecutionAttempt CLAIMED + committed Approval/Claim binding + cancel intent 없음 확인
→ ExecutionAttempt CLAIMED → EXECUTING
→ EXECUTION_DISPATCH_STARTED Audit INSERT
→ APPLIED Command Receipt + Command Result 저장
→ COMMIT
```

**`BeginExecutionAttempt` COMMIT이 `applied=true`인 뒤에만** Connector MCP Write를 호출할 수 있다. 실패/충돌/취소 intent 감지 시 외부 Write는 0건이며 `current_status + next_allowed_commands`로 재조정한다.

### 10.5 외부 Write와 결과

```
BeginExecutionAttempt COMMIT(applied=true)
→ Connector MCP Write Tool 호출 → Connector MCP Server 내부 Provider Write
→ DB Transaction 없음
BEGIN IMMEDIATE
→ §10.0 Receipt adjudication
→ Result ResourceRef INSERT (성공/복구 결과가 Resource identity를 제공할 때)
→ Attempt SUCCEEDED | UNKNOWN_RESULT | FAILED
→ Action EXECUTED | UNKNOWN_RESULT | FAILED
→ delivery_certainty와 결과 근거 저장
→ Audit INSERT
→ APPLIED Command Receipt + Command Result 저장
→ COMMIT
```

P0 첫 Connector는 Google Workspace지만 Domain/Application이 Google Provider API를 직접 호출한다는 의미가 아니다.

### 10.6 GET Verification

```
Connector MCP Verification Read → Connector MCP Server 내부 Provider Adapter
→ DB Transaction 없음
BEGIN IMMEDIATE
→ §10.0 Receipt adjudication
→ Verification append-only INSERT
→ Action VERIFIED 또는 MISMATCH
→ Audit INSERT
→ APPLIED Command Receipt + Command Result 저장
→ COMMIT
```

Action Verification 결과만으로 Run `status`를 암묵 재계산해 덮어쓰지 않는다. 첫 Write verification 진입은 `BeginVerification`, MISMATCH/불명 결과는 `RequireRecovery`, 정상 완료는 `CompleteWriteRun`, 취소 완료는 `FinalizeCancel`/`ResolveRecovery(CANCEL)` 같은 명시적 Run Domain Command가 전이시킨다.

`action_dependencies`에는 별도 dependency result/status를 저장하지 않는다. Verification COMMIT 뒤 다음 Action의 readiness는 **predecessor Action의 durable `VERIFIED` 상태를 read-only로 평가**한다. `StoreVerification`이 dependency row를 갱신하거나 새 dependency lifecycle/status authority를 만들지 않는다.

## 11. 동시성·Lock

### 11.1 적용

| 대상 | 전략 |
| --- | --- |
| Run | version 낙관적 Lock + Open Run Partial UNIQUE |
| Action | version 낙관적 Lock + changed_rows = 1 |
| ExecutionAttempt | version 낙관적 Lock + Active Attempt Partial UNIQUE |
| CommandReceipt | `command_id` UNIQUE + server canonical `request_hash` comparison + APPLIED/REJECTED stored-result replay |
| Plan | Revision Append |
| Approval | 승인 이력 Insert + ACTIVE 하나 Partial UNIQUE |
| Verification·Audit | Append-only |
| Migration·Restore·Purge | 짧은 전용 BEGIN IMMEDIATE |

### 11.2 사용하지 않음

- Redis·분산 Lock
- 장시간 비관적 Row Lock
- Connector MCP/Provider 외부 호출 중 SQLite Write Lock
- Python Lock만으로 정합성 보장

Process-local write serialization은 같은 Process의 쓰기 순서를 보조할 수 있지만 최종 정합성은 DB `UNIQUE`·`CHECK`·Foreign Key·Partial UNIQUE·executable Trigger/DB guard·version 조건부 UPDATE가 보장한다. Application semantic validator나 Process-local lock 하나만으로 cross-aggregate integrity를 대체하지 않는다.

## 12. 멱등성

### 12.1 Idempotency Key

Approval 생성 시 다음 Canonical 값으로 SHA-256을 생성한다.

```
account_id
approval_id
action_id
action_version
tool_name
canonical_arguments_hash
policy_version
tool_schema_version
```

`idempotency_key`는 **한 Approval 실행 문맥**에 고정된다. `FAILED → MODIFIED → 새 Approval` 재시도에서는 기존 Approval과 기존 Key를 재사용하지 않으며 새 Approval로 새 Key를 생성한다. 같은 Approval 안에서 `UNKNOWN_RESULT`를 해소하기 위한 조회/Verification은 새 Write가 아니므로 새 Idempotency Key를 만들지 않는다.

### 12.2 Recovery Fingerprint

Connector Provider가 공통 Idempotency Header를 제공한다고 가정하지 않는다. 응답 유실·`UNKNOWN_RESULT`에서는 Approval에 저장된 `recovery_fingerprint`로 **같은 Connector Effect 범위**의 기존 결과 후보만 찾는다. 서로 다른 Connector의 Resource/Effect가 같은 fingerprint 검색 공간에 섞이면 안 된다.

```
connector_id
Conversation owner account identity  # P0: Google account_id
Tool 유형 / Effect
대상 Resource identity(resource_type + resource_id), 존재하는 경우
정규화된 제목·핵심 시간/기한·수신자 집합 등 Effect별 business fingerprint
canonical_arguments_hash
```

CREATE처럼 사전 `resource_id`가 없는 Effect는 해당 항목을 생략하고 Effect별 business fingerprint로 후보를 좁힌다. 두 번째 Connector에서 별도 connector-account persistence가 필요해지면 기존 Google-specific account binding을 일반화하는 **새 forward migration**을 추가하며 적용 Migration을 소급 수정하지 않는다.

### 12.3 보장 범위

- REST Retry·브라우저 새로고침·중복 클릭·앱 재시작의 동일 Action 중복 실행 차단
- UNKNOWN_RESULT 확인 전 재실행 차단
- 서로 다른 Action으로 생성된 의미상 중복은 별도의 중복·충돌 Validator가 처리

## 13. DB Fetch Size·Batch·Disk I/O

04가 소유하는 것은 SQLite/Domain persistence I/O 단위다. Connector/API page size와 Agent detail-fetch budget은 05 Retrieval·07 Interface가 소유하며 이 문서에서 별도 숫자 authority를 만들지 않는다.

| 항목 | 제어 대상 |
| --- | --- |
| Cursor Fetch Size | SELECT 결과를 Python으로 전달하는 Row 묶음 |
| Write Batch Size | 한 Transaction에서 저장하는 Row 수 |
| SQLite Page Write | WAL·Transaction·Commit·DB Page와 Cache의 영향 |

Disk I/O는 Row별 Commit을 금지하고 Application UoW 단위 Batch Write로 줄인다.

P0 persistence defaults:

| 경로 | 초기값 |
| --- | --- |
| Conversation·Message Page | configured bounded page size |
| 내부 ID Batch Query | 최대 50개 |
| Plan·Action·Evidence Batch Write | 최대 50 Row |
| Trace·Audit Export Fetch | 200 Row |

## 14. Local DB Pagination

Conversation·Message·Run·Audit은 `(timestamp_ms, id)` Keyset Cursor를 사용한다.

```sql
SELECT id, title, updated_at_ms
FROM conversations
WHERE account_id = :account_id
  AND (
       updated_at_ms < :cursor_time
       OR (updated_at_ms = :cursor_time AND id < :cursor_id)
  )
ORDER BY updated_at_ms DESC, id DESC
LIMIT :limit;
```

Cursor 외부 표현은 Version·Time·ID JSON을 URL-safe Base64로 인코딩하며 DB에 저장하지 않는다. Connector continuation/Provider page token과 이 Local DB cursor는 서로 다른 authority다. Connector pagination과 Retrieval query progression은 05/07을 참조한다.

## 15. N+1 방지

### 15.1 DB

SQL JOIN, CTE, `WHERE id IN (...)`, 고정 개수 Batch Query를 사용하며 ORM-specific fetch 전략을 canonical contract로 만들지 않는다.

| Plan 화면 조회 | 최대 SQL 수 |
| --- | --- |
| Plan + Actions | 1 |
| Dependencies | 1 |
| Evidence + ActionEvidence | 1 |
| Approval + 최신 Attempt | 1 |
| Verification | 1 |
| 전체 Plan Bundle | 최대 5 |

Action×Evidence×Attempt×Verification을 하나의 거대한 Join으로 합쳐 Row 곱집합을 만들지 않는다.

### 15.2 Connector Provider read N+1 boundary

```text
Sidebar 목록 batch
→ Metadata 표시
→ 항목별 상세 자동 조회 금지
→ 클릭·선택한 Resource만 상세 조회
```

복수 선택 상세 조회는 **Application-level bounded batch responsibility**로 처리한다. Provider가 개별 상세 Endpoint만 제공해 concrete Adapter 내부 HTTP 호출이 여러 번 필요하더라도 중복 제거, 제한된 동시성, 메모리 재사용, 후보 수 상한을 적용한다. 구체 Port method와 MCP Tool ID는 `07 Interface`, repository path/file/symbol은 `16 Repository Architecture`가 소유한다.

## 16. Persistence repository capability boundary

04가 요구하는 Repository 책임은 method 이름이 아니라 다음 persistence capability다. 구체 operation/path/file/symbol은 16이 단일 권위로 매핑한다.

- Conversation/Message keyset page read
- Run snapshot read
- Plan aggregate bundle read/write
- Recovery candidate bounded read
- command receipt + expected-version conditional mutation
- Approval/Claim/ExecutionAttempt/Verification atomic persistence
- Evidence/ResourceRef bounded persistence
- retention purge UoW

Connector read/write Port는 07 Interface concern이며 이 문서가 별도 `MCP * Port` 또는 method name을 정의하지 않는다.

## 17. Index 원칙

- 실제 WHERE·JOIN·ORDER BY와 Query Plan을 기준으로 생성한다.
- Conversation·Message·Run·Audit는 Keyset 정렬 복합 Index를 가진다.
- Open Run, ACTIVE Approval, Active Attempt는 Partial UNIQUE Index를 가진다.
- Recovery 상태는 Partial Index로 빠르게 조회한다.
- Dependency 역방향, Evidence Origin, Join Table 역방향 조회 Index를 둔다.
- 사용하지 않는 Column과 Index를 미리 대량 생성하지 않는다.

## 18. SQLite Runtime Config

```
foreign_keys = ON
journal_mode = WAL
synchronous = FULL
busy_timeout = 5000ms
```

- 모든 Connection은 하나의 초기화 함수를 사용한다.
- `SQLITE_BUSY`는 5초 대기 후 상위 Use Case에서 최대 1회만 재시도한다.
- 승인·실행권 Claim Commit 유실은 중복 Connector Write 위험이 있으므로 P0 기본은 FULL이다.
- 실제 성능 측정 없이 NORMAL로 낮추지 않는다.

## 19. Migration·Backup·Restore

### 19.1 Migration

1. 앱 Schema Version과 DB Version 비교
2. Migration 필요 시 SQLite Backup API로 사전 Backup
3. Migration별 Transaction 실행
4. `schema_migrations`에 Version·Checksum 기록
5. `PRAGMA quick_check`
6. `PRAGMA foreign_key_check`
7. 실패 시 Safe Mode

SQLAlchemy·Alembic은 P0 고정 기술로 강제하지 않는다. 명시적 SQL Migration과 Checksum을 기준으로 하며 Adapter 선택은 구현 단계에서 결정한다.

**Command Receipt migration realization requirement:** 모든 **Domain Aggregate 상태 변경 lifecycle Command**는 durable `command_receipts`를 요구한다. non-Domain operational command는 07의 별도 replay authority를 사용한다. 구현 시 migration set에서 relation과 필수 uniqueness/request-hash/result persistence가 존재하는지 확인하고, 없으면 다음 사용 가능한 numeric 순번의 **새 forward migration**을 추가한다. 적용된 `0001~0008`을 소급 수정하지 않는다. 의미 권위는 이 문서와 State Transition Contract이며 migration 번호는 implementation history다.

### 19.2 Backup

- Migration 전 자동 Backup
- 사용자 수동 Backup
- Backup SHA-256·App Version·Schema Version을 DB 외부 Manifest에 기록
- CI Restore Test
- P0에는 백그라운드 정기 Scheduler를 추가하지 않는다.

### 19.3 Restore

1. Domain·Connector Write 차단
2. 현재 DB를 별도 이름으로 보존
3. 사용자가 Backup 선택
4. 새 파일로 복원
5. Schema Version·quick_check·foreign_key_check
6. 통과 시 정상 모드

## 20. 보존과 삭제

01-B의 P0 retention matrix를 persistence에 다음처럼 exact realization한다. `retention_days` 기본은 30, P0 유효 범위는 **1..30**이며 이 절이 별도 정책 상한을 만들지 않는다.

| 대상 | cutoff 기준 | `retention_days` | 보호/삭제 규칙 |
| --- | --- | --- | --- |
| Terminal Run + Plan·Action·Approval·ExecutionAttempt·Verification·ResourceRef·Evidence·Trace | owning Run `finished_at_ms` | 적용 | Run이 terminal이고 active Recovery/Reauth/Verification가 없을 때만 child-first purge |
| LangGraph Checkpoint | owning terminal Run cutoff | owning Run과 동일 | resume/recovery 가능성이 남아 있으면 Run보다 먼저 삭제 금지 |
| Command Receipt | owning Aggregate retention/replay window | 직접 적용하지 않음 | owning Aggregate와 replay 판정이 남아 있는 동안 선행 purge 금지; eligible aggregate purge UoW 안에서 receipt ordering 보장 |
| Message | `created_at_ms` | 적용 | 연결된 retained/open Run의 재구성에 필요한 Message는 보호 |
| Conversation | `updated_at_ms` | 적용 | open Run=0이고 retained Message/Run child=0일 때만 parent 삭제 |
| Audit | Audit timestamp | **고정 90일** | `retention_days` 영향 없음; 업무 원문 없이 최소 식별·상태만 보존 |
| Google Sidebar Cache | UI session | 미적용 | 세션 종료 시 폐기 |
| Secret | 09/10 credential lifecycle | 미적용 | Domain/SQLite에 저장하지 않음 |

`RetentionRepository.purge_batch(cutoffs, batch_limit)`의 `cutoffs`는 Application `PurgeRetentionHandler`가 persisted `retention_days`와 위 category rules로 계산한 typed cutoff set만 받는다. 구현자가 임의 target list를 만들지 않는다. Purge 순서는 **Run child/Checkpoint/Receipt eligibility 확정 → Run → eligible Message → child가 0인 Conversation**이며 Foreign Key/replay invariant를 깨지 않는다. nonterminal Run과 그 owning Conversation, unresolved Recovery/Reauth, current replay에 필요한 Receipt는 항상 보호한다.

모든 Table에 `deleted_at`을 일괄 추가하지 않는다. 사용자 명시 Conversation 삭제는 같은 child-first 규칙으로 실제 삭제하고 Audit에는 업무 원문 없이 최소 ID만 남긴다.

## 21. P0 보류

- SQLCipher·Column Encryption
- Domain DB·Checkpoint DB 물리 분리
- Vector Index·Embedding Cache
- Local Full-text Search
- Remote Sync·Multi-user Tenant
- Distributed Lock
- Read Replica
- 대규모 Archive·자동 Vacuum 고도화


## 22. Persistence contract handoff

이 문서에서 정의한 persistent fact·invariant를 구현으로 넘길 때 concern ownership을 다음처럼 유지한다.

- `04 Domain·DB` — persistent fact, aggregate invariant, transaction/consistency semantics를 소유한다.
- `Domain State Transition Contract` — lifecycle transition·guard·command semantics를 소유한다.
- `10 Infrastructure` — migration 실행·startup ordering·operational DB configuration을 소유한다.
- `16 Repository Architecture` — Repository/Adapter의 path·file·symbol·callable placement를 매핑한다.
- `12 Test`와 `State Transition Test Matrix` — 위 계약의 구현 준수를 검증하며 새 persistence/lifecycle 의미를 만들지 않는다.

SQL migration은 위 semantic authority를 구현하는 downstream artifact이며 별도 설계 authority가 아니다.


## 23. Current migration · persistence boundary

이 절은 current persistence authority와 migration implementation boundary만 정의한다.

- DB Schema v1.9의 설계 수준 invariant는 이 문서의 current sections가 소유한다.
- required `CHECK/UNIQUE/FK/partial UNIQUE/trigger/conditional-update` 의미는 이 문서의 current invariant contract가 소유한다. SQL syntax와 migration ordering은 implementation realization이며 10/12/16이 검증한다.
- 적용된 migration이 아래 invariant를 구현하지 않으면 applied migration을 다시 쓰지 않고 `FORWARD_NUMERIC_MIGRATION_REQUIRED`로 처리한다.
- Domain DB와 LangGraph Checkpointer는 같은 SQLite 파일을 공유할 수 있지만 logical ownership은 분리한다. Domain Repository가 Checkpoint row를 aggregate persistence로 노출하지 않는다.
- Raw Provider continuation/token, Secret, Prompt scratch, whole Sidebar cache는 Domain DB에 저장하지 않는다.
- Reauth/Recovery resume 위치는 Workflow/Checkpoint concern의 등록된 target을 따르며 이 문서가 node/edge authority를 만들지 않는다.


## 24. Domain lifecycle persistence projection — derivative only

### 24.1 Authority boundary

이 절은 lifecycle command를 새로 정의하지 않는다. **Command 이름·허용 source state·semantic guard·target state·next allowed command는 Domain State Transition Contract가 소유한다.** Lifecycle closure는 이 snapshot에 포함된 `Domain State Transition Contract`와 `State Transition Test Matrix`를 함께 따른다. 이 문서의 persistence projection은 lifecycle semantics를 중복 정의하지 않는다.

### 24.2 Persistence responsibilities owned by 04

Lifecycle owner가 허용한 command를 Application이 호출했을 때 04가 소유하는 것은 다음 persistence realization이다.

- Aggregate row와 immutable snapshot/receipt의 저장 위치와 관계
- `expected_version` 조건부 UPDATE와 영향 Row 1개 확인
- mutable row version 증가와 stale write conflict 판정
- Command Receipt의 `command_id + canonical request hash` replay/conflict persistence
- Action 변경/재시도/expired-refresh에 따른 Approval revocation과 Review freshness reset의 durable realization
- Claim/ExecutionAttempt/Verification의 atomic write-set과 외부 I/O 전후 Transaction 분리
- Audit/Trace에 기록할 durable fact의 persistence projection
- DB-level final defense가 필요한 invariant의 required enforcement class

이 절에서 lifecycle state name을 예로 들더라도 **허용 전이 표로 읽지 않는다.** source-state/guard/next-state 전체 표는 중복 authority를 만들기 때문에 제거한다.

### 24.3 Review freshness persistence

Action의 arguments/source/policy/tool-schema binding이 바뀌는 modify/retry/expired-refresh persistence는 기존 Approval을 재활성화하지 않고 Review freshness를 `REQUIRED`로 reset해야 한다. 이전 Review PASS는 current Plan/Action revision에 자동 승계되지 않는다.

### 24.3-A Terminal Assistant Message durable effect

`CompleteAnswerOnlyRun`, legacy `CompleteReadOnlyRun`, `CompleteWriteRun`, `BlockRun`, `FinalizeCancel`, terminal `ResolveRecovery(ACCEPT_PARTIAL|CANCEL|FAIL)`의 Application handler는 terminal Domain transition을 commit할 때 **정확히 하나의 final ASSISTANT Message**를 같은 UoW에 stage한다. Message는 lifecycle semantics가 아니라 terminal command의 required durable effect다. Command replay가 duplicate Message를 만들지 않도록 **applied terminal lifecycle receipt + run identity에 대해 final ASSISTANT Message가 하나만 존재해야 한다.** 이를 별도 `final`/`terminal_run_version` column으로 구현할지 receipt-linked uniqueness로 구현할지는 04의 implementation choice이며 다른 문서가 column 이름을 새 authority로 만들지 않는다.

`terminal_result_kind = SUCCESS | PARTIAL | BLOCKED | FAILED | CANCELLED`는 restart 뒤 Run Snapshot에서 복원 가능한 durable terminal projection이어야 한다. Run column 또는 terminal-result record 중 exact physical representation은 04 implementation choice지만 Trace/SSE-only 값이어서는 안 된다.

`TerminalAssistantMessageInputV1`의 content/result kind는 UoW 시작 전에 완성·검증되어야 하며 UoW 중 LLM/Connector 호출은 금지한다. required Audit와 Message stage 중 하나라도 실패하면 Receipt/Domain mutation까지 rollback한다. Diagnostic Trace와 SSE Projection은 commit 이후 별도 concern에서 처리하며 실패해도 committed Domain truth를 rollback하지 않는다.

fresh canonical Review 결과를 durable review gate에 반영하는 writer는 **Application persistence operation `plan.record_review_result`**가 소유한다. 이는 Domain lifecycle command를 새로 만드는 것이 아니라, 06 Review가 결정적으로 검증한 `PlanReviewResultV2`를 현재 Plan/Action revision에 조건부 기록하는 persistence boundary다.

`RecordReviewResultCommandV1`은 최소 `command_id`, `plan_id`, `expected_plan_version`, `review_artifact_id`, `review_version`, `disposition`, `based_on_action_versions`를 포함한다. Repository UoW는 현재 Plan version과 각 bound Action version이 모두 일치할 때만 결과를 기록한다. `disposition=PASS`인 current result만 review gate를 `PASSED`로 열 수 있고, `REVISE | RETRIEVE_MORE | ROUTE_RECONSIDERATION | CONFIRM | BLOCK`은 모두 durable current disposition으로 저장되지만 Approval 가능 gate를 열지 않는다. Review 도중 Modify/retry/expired-refresh로 Plan/Action revision이 바뀌면 조건부 write는 conflict로 실패하며 stale PASS는 durable authority가 되지 않는다.

이 operation은 Approval 생성, Action status 전이, lifecycle guard를 직접 수행하지 않는다. `ApproveAction`은 이 durable current PASS fact를 읽어 기존 Domain guard를 집행한다. Workflow/FastAPI가 DB를 직접 수정하거나 SQL trigger가 Review 의미를 발명하는 경로는 계속 금지한다.

### 24.4 Command Receipt / concurrency realization

State-changing Local API command는 Domain mutation과 Receipt adjudication을 같은 short SQLite transaction에서 처리한다.

```text
BEGIN IMMEDIATE
→ command_id lookup
→ same id + same hash: prior result replay
→ same id + different hash: conflict, old receipt immutable
→ expected_version / invariant validation
→ Domain mutation + durable Audit/Receipt
→ COMMIT
```

외부 Connector/LLM I/O를 이 write transaction 안에서 기다리지 않는다.

### 24.5 Required persistent enforcement contract

아래는 구현자가 반드시 SQLite final defense로 실현해야 하는 **설계 invariant**다. SQL 문법 자체는 구현 세부지만 enforcement class와 실패 의미는 선택사항이 아니다.

| Invariant ID | Required invariant | Required DB final defense | Failure meaning |
| --- | --- | --- | --- |
| `DBI-001` | Conversation당 Open Run 최대 1개 | partial `UNIQUE` | concurrent StartRun 중 하나만 commit |
| `DBI-002` | Action당 `ACTIVE` Approval 최대 1개 | partial `UNIQUE` | stale/duplicate approval insert reject |
| `DBI-003` | Approval당 active ExecutionAttempt 최대 1개 | partial `UNIQUE` | duplicate Claim/Attempt reject |
| `DBI-004` | `command_id`는 durable unique이며 request hash/result를 immutable replay | `UNIQUE` + same-transaction receipt adjudication | same id/different hash conflict; mutation 0 |
| `DBI-005` | Plan/Action/Approval/Attempt/Verification/Evidence/ResourceRef는 owning aggregate FK를 벗어나지 않음 | `FK` + required ownership trigger where a single FK cannot express cross-aggregate equality | cross-run/cross-plan child write reject |
| `DBI-006` | Action dependency self-edge 금지, `(plan_id, position)` unique | `CHECK` + `UNIQUE` | invalid DAG edge/position reject; full cycle detection remains deterministic Application validator |
| `DBI-007` | current Plan/Action revision과 bind되지 않은 Review PASS는 approval gate를 열 수 없음 | versioned conditional write + durable review-gate fields; DB constraint/trigger prevents impossible gate values | stale Review result conflict |
| `DBI-008` | ResourceRef canonical identity = `(run_id, connector_id, resource_type, resource_id)` | connector-aware `UNIQUE` | duplicate/cross-connector identity ambiguity reject |
| `DBI-009` | P0 persisted Action/ResourceRef connector identity는 registered `connector_id`를 가짐 | `NOT NULL/CHECK/FK` as schema allows | ownerless connector row reject |
| `DBI-010` | Claim commit은 Approval consume + Attempt CLAIMED + Action EXECUTING을 한 Transaction으로 완료 | conditional UPDATE + FK/UNIQUE + transaction | partial claim state rollback |
| `DBI-011` | `UNKNOWN_RESULT` unresolved 동안 새 Attempt/Write authority 생성 금지 | Domain guard + conditional DB write/trigger final defense | blind resend/new attempt reject |
| `DBI-012` | required Audit/Receipt와 Domain mutation은 하나의 short transaction | transaction/UoW; external I/O excluded | half-commit rollback |
| `DBI-013` | `SUPERSEDED` Plan은 child execution authority를 가질 수 없음: ACTIVE Approval 0, new child lifecycle mutation/Claim 0 | supersession UoW의 Approval revoke-before-Plan-update + parent-Plan conditional write/trigger final defense | stale old-Plan approval/claim reject; Attempt/Write 0 |

Migration implementation은 위 ID를 test trace로 연결한다. 이미 적용된 migration이 부족하면 다음 numeric forward migration으로 보강하고, 과거 migration bytes는 변경하지 않는다. 10은 discovery/order/checksum, 16은 placement/naming, 12는 실제 enforcement regression을 소유한다.

### 24.6 Downstream projection rule

06 Workflow, 07 Interface, 08 Sequence, 12 Test는 04의 persistence fact를 참조할 수 있지만 이 절에서 lifecycle semantic authority를 역으로 추출하지 않는다. Lifecycle mapping은 포함된 State Transition Contract/Test Matrix와 대조하며 이 문서가 command/state/guard를 독립 재정의하지 않는다.


## 25. Legacy lifecycle persistence compatibility projection

이 절은 **legacy/compatibility lifecycle command의 존재를 새로 정의하지 않는다.** 허용 source state·guard·target state·next command의 유일한 authority는 `Domain State Transition Contract`다. 04는 그 command가 실제로 존재할 경우 필요한 persistence realization만 기록한다.

- expired/retry/legacy READ 관련 command가 current State Contract에서 유효하면 Repository UoW는 `expected_version`, immutable prior Approval/Receipt, review freshness reset, append-only Audit를 보존한다.
- legacy READ compatibility가 유지되는 동안 READ Action은 Approval/ExecutionAttempt/Verification Row를 만들지 않는 persistence invariant를 지킨다.
- command 이름·source state·transition table을 이 문서에서 복제하지 않는다. lifecycle parity는 포함된 State Contract/Test Matrix로 검증한다.


## 26. Release Graph persistence/application projection

Release Graph의 semantic routing/command authority는 05/06/07 및 Domain State Transition Contract에 있다. 04가 소유하는 것은 다음 persistence 사실뿐이다.

### 26.1 Retrieval persistence boundary

- 일반 Connector Retrieval은 Action Row를 만들지 않는다.
- `ToolRoutePlanV2.input_plan.input_routes`/Query/Read/RAG 의미는 05/06이 소유하며 04는 Run-scoped ResourceRef/Evidence persistence와 bounded cache/reference separation만 소유한다.
- Retrieval raw continuation/Provider query/MCP arguments는 Domain DB에 저장하지 않는다.

### 26.2 Answer-only persistence boundary

- Answer-only completion이 current State Contract에서 허용될 때 Plan/Action 없이 **CommandReceipt + Run terminal mutation + required Audit + ASSISTANT Message**를 하나의 Application UoW로 원자화한다. Diagnostic Trace는 Domain truth가 아니므로 이 transaction에 필수로 묶지 않고 commit 이후 별도 short UoW로 기록할 수 있다.
- Open Write/UNKNOWN_RESULT가 있으면 completion writer는 fail closed한다.

### 26.3 Legacy READ persistence boundary

- legacy/compatibility READ Plan/Action이 State Contract에 존재하는 동안 그 path는 Approval·ExecutionAttempt·Verification Row를 생성하지 않는다.
- `CompleteReadOnlyRun`이 적용되면 current Plan terminal mutation + Run terminal mutation + CommandReceipt + required Audit + final ASSISTANT Message + durable `terminal_result_kind`를 같은 short UoW로 commit한다.
- 새 Release Retrieval은 이 compatibility path를 사용하지 않는다.

### 26.4 Write retry/unknown-result persistence boundary

- Write 실패/retry/UNKNOWN_RESULT의 허용 command/transition은 State Contract가 소유한다.
- 04는 새 retry가 기존 Approval/Attempt/Idempotency identity를 재사용하지 않고, UNKNOWN_RESULT가 해소되기 전 새 Write Attempt를 만들지 않는 persistence invariant만 소유한다.

### 26.5 Multi-Agent state ownership

- 모든 Agent는 하나의 Run·Conversation·`langgraph_thread_id`를 공유하되 Agent별 DB/Approval/Attempt를 만들지 않는다.
- Query candidate·Page Token·RAG candidate·대용량 원문은 05/06 owner-local cache/state에 남고 Domain DB의 두 번째 workflow truth가 되지 않는다.
- 승인·실행·검증·복구 durable fact는 기존 Domain Store가 기준이다.


## 27. Cross-cutting persistence projections

이 절은 앞 절에 흩어진 **추가 durable fact만** 모은다. Effect 의미·lifecycle command·Recovery route 자체는 `01-B`, State Contract, `06/07`의 owner contract를 따른다.

### 27.1 External I/O transaction boundary

Connector/LLM 외부 호출 동안 SQLite Write Transaction을 유지하지 않는다. 호출 전 필요한 authority fact를 짧은 transaction으로 commit하고, 호출 후에는 `expected_version`과 current lifecycle fact를 다시 검사해 결과를 조건부 저장한다. 두 transaction 사이에 authority가 바뀌면 성공을 추정하지 않는다.

### 27.2 Review disposition persistence

`plan.record_review_result`는 current `PlanReviewResultV2` disposition을 동일 값으로 durable 저장한다. current revision의 `PASS`만 review gate를 열 수 있으며, stale Plan/Action revision에 대한 PASS write는 version conflict로 실패한다. Review가 어떤 disposition을 만들고 어디로 route하는지는 `06`이 소유한다.

### 27.3 Per-Run requested mode

`runs.requested_mode = AUTO | LOCAL_GPU | API_LLM`은 StartRun UoW에서 immutable snapshot으로 저장하며 same-Run restart/resume의 durable authority다. process-local runtime mode나 user preference가 기존 Run 값을 덮어쓰지 않는다.

### 27.4 Pre-dispatch claimed-attempt abort

`AbortClaimedExecution` persistence는 current Attempt=`CLAIMED`, Action=`EXECUTING`, matching consumed Approval/Claim, APPLIED BeginExecutionAttempt receipt 없음이라는 owner guard 결과를 받아 Attempt/Action/Audit/Receipt를 한 transaction으로 commit한다. Provider/MCP I/O는 0이다. 정확한 transition semantics는 State Contract가 소유한다.

## 28. 테스트 완료 조건

- Schema를 새 SQLite 파일에 적용할 수 있다.
- `quick_check = ok`, Foreign Key 위반 0건이다.
- Conversation당 Open Run 2개 생성이 차단된다.
- 상태 변경 Command의 `command_receipts`가 앱 재시작 후에도 영속되고, 같은 `command_id + request_hash`는 기존 결과를 replay하며 Domain/Audit 추가 변경이 0건이다.
- 같은 `command_id`에 다른 `request_hash`가 오면 기존 Receipt를 덮어쓰지 않고 conflict로 차단한다.
- Receipt 예약·Domain mutation·필수 Audit·APPLIED 결과 확정 중 하나라도 실패하면 같은 Transaction이 rollback되어 반쪽 적용이 남지 않는다.
- Action당 ACTIVE Approval 2개 생성이 차단된다.
- Approval당 Active Attempt 2개 생성이 차단된다.
- 동일 Action 실행권 Claim 경쟁에서 1개만 성공한다.
- UNKNOWN_RESULT 해결 전 새 Approval·새 Attempt·새 Write가 차단된다.
- Write FAILED retry는 새 Approval·새 Idempotency Key·새 attempt_id를 사용하고 새 Approval의 첫 `attempt_no = 1`이다.
- Write FAILED가 남아 있는 동안 `CompleteWriteRun`과 dependent Action terminalization이 차단된다.
- `delivery_certainty`가 `execution_attempts.response_metadata_json.delivery_certainty`에 보존되고 오류 상세와 혼용되지 않는다.
- Plan Bundle 조회가 정해진 Query Budget을 넘지 않는다.
- Google 목록의 한 visible page를 조회한 뒤 같은 page의 모든 항목에 대한 상세 자동 호출이 발생하지 않는다.
- Migration 실패 시 원본 DB와 Backup이 보존되고 Safe Mode로 전환한다.
