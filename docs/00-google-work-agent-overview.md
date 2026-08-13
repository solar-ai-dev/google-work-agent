# Google Work Agent · Overview

Google Work Agent는 Gmail·Tasks·Calendar의 근거를 모아 업무를 이해하고, 필요한 경우 사용자가 승인할 수 있는 실행 계획을 만든 뒤 안전하게 Google Workspace에 반영하는 Windows 로컬 업무 Agent다.

## 제품 흐름
```text
사용자 요청
→ Request Understanding
→ IN/OUT Tool Route
→ 필요한 MCP Read Tool + Run-scoped RAG Evidence
→ optional Work Analysis
→ Answer 또는 Action Plan
→ Review + Domain/Policy Validation
→ 사용자 승인
→ Claim + MCP Write Tool → MCP 내부 Provider Adapter 반영
→ MCP Verification Read
```

## Agent 구조
Release 후보의 SIX 역할은 Request Understanding / Tool Route / Retrieval / Work Analysis / Planning / Review다. Agent 수 자체가 목적은 아니며 SINGLE/THREE/SIX를 실험으로 비교한다. 모든 Profile은 같은 Domain·Policy·Approval·Execution·Verification Engine을 공유한다.

## 핵심 설계 원칙
- Main Graph는 공식 Typed State와 Edge를 소유한다.
- 각 Agent는 LangGraph Subgraph이며 Node별 최소 Projection과 Local State를 가진다.
- Tool Route는 한 번 확정한다.
- Google Workspace 접근은 FastAPI/Application/LangGraph/Agent에서 직접 Provider API를 호출하지 않고 반드시 MCP Client/Port → Google Work MCP Server를 통과한다. Provider API/SDK는 MCP 내부 Adapter만 사용한다.
- Retrieval은 고정 IN Route에서 Query를 만들고 결정적 MCP Read Node로 Read/RAG/Evidence를 수행한다.
- Planning은 고정 OUT Route에서 Arguments/Dependency를 작성한다.
- 중복·충돌·시간 계산·Policy·Approval·Write·Verification의 결정 가능한 부분은 코드가 수행한다.
- Google Source 본문은 `UNTRUSTED_SOURCE_CONTENT / DATA_ONLY`다.
- SQLite Domain Store가 승인·실행·검증 사실의 기준점이다.

## 문서 원본
공식 원본은 Notion이며 Repository Markdown은 구현·리뷰용 Snapshot이다. 현재 버전은 `00-PROJECT-SOURCE-GUIDE.md`의 Manifest를 따른다.
