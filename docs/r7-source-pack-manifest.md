# Google Work Agent · R7 Source Pack Manifest

> **생성일:** 2026-08-07  
> **공식 원본:** Notion 설계 문서  
> **Repository 직접 반영 검증:** 미수행  
> **Source Document:** 26개  
> **DB Schema:** v1.3 (`0001_initial.sql` v1.2 baseline + `0002_action_effect_send_delete.sql`)

## 문서 목록

| No. | 파일 | 역할 |
|---:|---|---|
| 1 | `00-CODE-AGENT-START-HERE.md` | Agent 진입·작업 규칙 |
| 2 | `00-google-work-agent-overview.md` | 프로젝트 전체 개요·버전 Manifest |
| 3 | `00-PROJECT-SOURCE-GUIDE.md` | 문서 기준점·읽기 안내 |
| 4 | `0001_initial.sql` | Domain DB Schema v1.2 baseline |
| 5 | `0002_action_effect_send_delete.sql` | Domain DB Schema v1.3 Effect Migration |
| 6 | `01-a-functional-definition.md` | 기능 정의 |
| 7 | `01-b-policy-definition.md` | 정책·승인·금지 규칙 |
| 8 | `01-IMPLEMENTATION-AND-EXPERIMENT-CHECKLIST.md` | 구현·실험 실행 체크리스트 |
| 9 | `01-requirements-prd.md` | 요구사항·PRD |
| 10 | `02-ui-ux-design.md` | UI·UX·Clarification UX |
| 11 | `03-system-architecture.md` | 시스템 아키텍처·Transaction 경계 |
| 12 | `04-domain-database-design.md` | Domain·DB·Recovery 계약 |
| 13 | `05-context-retrieval.md` | 수집·Retrieval·Query·Overbroad 정책 |
| 14 | `06-agent-workflow.md` | Agent·Workflow·Budget·Clarification 계약 |
| 15 | `07-tool-mcp-internal-interface.md` | Tool·MCP·SEND/DELETE Interface |
| 16 | `08-sequence-design.md` | 주요 시퀀스·Transaction/Recovery |
| 17 | `09-security-auth.md` | 보안·인증·고영향 Write |
| 18 | `10-infrastructure-environment.md` | 인프라·Migration·Startup 계약 |
| 19 | `11-observability-logging-audit.md` | 관측성·로그·감사 |
| 20 | `12-test-design.md` | 테스트·정합성 회귀 Gate |
| 21 | `13-evaluation-experiment.md` | 평가·Safety·Ambiguity 실험 |
| 22 | `14-operations-troubleshooting.md` | 운영·장애·구현 정합성 진단 |
| 23 | `15-agent-capability-failure-prompt-contract.md` | Approved Agent Capability·Failure·Prompt 공통 계약 |
| 24 | `state-transition-contract-v1.3.md` | 상태 전이 계약 |
| 25 | `state-transition-test-matrix-v1.3.md` | 상태 전이 테스트 Matrix |
| 26 | `r7-source-pack-manifest.md` | R7 문서 목록·변경 기록 |

## R7 핵심 변경

### 제품 정책
- `gmail_send`를 승인 필수 `SEND` Effect로 지원.
- 정확한 Task 완료는 승인 필수 `UPDATE`.
- Calendar Event 삭제는 승인 필수 `DELETE`.
- Calendar 참석자 추가·수정은 승인 필수 `UPDATE`.
- 명시적 중복 생성은 중복 사실 재확인·승인 후 허용 가능.
- Gmail Message·Thread 원문 삭제, Task 삭제, 반복 Event 전체 일괄 수정은 금지 유지.

### Clarification
- 요청/검색/분석 중 실제 모호성이 발견된 단계에서 `NEEDS_CONFIRMATION`.
- `request_understanding.clarify`가 후보·차이·선택지를 제공하고 같은 Run·Thread를 Resume.
- `처리/진행/시작/정리/마무리`는 문맥으로 의미가 확정되면 질문하지 않음.
- `답장/회신/보내줘`는 SEND 의도, `초안/문구/작성만`은 Draft 의도.
- 전체 Mailbox·무제한 Workspace 조회는 BLOCK.
- Calendar `overlap != conflict`; nested related 일정은 정상 중첩 가능.

### 팀원 구현 정합성 반영
- Google/MCP/LLM 호출을 SQLite Write Transaction 밖으로 이동.
- 외부 호출 전후 Transaction을 분리하고 두 번째 Transaction에서 `expected_version`, Action·Attempt 상태 재검사.
- Recovery Run 상태는 `RequireRecovery`·`ResolveRecovery` Domain Command 경유.
- Repository 직접 Recovery 상태 setter는 금지.

### DB
- `0001_initial.sql`은 v1.2 baseline으로 보존.
- `0002_action_effect_send_delete.sql`에서 `SEND | DELETE`, `SENT_LOOKUP | GET_ABSENT`, `MESSAGE_SEARCH` 정책을 추가.
- 상태 전이 Contract/Matrix는 v1.3 유지. Effect 확장은 상태 Enum 변경이 아님.

## 공식 문서 버전

| 문서 | 버전 |
|---|---:|
| 00 Overview | v1.2 |
| 01 PRD | v2.4 |
| 01-A Functional | v2.3 |
| 01-B Policy | v2.3 |
| 02 UI·UX | v2.3 |
| 03 Architecture | v2.6 |
| 04 Domain·DB | v1.9 |
| 05 Retrieval | v2.1 |
| 06 Workflow | v5.5 |
| 07 Interface | v2.4 |
| 08 Sequence | v2.6 |
| 09 Security | v2.2 |
| 10 Infrastructure | v2.4 |
| 11 Observability | v2.4 |
| 12 Test | v2.5 |
| 13 Evaluation | v2.6 |
| 14 Operations | v2.2 |
| 15 Capability Contract | v1.0 |
| Domain DB Schema | v1.3 |
| State Transition | v1.3 |
| State Transition Matrix | v1.3 |
