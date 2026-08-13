# Google Work Agent — Overview

## 5분 안에 이해하기

Google Work Agent는 **Connector 확장 가능한 Work Agent Core** 위에 Google Workspace를 첫 Connector로 제공하는 Windows 로컬 업무 Agent다. P0에서는 Gmail·Tasks·Calendar의 근거를 모아 업무를 이해·분석하고, 필요한 경우 사용자가 승인할 수 있는 Action Plan을 만든다.

```text
사용자 요청
→ Request Understanding
→ IN/OUT Tool Route 확정
→ Connector MCP Read로 외부 자료 조회
→ Run-scoped RAG로 Evidence 선택
→ 필요한 경우 Work Analysis
→ 답변 또는 Action Plan
→ Review·Domain·Policy 검증
→ Write이면 사용자 승인
→ Claim
→ Connector MCP Write → Provider 반영
→ Verification Read
→ Verification / Recovery / Finalize
```

## LLM과 결정적 코드의 경계

| LLM·Agent | 결정적 코드 |
|---|---|
| 요청 이해, Resource·Effect 의미 판단, Query 계획, Evidence 선택, 업무 분석, Arguments 작성, 계획 검토 | Registry eligibility, Policy, 승인, Claim, Query/시간 계산, Write, Verification, Recovery, Domain 상태 전이 |

## Agent Graph

- Main Graph: 결정적 Supervisor.
- 공식 Main State: Versioned Typed Artifact만 저장.
- Agent: Request Understanding / Tool Route / Retrieval / Work Analysis / Planning / Review의 전문 LangGraph Subgraph.
- Agent별 장기 Memory는 두지 않는다.
- `SINGLE=1`, `THREE=3`, `SIX=6` Profile을 동일 안전 Engine 위에서 비교한다.

## Connector 경계

```text
React / FastAPI / Application / LangGraph / Agent / Domain
→ Connector Registry
→ MCP Client/Port
→ Connector MCP Server
→ Provider Adapter
→ Provider API
```

P0 첫 Connector는 `google_workspace`다. Core가 Gmail/Tasks/Calendar API를 직접 호출하지 않는다.

## 영속·재개

- SQLite Domain Store: 승인·실행·검증의 사실 기준점.
- LangGraph Checkpoint: 재개 위치 기준점.
- SSE/UI State: 화면 Projection.
- OS Keyring: OAuth/API Key 등 Secret.

## 현재 Canonical

`04 v1.19 / 06 v7.12 / 07 v2.18 / 08 v3.12 / 12 v3.19 / DB v1.6 / State v1.5`
