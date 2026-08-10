# 00-A. 제품 설계 결정과 선택 이유

> **문서 성격:** 설명 문서. 구현 세부값의 권위 문서가 아니다. 충돌 시 `01 PRD`, `01-B Policy`, `03 Architecture`, `04 Domain·DB`, `05 Retrieval`, `06 Workflow`, `07 Interface`와 실행 가능한 Domain/SQL Constraint를 따른다.

## 1. 한 문장으로 설명하면

Google Work Agent는 Gmail·Google Tasks·Google Calendar의 실제 근거를 연결해 업무를 이해하고 계획하되, **외부 상태를 바꾸는 권한과 실행 성공의 사실은 LLM이 아니라 결정적 소프트웨어가 통제하는 로컬 업무 Agent**다.

```text
사용자 요청
→ 필요한 Google 자료 조회
→ Evidence 구성
→ 업무 분석
→ 답변 또는 Action Plan
→ Domain·Policy 검증
→ 사용자 승인
→ Claim V2
→ Google Write
→ Google 실제 상태 재조회
→ Verification / Recovery
```

## 2. 해결하려는 문제

이 프로젝트는 단순 채팅 요약기가 아니라 다음 세 가지를 해결한다.

1. **흩어진 업무 사실 연결** — 메일 요청, Task 상태·일정, Calendar 가용 시간을 하나의 업무 맥락으로 묶는다.
2. **근거 있는 판단** — 추측이 아니라 실제 Google Resource와 최소 Evidence를 바탕으로 분석·계획한다.
3. **안전한 실행** — 계획이 좋아도 Policy·승인·무결성·검증 계약을 통과하지 않으면 외부 상태를 바꾸지 않는다.

비목표는 자유형 Peer-to-Peer Agent 군집, 승인 없는 자동 Write, SaaS형 원격 멀티사용자 서비스다.

## 3. LLM과 결정적 코드의 책임을 왜 나누는가

| 영역 | 주 책임 | 이유 |
|---|---|---|
| LLM·Agent | 요청 이해, Source 전략, Evidence 선택, 분석, 계획, 검토 | 자연어와 불완전한 업무 맥락 해석에 강함 |
| Deterministic Supervisor | Phase·Typed Result·Budget 기반 Routing | 흐름·재개·비용을 예측 가능하게 유지 |
| Domain·Policy | 허용 여부, 상태 전이, 승인·중복·충돌·무결성 | 제품 사실을 확률적 판단에 맡기지 않기 위해 |
| Execution·Verification | 승인된 Write 실행, Google 재조회, Recovery | Tool 응답이나 LLM 선언이 아니라 실제 외부 상태로 성공을 확정하기 위해 |

핵심 원칙은 **Agent는 판단하고 제안하지만 실행 권한과 실행 성공의 사실은 소유하지 않는다**는 것이다.

## 4. 왜 결정적 Supervisor인가

Main Supervisor가 Agent Subgraph를 호출하고, Agent는 Versioned Typed Result와 disposition을 Parent에 반환한다.

```text
Main Supervisor
→ Agent Subgraph
→ Typed Result + disposition
→ Main Supervisor
→ 다음 Agent / Interrupt / Domain 경로
```

이 구조는 다음을 가능하게 한다.

- 어떤 Agent가 왜 호출됐는지 추적 가능
- Agent 간 무한 대화·책임 중복 방지
- Agent invocation 수와 LLM call 수 분리 계측
- Checkpoint·Interrupt·Resume 경계 명확화
- Handoff 손실과 오류 전파 평가
- Agent topology와 무관한 공통 Write 안전 경로 유지

Agent가 다른 Agent를 직접 호출하지 않는 이유도 동일하다. 다른 책임이 필요하면 disposition을 반환하고 Supervisor가 다음 Edge를 선택한다.

## 5. 이 프로젝트에서 Agent의 정의

Agent는 단일 Prompt 함수나 wrapper가 아니라 **Main Supervisor가 호출하는 LangGraph Subgraph**다.

필수 특성:

