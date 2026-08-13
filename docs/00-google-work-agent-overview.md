# Google Work Agent — 프로젝트 개요

## 한 문장

Google Work Agent는 **Connector 확장 가능한 Work Agent Core** 위에 Google Workspace를 P0 첫 Connector로 제공하는 Windows 로컬 업무 Agent다. 외부 업무 근거를 수집해 분석·계획하고, 사용자가 승인한 외부 변경만 결정적 실행·검증 경로로 수행한다.

## P0 제품 범위

```text
Google Workspace Connector
├─ Gmail
├─ Google Tasks
└─ Google Calendar
```

현재 실제 사용자 기능은 Google Workspace에 집중한다. Connector 일반화는 Google 기능을 추상적으로 숨기기 위한 것이 아니라, Core가 특정 Provider API에 종속되지 않게 만드는 아키텍처 경계다.

## 전체 흐름

```text
사용자 요청
→ Request Understanding
→ Connector + IN/OUT Tool Route 확정
→ Connector MCP Read / Retrieval / RAG Evidence
→ 필요한 경우 Work Analysis
→ Planning
→ Review
→ Domain·Policy Validation
→ 사용자 승인
→ Claim
→ Connector MCP Write
→ Provider 상태 재조회
→ Verification / Recovery
```

## 책임 분리

| 영역 | 책임 |
|---|---|
| LLM·Agent | 요청 이해, Route 의미 판단, Query 계획, Evidence 선택, 업무 분석, Arguments 초안, Review |
| Supervisor | Typed Result·Disposition 기반 결정적 Routing |
| Domain·Policy | 허용/차단, 상태 전이, 승인 무결성, 실행권 |
| Connector Runtime | Registry, MCP Transport, Connector별 Tool 경계 |
| Connector Adapter | Provider Credential, API/SDK, raw response 해석 |
| SQLite Domain Store | 승인·실행·검증의 영속 사실 |
| LangGraph Checkpoint | Workflow 재개 위치 |

## Connector 구조

```text
FastAPI / Application / LangGraph / Domain
        ↓
Connector Registry
        ↓
MCP Client / Port
        ↓
Connector MCP Server
        ↓
Provider Adapter
        ↓
Provider API
```

P0:

```text
connector_id = google_workspace
→ Google Workspace MCP Server
→ Gmail / Tasks / Calendar APIs
```

Core에서 Provider API/SDK를 직접 호출하지 않는다.

## LangGraph 구조

- Main Graph는 결정적 Supervisor다.
- Agent는 전문 LangGraph Subgraph다.
- Main State는 공식 Versioned Typed Artifact만 보존한다.
- Subgraph Local State는 invocation 범위 작업 메모리다.
- Agent 간 직접 호출은 없다.
- Confirmation은 발생 Subgraph checkpoint로 resume한다.
- 공식 Artifact는 단일 Owner가 새 revision을 만든다.

평가에서는 같은 semantic responsibility를 다음 Profile로 비교한다.

```text
SINGLE_BASELINE = 1 Agent Subgraph
THREE_STAGE     = 3 Agent Subgraphs
SIX_ROLE_BASELINE = 6 Agent Subgraphs
```

Agent 수와 LLM Call 수는 동일 개념이 아니다.

## 안전 모델

외부 Write는 반드시 다음 체인을 통과한다.

```text
Plan
→ Domain Validation
→ Approval Snapshot
→ Claim V2
→ Connector MCP Write
→ Verification Read
→ VERIFIED / RECOVERY_REQUIRED
```

핵심 원칙:

- 승인 없는 Write 금지
- 승인 인자 변경 금지
- `UNKNOWN_RESULT` blind resend 금지
- Provider 상태 재조회 없는 성공 확정 금지
- Source 본문은 항상 비신뢰 데이터
- UI/SSE/Checkpoint는 실행 사실의 기준점이 아님

## 현재 DB 일반화 경계

DB Schema v1.6은 실제 P0 구현에 맞춰 Google Workspace-first 구조를 가진다.

- `GoogleAccount`는 현재 P0 Connector-specific Entity다.
- Core Resource identity의 장기 의미는 `connector_id + resource_type + external_resource_id`다.
- 실제 신규 Connector 지원 시 새 Migration으로 확장한다.
- 기존 `0001~0005` Migration은 수정하지 않는다.

## 평가

안전은 점수가 아니라 Gate다.

```text
Safety / Integrity Gate
→ Business Task Success
→ Process 분석
→ Efficiency
→ Reliability / Holdout / Stress
```

비용·Token·Latency가 안전 또는 업무 실패를 상쇄하지 않는다.
