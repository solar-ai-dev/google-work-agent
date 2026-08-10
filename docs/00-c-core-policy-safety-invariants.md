# 00-C. 핵심 정책·안전 불변조건 요약

> **문서 성격:** 설명 문서. 실제 권위는 `01-B Policy`, `04 Domain·DB`, Domain 상태 전이 계약, SQL Constraint, `07 Interface`, `09 Security`가 소유한다.

## 1. 한 문장으로 설명하면

Google Work Agent의 안전 모델은 LLM의 좋은 의도를 신뢰하는 것이 아니라 **권한·상태·인자·실행·검증을 결정적 계약으로 분리해 잘못된 판단이 실제 Google Side Effect로 이어지지 않게 하는 구조**다.

```text
Agent 제안
→ Domain·Policy 허용 판정
→ 사용자 승인
→ Claim Commit
→ ClaimContextV2 검증
→ Google Write
→ 실제 Google 상태 재조회
→ Verification
→ 필요 시 Recovery
```

## 2. 무엇을 누구에게 신뢰하는가

| 구성 | 신뢰하는 것 | 신뢰하지 않는 것 |
|---|---|---|
| LLM·Agent | 언어 해석, Source 전략, 분석, 계획 후보 | 최종 Policy 판정, 승인 대체, 실행 성공 선언 |
| Supervisor | Phase·Typed Result 기반 Routing | Domain 상태 사실, Google Write 결과 추정 |
| Domain Store | 승인·Action·Attempt·Verification 영속 사실 | Google 원본 상태를 단독 추정 |
| Google 재조회 | 실제 외부 Resource 상태 | 우리 Domain 상태 전이 규칙 |
| Checkpoint | Workflow 재개 위치 | 실행 성공의 사실 |
| SSE/UI | 사용자 Projection | 승인·실행 권위 |

한 구성요소가 모든 사실을 단독으로 선언하지 못하게 하는 것이 핵심이다.

## 3. Agent가 할 수 있는 것과 할 수 없는 것

Agent가 할 수 있는 일:

- 요청 이해
- Source·Budget 전략 제안
- Evidence 선택
- 업무 분석
- Answer / Action Plan 제안
- Plan Review

Agent가 할 수 없는 일:

- Policy 최종 허용 판정
- Approval 생성·우회
- Google Write 직접 실행
- 승인된 Tool·Arguments·Target 변경
- Write 성공 최종 확정
- `UNKNOWN_RESULT`에서 새 Write 생성
- Domain 상태 직접 변경

Agent 간 직접 호출·Peer-to-Peer A2A·Agent별 장기 Memory도 P0 기준선이 아니다.

## 4. READ와 WRITE의 경계

### READ
사용자 요청 범위 안에서 자동 수행할 수 있다. Retrieval Read는 Approval·ExecutionAttempt·Verification Row를 만들지 않는다.

### WRITE
외부 상태를 바꾸는 허용 Effect는 사용자 승인과 결정적 실행 경로를 거친다.

```text
CREATE | UPDATE | SEND | DELETE
```

위험도가 낮아 보인다는 이유로 승인 경로를 생략하지 않는다.

## 5. Approval 불변조건

승인은 단순 버튼 클릭 기록이 아니라 **정확히 어떤 작업을 실행해도 되는지 고정하는 실행 권한 Snapshot**이다.

승인 시 최소 다음을 고정한다.

- Action Version
- Tool / Effect
- Canonical Business Arguments
- `approval_arguments_hash`
- Target Resource
- Source Snapshot
- Policy / Tool Schema Version
- Expiry

규칙:

- 승인 전 Action과 실행 Action이 일치해야 한다.
- 승인 후 LLM이 Tool·Arguments·Target을 다시 생성하지 않는다.
- Resource Version, Arguments, Policy, Tool Schema가 바뀌면 기존 Approval을 그대로 사용하지 않는다.
- 만료·수정·재계획은 계약에 따라 새 Approval을 요구한다.
- 승인 무결성 위반은 사용자 Override로 우회할 수 없다.

## 6. ClaimContextV2 불변조건