- 안정적인 Role/Responsibility Contract
- Parent State에서 필요한 입력만 받는 Input Projection
- invocation 범위 AgentLocalState
- PromptRef 기반 LLM Node
- Schema·Semantic Validation
- bounded Repair/Revision
- 필요할 때 결정적 Application/Read Node
- Versioned Typed Result + disposition 반환

따라서 다음 개념을 구분한다.

- Agent 수 ≠ LLM Call 수
- Prompt 수 ≠ Agent 수
- AgentLocalState ≠ 장기 Memory
- wrapper 함수 ≠ Agent Subgraph

## 6. 왜 SINGLE / THREE / SIX를 비교하는가

처음부터 6개 Agent가 정답이라고 가정하지 않는다.

- `SINGLE_BASELINE`: 통합 Agent Subgraph 1개
- `THREE_STAGE`: Agent Subgraph 3개
- `SIX_ROLE_BASELINE`: 전문 Agent Subgraph 6개

세 Profile은 모두 요청 이해 → Source/Read → Evidence → 분석 → 계획 → 품질 점검이라는 **동일 Semantic Responsibility**를 가진다. 비교하는 독립변수는 책임 분해 수준이다.

평가 질문은 다음과 같다.

> 전문화가 업무 성공률·오류 격리·검토 품질을 얼마나 높이며, 그 대가로 LLM Call·Token·Latency·Handoff 위험이 얼마나 증가하는가?

Graph Profile이 달라도 Domain·Policy·Approval·Claim·Execution·Verification·Recovery는 동일한 코드를 사용한다.

## 7. 왜 Acquisition 안에 결정적 Read가 있는가

LLM은 Source·순서·Budget 전략을 제안할 수 있지만 Raw Query나 MCP Arguments를 직접 실행하지 않는다.

```text
Acquisition Agent Subgraph
→ LLM: Source·순서·Budget 전략
→ Plan Validation
→ Deterministic Query Builder
→ MCP Read Port
→ Google READ
→ AcquisitionResult Validation
→ Parent 반환
```

이 구조는 LLM의 판단 유연성을 사용하면서 실제 API 실행은 타입·범위·Page Token·Resource ID 검증을 통과한 코드가 담당하게 한다.

## 8. 왜 모든 Profile이 같은 Write Engine을 쓰는가

Write 경로가 Profile마다 다르면 Agent 구조 효과와 안전 정책 효과를 분리해 평가할 수 없다. 또한 승인 후 LLM이 Tool·Arguments·Target을 다시 생성하면 사용자가 승인한 작업과 실제 실행이 달라질 수 있다.

공통 실행 경로:

```text
Plan Draft
→ Domain Validation
→ Approval Snapshot
→ Claim Commit
→ ClaimContextV2 검증
→ MCP / Google Write
→ Google 재조회 Verification
→ Recovery / Finalize
```

`approval_arguments_hash`는 사용자가 승인한 Business Arguments를 고정하고, `execution_arguments_hash`는 실제 MCP Dispatch Payload를 고정한다. MCP는 서명·TTL·Service/MCP instance·Action·Approval·Attempt·Tool·두 Hash·Nonce와 실제 수신 Arguments를 다시 검증한 뒤에만 Write한다.

## 9. Gmail 첨부파일을 LLM 기능과 분리한 이유

첨부파일은 P0에서 “파일 내용을 이해하는 Agent 기능”이 아니라 **Google과 사용자 로컬 파일 사이의 Binary I/O 경계**다.

- 수신: Attachment Metadata → 사용자 선택 → MCP Read → Download Stream
- 발신: Local File → Staging Descriptor/SHA-256 → Approval → Claim V2 → MIME Draft/SEND
- 첨부파일 bytes·내용은 LLM Prompt·Context·Evidence·SQLite·Trace에 넣지 않음

이렇게 하면 Attachment 기능을 추가해도 Agent Context와 개인정보 경계를 넓히지 않는다.

## 10. 왜 Domain Store와 Checkpoint를 분리하는가

