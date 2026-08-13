# Google Work Agent — Code Agent Start Here

> 이 문서는 구현 Agent용 온보딩 문서다. Concern Owner가 아니며 충돌 시 `00-PROJECT-SOURCE-GUIDE.md`와 01~15/Domain/SQL 계약을 따른다.

## 1. 현재 Canonical

- PRD v2.10 / Functional v2.15 / Policy v2.11 / UI v2.11
- Architecture v3.5 / Domain·DB v1.19 / DB Schema v1.6
- Retrieval v2.11 / Workflow v7.12 / Interface v2.18 / Sequence v3.12
- Security v2.10 / Infrastructure v2.9 / Observability v2.12
- Test v3.19 / Evaluation v3.9 / Operations v2.7 / Agent Capability v1.11
- Domain State Transition v1.5 / Test Matrix v1.5

## 2. 먼저 읽을 순서

```text
01 PRD → 03 Architecture → 06 Workflow → 08 Sequence
→ 01-A Functional → 01-B Policy
→ 04 Domain·DB → 05 Retrieval → 07 Interface
→ 09 Security → 10 Infrastructure → 11 Observability → 14 Operations
→ 12 Test → 13 Evaluation → 15 Agent Capability
```

## 3. 구현 불변조건

- 외부 업무 시스템 접근: `Core → Connector Registry → MCP Client/Port → Connector MCP Server → Provider Adapter`.
- Core에서 Provider API/SDK 직접 호출 또는 MCP 장애 시 direct fallback 금지.
- Agent/LLM은 Write를 직접 실행하지 않는다.
- 승인형 Write: Domain Validation → Approval → Claim → MCP Write → Verification → Recovery/Finalize.
- Claim Commit 전 MCP Write 0.
- `UNKNOWN_RESULT` blind resend 0.
- `FAILED + NOT_SENT`는 명시적 retry/cancel 전 자동 재실행 0.
- Action 실행 중 Run을 자동 EXECUTING으로 덮지 않는다. 정상 Write는 첫 Verification까지 Run WAITING_APPROVAL 유지.
- Confirmation은 owner checkpoint resume. 모든 확인을 Request Understanding으로 재시작하지 않는다.
- FINALIZE는 비Terminal Run을 직접 종료하지 않는다.
- Migration SQL `0001~0005`는 checksum/history Artifact이므로 소급 수정하지 않는다.

## 4. 변경할 때

1. 어떤 Concern인지 찾는다.
2. 해당 권위 문서의 상태/Schema/Command를 먼저 확인한다.
3. 구현은 최소 완결 변경으로 한다.
4. Domain/Policy/Interface 경계를 우회하지 않는다.
5. 관련 Contract/Regression Test를 같이 수정한다.
6. 새 Connector 추가 시 Core 상태/Graph를 Provider-specific으로 확장하기보다 Registry/MCP/Adapter/Normalizer/Migration 경계를 우선한다.