Domain의 `ClaimExecution`이 Commit된 뒤 외부 MCP Write 직전에 실행권을 전달한다.

`ClaimContextV2`는 다음을 바인딩한다.

- Claim Version
- Service Instance
- MCP Process Instance
- Action / Approval / ExecutionAttempt
- Tool
- `approval_arguments_hash`
- `execution_arguments_hash`
- TTL
- One-time Nonce
- HMAC-SHA-256 Signature

MCP는 실제 수신 Arguments를 다시 Hash해 `execution_arguments_hash`와 비교한 뒤에만 Google Write를 호출한다.

Claim Token·Session Key는 SQLite·Keyring·환경 변수·CLI·Log·Trace·Audit에 저장하지 않는다.

## 7. 외부 호출과 DB Transaction을 분리한다

```text
DB Snapshot / Claim Transaction
→ COMMIT
→ external MCP / Google call
→ new DB Transaction
→ expected_version / Action / Attempt 재검사
→ 결과 저장
```

금지:

- SQLite Write Transaction을 연 채 Google/MCP/LLM 응답 대기
- Claim Commit 전에 Google Write 호출
- 외부 호출 뒤 과거 Snapshot만 믿고 결과 저장
- Claim Token 재사용
- 외부 호출 후 version/state 재검사 생략

## 8. FAILED와 UNKNOWN_RESULT는 다르다

### FAILED
Write가 수행되지 않았음이 확정된 경우다. `delivery_certainty=NOT_SENT`가 필요하다.

재시도:

```text
FAILED
→ MODIFIED
→ 최신 Source·Policy 재검증
→ 새 Approval
→ 새 Attempt
```

기존 Approval·Idempotency Key를 재사용하지 않고 `FAILED → EXECUTING` 직접 전이를 금지한다.

### UNKNOWN_RESULT
Google에 전달됐을 가능성이 있어 결과를 모르는 상태다.

```text
UNKNOWN_RESULT
→ 기존 결과 조회 / Target GET / Resource Search / Sent Search
→ 기존 Attempt 결과 복구
또는 RECOVERY_REQUIRED
```

금지:

- `UNKNOWN_RESULT → EXECUTING`
- 새 Attempt 생성
- blind resend

Write Adapter는 `NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST`를 보존한다. dispatch 이후 Timeout·5xx·응답 유실은 미전달이 보장되지 않으면 UNKNOWN_RESULT다.

## 9. Verification은 Tool 응답과 별개다

`200 OK`나 LLM의 성공 문장은 최종 성공 근거가 아니다.

| Effect | Verification |
|---|---|
| CREATE | 생성 Resource GET 후 Expected 비교 |
| UPDATE | Target GET 후 변경 필드 비교 |
| SEND | Sent 결과 조회 |
| DELETE | Target 부재 또는 삭제 상태 확인 |

`MISMATCH`는 Action과 Verification 사실을 보존하고 Run을 `RECOVERY_REQUIRED`로 전환한다.

허용 Recovery:

- `ACCEPT_PARTIAL`: 현재 실제 상태를 수용하고 추가 Write 없이 종료
- `CREATE_CORRECTIVE_PLAN`: 실제 상태 기준 새 Plan Revision → 새 승인·Claim·Attempt·Verification

자동 수정·자동 rollback·기존 Approval/Attempt 재사용은 금지한다.

## 10. 허용 Effect와 금지 Action

승인 후 허용되는 대표 Write:

- Gmail Draft 생성·수정
- Gmail 실제 SEND
- Google Task 생성·허용 필드 수정·완료
- Google Task 삭제
- Calendar Event 생성·허용 필드 수정·삭제
- Calendar 참석자 추가·수정

금지:

- Gmail Message·Thread 원문 삭제
- Gmail Label·설정 변경
- 반복 Event 전체 일괄 수정
- 승인·Policy·Verification 우회 DB/System 직접 변경

금지 기능은 UI에서 숨기는 것만으로 끝내지 않고 Tool Registry에서도 차단한다.

## 11. Source는 비신뢰 데이터다