```text
Domain Store = 무엇이 승인·실행·검증되었는지
Checkpoint   = 어디서 다시 시작할지
SSE/UI       = 사용자에게 보여주는 Projection
```

Checkpoint가 실행 단계에 있다는 사실은 Google Write 성공을 의미하지 않는다. 승인·Attempt·Verification의 제품 사실은 Domain Store가, 실제 외부 상태는 Google 재조회가 결정한다.

이 분리는 브라우저 새로고침, REST Retry, SSE 재연결, 앱 재시작, 응답 유실과 `UNKNOWN_RESULT` 상황에서 중복 Write를 막는 핵심이다.

## 11. 왜 Agent별 장기 Memory를 두지 않는가

P0의 목적은 장기간 사람처럼 기억하는 Assistant가 아니라 현재 업무를 최신 Google Source와 정확한 상태로 처리하는 것이다.

Agent별 장기 Memory를 두면 오래된 사실이 Google 최신 상태보다 우선할 수 있고, Agent 간 기억 불일치가 생기며, 승인·실행 권위가 흐려지고, 오류 재현과 실험 통제가 어려워진다.

따라서 장기 사실은 Google 원본·Main Graph Typed State·Domain Store가 담당하고 Agent는 invocation-local state만 사용한다.

## 12. 왜 로컬 제품인가

P0는 단일 사용자의 Gmail·Tasks·Calendar를 다룬다. 원격 SaaS Backend 대신 사용자 PC에서 실행해 원격 사용자 데이터 저장 계층을 만들지 않고, Credential·Domain Store 경계를 좁히며, 단일 사용자 상태·복구를 단순화한다.

```text
Launcher
→ FastAPI Local Agent Service
→ React UI
→ LangGraph / Domain
→ MCP stdio
→ Google APIs
```

운영 UI와 Local API는 `127.0.0.1` same-origin 구조를 사용한다.

## 13. 왜 API LLM을 먼저 안정화하고 Local LLM을 연결하는가

제품은 API LLM과 검증된 GPU Local LLM을 지원하지만 두 Runtime 문제를 동시에 디버깅하지 않는다.

```text
API LLM으로 수직 흐름·안전 계약·Evaluation Runner 안정화
→ 동일 Port에 Ollama Adapter 연결
```

이 순서는 Workflow·Domain 문제와 모델 Runtime 문제를 분리한다. CPU-only 또는 GPU 기준 미달 환경은 API_LLM으로 고정한다.

## 14. 의도적으로 선택하지 않은 구조

| 선택하지 않은 방향 | 이유 |
|---|---|
| 자유형 Peer-to-Peer Agent 군집 | 책임·비용·오류 전파·승인 경계를 추적하기 어려움 |
| LLM의 Raw MCP/Google Tool 직접 실행 | Query·Arguments·범위 검증을 우회할 수 있음 |
| 승인 없는 자동 Write | 외부 Side Effect의 사용자 통제 상실 |
| Tool 응답만으로 Write 성공 확정 | 응답 유실·정규화 차이·실제 불일치 처리 불가 |
| Agent별 장기 Memory | 최신 Google 사실과 충돌·재현성 저하 |
| 영구 Vector Index 기본화 | P0 문제보다 복잡도가 커지고 원본 최신성 경계가 흐려짐 |
| 원격 SaaS Backend | P0 단일 사용자 로컬 범위를 넘어서는 운영 복잡도 |

## 15. 설계 판단을 읽는 기준

이 프로젝트의 핵심은 “Agent가 많다”가 아니라 다음 네 가지다.

1. **판단과 실행 권한을 분리했다.**
2. **제품 사실과 Workflow 재개 상태를 분리했다.**
3. **Graph 구조를 고정 정답으로 두지 않고 실험으로 선택한다.**
4. **실제 Google 상태를 다시 읽어 Write 성공을 검증한다.**

세부 숫자·상태·Tool·Schema가 필요하면 설명 문서가 아니라 각 Concern Owner 문서를 기준으로 구현한다.
