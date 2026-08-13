# Google Work Agent · Code Agent Start Here

> **Source Pack:** 2026-08-13 Notion Canonical · DB Schema v1.6 · Workflow v7.5
> **목적:** 구현·검수 Agent가 현재 계약을 먼저 읽고 실제 소스와 비교한 뒤 안전 경계를 훼손하지 않고 작업하도록 한다.

## 1. 최초 읽기 순서

```text
00-google-work-agent-overview.md
→ 00-PROJECT-SOURCE-GUIDE.md
→ 01-requirements-prd.md
→ 01-b-policy-definition-v2.8.md
→ 03-system-architecture.md
→ 04-domain-database-design.md
→ 0001~0005 migration SQL
→ state-transition-contract-v1.4.md
→ 05-context-retrieval.md
→ 06-agent-workflow.md
→ 07-tool-mcp-internal-interface.md
→ 12-test-design.md
→ 15-agent-capability-failure-prompt-contract.md
```

## 2. 구현 기준점
- 실제 구현 상태는 repository source/test/runtime migration을 확인한다. 문서와 코드가 다르면 임의로 하나를 정답으로 만들지 말고 차이를 보고한다.
- 설계 권위는 Concern Owner 규칙을 따른다. 01-B 안전, 04 Domain/DB, 05 Retrieval, 06 Workflow, 07 Interface를 하위 문서가 완화할 수 없다.

## 3. LangGraph 구현 불변조건
- Main Supervisor는 결정적 Router다.
- Agent는 LangGraph Subgraph이며 내부 Node마다 최소 State Projection을 사용한다.
- Schema=출력 통제, State=확정 메모리, Prompt=현재 Node 작업 지시, Edge=결정적 Routing이다.
- Tool Route가 IN/OUT을 한 번 확정하며 downstream Tool 재선택을 금지한다.
- Google Workspace는 MCP 단일 경계다. 제품 Core에서 Gmail·Tasks·Calendar Provider API/SDK 직접 호출·직접 Provider Client 구성·MCP 장애 시 direct fallback을 금지한다.
- `TASK + CREATE` 중복검사, `CALENDAR + CREATE` 충돌검사는 Policy Precondition READ다.
- 사용자 범위 밖 READ는 `SCOPE_EXPANSION_REQUIRED` 확인 전 실행하지 않는다.
- LLM 관계 후보는 deterministic validation 전 최종 중복/충돌 사실이 아니다.
- Policy Override는 실제 사용자 응답 기반 `PolicyConfirmationReceiptV1` 없이는 진행하지 않는다.

## 4. Write 불변조건
- 승인 없는 Write 금지.
- ClaimContextV2는 승인 Business Hash와 실제 Execution Hash를 분리한다.
- MCP Tool·MCP 내부 Google Provider API·LLM 외부 호출 중 SQLite Write Transaction을 유지하지 않는다.
- `UNKNOWN_RESULT` blind resend 금지.
- Write 후 MCP Verification Read로 실제 Google Provider 상태 재조회 필수.

## 5. 구현 완료 검증
Repository가 정의한 테스트/정적 분석 명령을 우선한다. 최소 Unit/Integration/전체 테스트, Ruff, mypy, `git diff --check`를 실행하고 안전·상태 전이·Tool Contract 실패가 있으면 완료로 판정하지 않는다.
