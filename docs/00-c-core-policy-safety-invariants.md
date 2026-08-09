# 00-C. 핵심 정책·안전 불변조건 요약

> **R8.3 핵심 관점 문서:** 어떤 구현·Prompt·Graph에서도 깨면 안 되는 선을 요약한다. 실제 권위는 01-B, 04/State Contract/DB Constraint, 07, 09가 소유한다.

## 1. 한 문장
LLM의 좋은 의도를 신뢰하는 대신 권한·상태·인자·실행·검증을 결정적 계약으로 분리해 잘못된 판단이 실제 Google Side Effect로 이어지지 않게 한다.

## 2. 신뢰 경계
- LLM/Agent: 언어 해석·전략·분석·계획 후보
- Supervisor: Typed Result 기반 Routing
- Domain Store: 승인·Action·Attempt·Verification 영속 사실
- Google 재조회: 실제 외부 Resource 상태
- Checkpoint: Workflow 재개 위치

## 3. Agent가 못 하는 것
Policy 최종 판정, Approval 우회, Google Write 직접 실행, 승인 인자 변경, Write 성공 확정, UNKNOWN_RESULT blind resend, Domain 상태 직접 변경.

## 4. READ / WRITE
READ는 요청 범위에서 자동 가능하며 Approval·ExecutionAttempt·Verification Row가 없다. WRITE는 CREATE/UPDATE/SEND/허용 DELETE 모두 승인 경계를 통과한다.

## 5. Approval
Action Version, Tool, Effect, Canonical Arguments/Hash, Target, Source Snapshot, Policy/Tool Schema Version, Expiry를 고정한다. 변경·만료·재계획 시 재승인한다.

## 6. Claim과 외부 I/O
`Claim Transaction COMMIT → external MCP/Google → 새 DB Transaction에서 version/state 재검사 → 결과 저장`. 외부 I/O 중 SQLite Write Transaction을 유지하지 않는다.

## 7. FAILED와 UNKNOWN_RESULT
FAILED는 Google 미변경이 확정된 경우에만 사용한다. Retry는 `FAILED → MODIFIED → 최신 Source/Policy → 새 Approval → 새 Attempt`다. UNKNOWN_RESULT에서는 기존 결과 조회만 허용하며 새 Attempt·blind resend는 금지한다.

Write Adapter는 `NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST`를 보존하며 `NOT_SENT`만 FAILED 후보다. dispatch 이후 Timeout·5xx·response loss는 미전달 보장이 없으면 UNKNOWN_RESULT다.

## 8. Verification / MISMATCH
CREATE/UPDATE는 GET 비교, SEND는 Sent Lookup, DELETE는 Target 부재/삭제 상태를 확인한다. MISMATCH Action/Verification은 보존하고 Run은 `RECOVERY_REQUIRED`로 전환한다.

P0 Recovery:
- `ACCEPT_PARTIAL`: 현재 실제 상태를 수용, 추가 Write 0, 미실행 Action 취소, Run COMPLETED+PARTIAL.
- `CREATE_CORRECTIVE_PLAN`: 실제 상태를 기반으로 새 Plan Revision과 새 Approval·Claim·Attempt.

자동 수정·rollback·기존 MISMATCH Action 재실행은 금지한다.

## 9. 허용/금지
허용: Gmail Draft 생성·수정·SEND, Task 생성·수정·완료, Calendar 생성·수정·참석자 변경·Event DELETE.
금지: Gmail 원문 삭제, Task 삭제, 반복 Event 전체 일괄 수정, 안전 경계 우회.

## 10. Source 비신뢰
Gmail·Task·Calendar 본문은 Evidence이지 시스템 지시가 아니다. Raw Source를 Tool/Arguments로 실행하지 않고 deterministic validator를 거친다.

## 11. 데이터 최소화
Credential·Token·Claim Token·전체 Prompt/Completion·전체 Gmail 원문·전체 MCP request/response·Approval snapshot 전체를 일반 로그에 저장하지 않는다.

## 12. Domain / Checkpoint / UI
Domain Store=사실, Checkpoint=재개 위치, SSE/UI=Projection. 서로 대체하지 않는다.

## 13. Profile 독립 Safety
SINGLE/THREE/SIX는 reasoning 구조만 다르며 Policy·Validation·Approval·Claim·Execution·Verification·Recovery·Command Receipt·Google Adapter는 동일하다.

## 14. 장애·재시작
UI reconnect는 재실행이 아니다. Resume 전 Domain을 확인하고 OAuth 후 Source를 재조회한다. 전달 가능 Write는 자동 재전송하지 않는다. Crash 후 EXECUTING/UNKNOWN_RESULT/MISMATCH를 검사한다.

## 15. 코드 리뷰 즉시 차단 패턴
Agent→Write, LLM Policy override, 승인 후 Arguments 재생성, FAILED 직접 Execute, UNKNOWN_RESULT retry send, Tool response만으로 VERIFIED, MISMATCH 자동 수정, 외부 I/O 중 DB Write Tx, Claim 전 Write, Checkpoint를 실행 사실로 사용, READ에 Approval/Attempt/Verification, 금지 Tool 등록, Secret/원문 일반 로그.

## 16. 구현과 계약이 다를 때
현재 코드보다 최신 Concern Owner 계약이 우선한다. 설계가 상위 정책과 충돌하면 설계부터 수정한 뒤 코드를 맞춘다.

## 17. 요약
LLM이 실수하지 않는다고 믿어서 안전한 것이 아니라 Policy·Approval·Claim·상태 전이·Verification이라는 결정적 경계를 둬 부작용을 막는다. 응답을 못 받은 Write는 재전송하지 않고 실제 결과를 찾으며 성공은 Google 상태를 다시 읽어 확정한다.