Gmail·Task·Calendar 본문은 업무 Evidence일 수 있지만 시스템 명령은 아니다.

- Raw Source 문자열을 Tool Name·Arguments로 실행하지 않는다.
- Source가 Policy·System Prompt 우선순위를 변경하지 못한다.
- Source 문자열이 Local File·Shell·Process·임의 URL Fetch를 유발하지 못한다.
- Query·Tool Arguments는 결정적 Validator를 통과한다.

## 12. 데이터 최소화와 Secret 경계

저장·로그 금지 대표 항목:

- OAuth Access/Refresh Token 원문
- LLM API Key
- Bootstrap·Session·PKCE Secret
- Claim Token / Session Key 원문
- 전체 LLM Prompt·Completion
- Gmail 전체 원문
- MCP 전체 Request·Response
- Gmail Attachment bytes·내용·Local Path
- Approval Snapshot 전체의 일반 Trace 복제

필요한 최소 데이터만 보존한다.

- 실제 사용 ResourceRef
- 판단·승인에 필요한 최소 Evidence excerpt
- Prompt ID·Version·Hash Metadata
- 상태·결과·지연·Count·Correlation ID

Credential은 OS Keyring 또는 Process Memory 경계를 따른다.

## 13. Attachment 안전 경계

Gmail 첨부파일은 Binary I/O 경계다.

### 수신
Attachment Metadata 조회 → 사용자 선택 → MCP attachment read → Download Stream.

### 발신
Local File → Staging Descriptor/SHA-256 → Approval Business Arguments → Claim V2 → MCP가 bytes/hash 재검증 → MIME Draft/SEND.

첨부파일 bytes·내용은 LLM Prompt·Context·Evidence·SQLite·Trace로 보내지 않는다.

## 14. Domain Store·Checkpoint·SSE 불변조건

```text
Domain Store = 승인·실행·검증의 사실 기준점
Checkpoint   = Graph 재개 위치
SSE / UI     = 사용자 Projection
```

- SSE 누락은 Workflow 실패가 아니다.
- Checkpoint가 실행 단계라고 해서 Write 성공이 아니다.
- UI 중복 클릭은 Command Receipt와 Domain Guard가 막아야 한다.
- Domain과 Checkpoint가 충돌하면 추정하지 않고 안전한 Recovery 경로로 전환한다.

## 15. Graph Profile이 달라도 안전 엔진은 하나다

SINGLE / THREE / SIX가 달라도 다음은 동일해야 한다.

- Policy
- Domain Validation
- Approval
- Claim
- Execution
- Verification
- Recovery
- Command Receipt
- Google Write Adapter

Agent topology는 실험 대상이지만 Safety invariant는 후보마다 달라지지 않는다.

## 16. 취소 불변조건

- RequestCancel의 Receipt/Version 판정 전에 child state를 변경하지 않는다.
- `CANCEL_REQUESTED` 이후 새 Claim·Write를 시작하지 않는다.
- `EXECUTING`은 결과 확정 전 `CANCELLED`로 덮어쓰지 않는다.
- `EXECUTED`는 Verification 후 취소를 마무리한다.
- `UNKNOWN_RESULT`가 남아 있으면 Recovery로 결과를 확정한 뒤 cancel intent를 이어간다.
- 이미 성공한 Google Write를 rollback하지 않는다.
- 미실행 Action만 `CANCELLED` 처리한다.

## 17. 장애·재시작에서도 같은 계약을 유지한다

브라우저 새로고침, SSE 단절, FastAPI 재시작, MCP 종료, OAuth 재인증, Google 응답 유실은 중복 Write의 이유가 될 수 없다.

- UI 재연결이 Action 재실행을 의미하지 않는다.
- Resume 전에 Domain 상태를 확인한다.
- OAuth 재인증 후 최신 Source·Version을 다시 검증한다.
- 전달 가능성이 있는 Write를 자동 재전송하지 않는다.
- Recovery 상태 변경은 Domain Command를 거친다.

이 불변조건들이 LLM의 실수, Transport 장애, 사용자 중복 클릭을 실제 Google Side Effect로부터 격리한다.
