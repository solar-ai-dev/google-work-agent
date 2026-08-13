# 00-A. 제품 설계 결정과 선택 이유

> 이 문서는 설계 선택의 이유를 설명하는 온보딩 문서다. 구현 세부의 권위는 01/03/04/05/06/07 등 Concern Owner 문서가 가진다.

## 1. 제품의 중심 명제

Work Agent는 Connector 확장 가능한 Core가 외부 업무 시스템의 실제 근거를 연결해 업무를 이해하고 계획하되, **외부 상태를 바꾸는 권한과 실행 사실은 LLM이 아니라 결정적 소프트웨어가 통제**하도록 설계한다. P0 첫 Connector는 Google Workspace다.

## 2. 왜 Connector 경계를 두는가

Google Workspace가 현재 핵심 기능이지만 Core를 Gmail/Tasks/Calendar API 구조에 직접 묶으면 GitHub·Jira·Notion 같은 후속 시스템을 추가할 때 Workflow/Domain까지 Provider 세부가 전파된다.

따라서:

```text
Core
→ Connector Registry
→ MCP Port
→ Connector MCP Server
→ Provider Adapter
```

로 경계를 둔다. Core는 `connector_id`, Resource, Effect, Tool Schema 같은 계약을 다루고 Provider API·Credential·Pagination 세부는 Adapter가 소유한다.

## 3. 왜 결정적 Supervisor인가

자유형 Peer-to-Peer Agent 대신 Main Supervisor가 Subgraph를 호출한다.

- Routing을 재현할 수 있다.
- Agent 간 무한 대화를 차단한다.
- Checkpoint/Interrupt/Resume 위치가 명확하다.
- Handoff 오류를 계측할 수 있다.
- 안전·실행 Engine을 Agent topology와 분리할 수 있다.

## 4. 왜 1/3/6 Agent Profile을 비교하는가

6 Agent가 정답이라고 가정하지 않는다. 같은 의미 책임을 다른 분해 수준으로 비교한다.

```text
Request Understanding
→ Tool Route
→ Retrieval
→ optional Work Analysis
→ Planning
→ Review
```

SINGLE/THREE/SIX의 차이는 책임을 몇 개 Subgraph에 나누는가이며, 안전·Tool·Policy 계약은 동일하다.

## 5. 왜 Tool Route와 Retrieval을 분리하는가

Tool Route는 **어디서 읽고(IN), 어디에 어떤 Effect를 만들지(OUT)** 정한다. Retrieval이 다시 Tool을 선택하거나 Planning이 Tool identity를 바꾸면 책임 중복과 승인 무결성 문제가 생긴다.

따라서 Tool Route를 공식 State Artifact로 고정하고 Retrieval/Planning은 소비만 한다.

## 6. 왜 Write Engine은 하나인가

Graph Profile마다 Write 구현이 다르면 Agent 구조 효과와 안전 정책 효과를 분리할 수 없다. 모든 Profile은 동일한:

```text
Domain Validation
→ Approval
→ Claim
→ Write
→ Verification
→ Recovery
```

Engine을 사용한다.

## 7. 왜 Domain Store와 Checkpoint를 분리하는가

```text
Checkpoint = 어디서 다시 시작할지
Domain Store = 무엇이 승인·실행·검증됐는지
```

Checkpoint가 실행 단계라는 사실은 Write 성공 증거가 아니다. 브라우저 새로고침·앱 재시작·응답 유실에서도 Domain Store를 기준으로 복구한다.

## 8. 왜 Agent별 장기 Memory를 두지 않는가

P0 문제는 장기 개인 Assistant가 아니라 최신 외부 Source를 근거로 현재 업무를 안전하게 처리하는 것이다. Agent별 장기 Memory는 stale 사실·상충 기억·재현성 저하를 만들 수 있다.

## 9. 왜 로컬 제품인가

P0는 단일 사용자 개인 업무 데이터가 대상이다. 원격 SaaS Backend 대신 사용자 PC에서 Frontend/Service/MCP/DB를 실행해 데이터 경계를 좁히고 운영 복잡도를 줄인다.

## 10. 왜 API LLM과 Local LLM을 Port로 분리하는가

업무 계약은 모델에 종속되지 않아야 한다. LLM Runtime은 Port 뒤에 두고 API/Local 후보를 동일 Prompt/Schema/Graph 조건에서 평가한다.

## 11. DB는 왜 즉시 완전 일반화하지 않는가

현재 DB v1.6은 Google Workspace-first P0 구현을 반영한다. 아직 요구사항이 없는 미래 Connector를 위해 미리 Table을 추측하지 않는다. 대신 Core 의미를 Connector-neutral로 정의하고 실제 두 번째 Connector 도입 시 새 Migration으로 확장한다.
