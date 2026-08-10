# Google Work Agent — 5분 개요

> **기준일:** 2026-08-10 · **Canonical:** Claim V2·Attachment·Task 날짜 의미 · **공식 원본:** Notion · **이 파일:** Repository Export Snapshot

## 제품 흐름

```text
사용자 요청
→ 필요한 Google 자료 조회
→ Evidence·업무 관계 분석
→ 답변 또는 Action Plan
→ Domain·Policy 검증
→ 사용자 승인
→ Claim V2
→ Google Write
→ 실제 Google 상태 재조회·검증
```

## 책임 분리

| LLM·Agent | 결정적 코드 |
|---|---|
| 요청 이해, Source 전략, Evidence 선택, 분석, 계획, 검토 | Policy, 승인, Claim V2, Tool Arguments 검증, Write, Verification, Recovery |

- `SINGLE=1`, `THREE=3`, `SIX=6` Agent Subgraph를 비교하며 Agent 수와 LLM Call 수는 별도다.
- 모든 Profile은 같은 Domain·Policy·Execution·Verification Engine을 사용한다.
- Domain Store는 승인·실행·검증 사실, Checkpoint는 재개 위치, SSE/UI는 Projection이다.

## 핵심 실행·첨부파일 계약

### ClaimContextV2
`approval_arguments_hash`는 사용자가 승인한 Business Arguments를, `execution_arguments_hash`는 실제 MCP Dispatch Payload를 고정한다. MCP가 서명·TTL·Process Instance·Action·Approval·Attempt·Tool·두 Hash·Nonce와 실제 수신 Arguments hash를 모두 검증한 뒤에만 Write한다.

### Gmail 첨부파일
- 수신: Attachment Metadata → 사용자 선택 → MCP Read → Download Stream.
- 발신: Local File → Staging Descriptor/SHA-256 → Approval → Claim V2 → MCP MIME Draft/SEND.
- 첨부파일 bytes·내용은 LLM Prompt·Context·Evidence로 보내지 않는다.
- 새 OAuth Scope는 추가하지 않는다. 기존 Gmail read/compose 범위에서 처리한다.

## Canonical Version Manifest

| 문서 | 버전 |
|---|---:|
| PRD | v2.8 |
| Functional | v2.9 |
| Policy | v2.8 |
| UI·UX | v2.8 |
| Architecture | v3.0 |
| Domain·DB | v1.12 |
| Retrieval | v2.6 |
| Workflow | v6.1 |
| Interface | v2.10 |
| Sequence | v3.2 |
| Security | v2.5 |
| Infrastructure | v2.7 |
| Observability | v2.9 |
| Test | v3.5 |
| Evaluation | v3.2 |
| Operations | v2.5 |
| Agent Capability·Failure·Prompt | v1.5 |
| Domain DB Schema | v1.4 |
| Domain State Transition | v1.4 |
| State Transition Test Matrix | v1.4 |
