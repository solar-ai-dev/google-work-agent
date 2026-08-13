# Google Work Agent — Coding Agent Start Here

## 목적

이 문서는 코딩 에이전트가 저장소를 수정하기 전에 읽어야 하는 **진입 가이드**다. 권위 계약 자체를 새로 정의하지 않으며, 충돌 시 25개 Canonical Source 문서를 따른다.

## 현재 설계 기준

- 제품은 Windows 11 x64 단일 사용자 로컬 애플리케이션이다.
- Frontend는 React/TypeScript/Vite, Local Agent Service는 FastAPI, Workflow는 LangGraph다.
- Main Graph는 결정적 Supervisor이며 Agent는 전문 LangGraph Subgraph다.
- 외부 업무 시스템은 **Connector Registry → MCP Client/Port → Connector MCP Server → Provider Adapter** 경계를 통해 접근한다.
- P0 첫 Connector는 `google_workspace`이며 Gmail·Google Tasks·Google Calendar를 제공한다.
- Core/Application/LangGraph/Agent/Domain은 Provider API/SDK를 직접 호출하지 않는다.
- 모든 Write는 `Domain Validation → Approval → Claim → Connector MCP Write → Verification Read`를 거친다.
- Domain Store는 승인·실행·검증 사실의 기준점이며 Checkpoint는 Graph 재개 위치다.

## 반드시 먼저 읽을 문서

```text
01 PRD
01-A Functional
01-B Policy
03 Architecture
04 Domain·DB
05 Retrieval
06 Workflow
07 Interface
08 Sequence
09 Security
12 Test
15 Agent Capability·Failure·Prompt
```

DB 또는 상태 전이를 변경하면 추가로 다음을 읽는다.

```text
state-transition-contract-v1.4.md
state-transition-test-matrix-v1.4.md
0001~0005 migration SQL
```

## 구현 시 핵심 불변조건

1. LLM이 Policy 최종 허용 여부를 결정하지 않는다.
2. Agent가 다른 Agent를 직접 호출하지 않는다.
3. Tool Route가 Connector/IN/OUT Tool을 확정한 뒤 Retrieval·Planning이 재선택하지 않는다.
4. 외부 READ는 Retrieval의 결정적 Application Node가 Connector MCP Read Port를 호출한다.
5. 외부 Provider API direct fallback을 만들지 않는다.
6. 승인 전에 Write하지 않는다.
7. 승인된 Business Arguments와 실제 실행 Arguments의 무결성을 Claim V2로 검증한다.
8. `UNKNOWN_RESULT`에서는 blind resend하지 않는다.
9. 성공 Write는 Provider 상태 재조회로 검증한다.
10. 기존 Migration은 이력/checksum Artifact이므로 소급 수정하지 않는다.

## Connector 확장 시 주의

Core의 장기 의미는 Connector-neutral이지만 현재 P0 구현에는 Google Workspace-first 호환 구조가 남아 있다.

- DB v1.6의 `GoogleAccount` / `resource_refs.source` / 일부 CHECK는 P0 Google Workspace 값에 닫혀 있다.
- 실제 두 번째 Connector를 추가할 때는 새 Migration으로 Account binding과 Resource identity를 확장한다.
- 미래 Connector의 Tool 이름·OAuth 방식·Schema를 미리 추측해 문서나 코드에 넣지 않는다.
- 먼저 Connector capability/registry/port 계약을 만족시키고 Provider-specific 세부는 Adapter 내부로 격리한다.

## 수정 순서

```text
권위 문서 확인
→ 현재 구현 조사
→ Gap 식별
→ 최소 완결 변경
→ Contract/Unit Test
→ Integration Test
→ 관련 Safety Regression
→ 문서/구현 정합성 재검수
```

## 금지

- 설계 근거 없이 광범위한 리네이밍
- 안전 임계 흐름과 무관한 대규모 동시 리팩터링
- Provider API direct call 추가
- 승인/Claim/Verification 우회
- Migration 소급 수정
- Prompt에 Gold/Grader/Expected Route 누출
- 실제 사용자 Gmail·Tasks·Calendar 데이터의 테스트 Fixture 사용
