# 00-A. 제품 설계 결정과 선택 이유

> **R8.3 핵심 관점 문서:** 왜 이 제품을 이런 구조로 설계했는지 설명한다. 구현 세부의 권위는 01/03/04/05/06/07 Concern Owner 계약을 따른다.

## 1. 한 문장으로 설명하면
Google Work Agent는 Gmail·Google Tasks·Google Calendar의 실제 근거를 연결해 업무를 이해하고 계획하되, 외부 상태를 바꾸는 권한과 실행 사실은 LLM이 아니라 결정적 소프트웨어가 통제하는 로컬 업무 Agent다.

```text
사용자 요청 → Google 자료 탐색 → Evidence → 분석 → 답변/Plan
→ Domain·Policy → 승인 → 결정적 Write → Google 재조회 → Verification/Recovery
```

## 2. 풀려는 문제
1. 흩어진 Gmail·Task·Calendar 사실 연결
2. 실제 Resource/Evidence 기반 판단
3. 승인·무결성·Verification이 있는 안전한 실행

Agent 수를 늘리는 것, 모든 작업을 LLM에 맡기는 것, 자동 메일 전송 자체는 목표가 아니다.

## 3. 책임 분리
| 영역 | 주 책임 |
|---|---|
| LLM·Agent | 요청 이해, Source 전략, Evidence 선택, 분석, 계획, 검토 |
| Deterministic Supervisor | Phase·Typed Result·Budget 기반 Routing |
| Domain·Policy | 허용 여부, 상태 전이, 승인·중복·충돌·무결성 |
| Execution·Verification | 승인된 Write, 실제 Google 재조회, Recovery |

Agent는 판단하고 제안하지만 실행할 권리와 실행 성공의 사실을 소유하지 않는다.

## 4. 결정적 Supervisor
```text
Main Supervisor → Agent Subgraph → Versioned Typed Result → Supervisor → 다음 단계
```
Agent 간 직접 호출을 두지 않아 호출·비용·오류 전파·Checkpoint·Write 경계를 추적 가능하게 유지한다.

## 5. Agent 정의
Agent는 안정적 책임, Parent Input Projection, invocation-local state, PromptRef, validation/repair/revision, 필요한 deterministic node, Versioned Typed Result를 가진 실제 LangGraph Subgraph다. Agent 수·LLM Call 수·Prompt 수는 서로 다른 개념이다.

## 6. 1/3/6 Profile
`SINGLE_BASELINE=1`, `THREE_STAGE=3`, `SIX_ROLE_BASELINE=6`은 동일한 Request→Source/Read→Evidence→Analysis→Planning→Quality Review 의미 책임을 서로 다르게 분해한다. 최종 구조는 실험으로 선택한다.

## 7. Acquisition 안의 결정적 Read
LLM은 Source·순서·Budget을 제안하고 Query Builder·Page Validation·MCP Read는 같은 Acquisition invocation 안의 결정적 Node가 수행한다. 검증되지 않은 Raw Query를 직접 실행하지 않는다.

## 8. 공통 Write Engine
모든 Profile은 `Plan → Domain Validation → Approval → Claim → Google Write → Verification → Recovery/Finalize`를 공유한다. Graph 구조와 Safety Engine을 분리해 평가한다.

## 9. Domain Store와 Checkpoint
`Checkpoint=재개 위치`, `Domain Store=승인·실행·검증 사실`. UI/SSE/Checkpoint만으로 Write 성공을 확정하지 않는다.

## 10. Agent별 장기 Memory를 두지 않는 이유
오래된 기억이 최신 Google 상태와 충돌하거나 Approval/Execution authority가 흐려지는 것을 막고 재현 가능한 실험을 유지하기 위해 invocation-local state만 사용한다.

## 11. 로컬 제품인 이유
P0는 Windows 단일 사용자 앱이며 Launcher→FastAPI→React/LangGraph/Domain→MCP stdio→Google 구조를 사용한다. 원격 SaaS 데이터 저장 계층보다 Agent·Domain·Safety·Evaluation에 집중한다.

## 12. API/Local LLM 구현 순서
제품 수직 흐름과 안전 계약을 API LLM으로 먼저 안정화한 뒤 동일 Port에 Ollama Adapter를 연결해 Runtime 문제와 Workflow 문제를 분리한다.

## 13. 선택하지 않은 구조
- 자유형 Peer-to-Peer Agent 군집
- LLM Raw MCP/Google Tool 직접 실행
- Agent의 직접 Google Write
- Profile별 별도 Safety/Write Engine
- Agent별 장기 Memory
- 전체 Mailbox/Workspace 무제한 조회
- P0 원격 SaaS Backend

## 14. 구현과 설계가 다를 때
최신 Concern Owner 계약 → 실제 Source → 차이 원인 순으로 판단한다. 설계가 상위 Policy/Domain/Security와 충돌하면 코드 workaround 대신 설계를 먼저 수정·동기화한다.

## 15. 요약
Google Work Agent는 LLM이 실제 업무 맥락을 이해하고 계획하도록 하되 흐름은 결정적 Supervisor가, 업무 사실은 Domain Store가, 외부 Write는 사용자 승인과 Verification이 통제한다. 이 구조 안에서 1·3·6 Agent 분해의 실제 가치를 실험으로 증명한다.
