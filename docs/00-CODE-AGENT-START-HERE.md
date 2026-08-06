# Google Work Agent — Code Agent Start Here

## 공식 기준
- Notion이 설계의 공식 원본이다.
- 이 ZIP은 2026-08-06 기준 Repository 구현용 동기화 Snapshot이다.
- 현재 핵심 버전: PRD v2.3, Architecture v2.5, Workflow v5.4, Evaluation v2.4, State Transition v1.3.

## 문서 우선순위
1. `00-google-work-agent-overview.md`
2. `01-requirements-prd.md`
3. `01-b-policy-definition.md`
4. `state-transition-contract-v1.3.md`
5. `04-domain-database-design.md` 및 `0001_initial.sql`
6. `03-system-architecture.md`
7. `06-agent-workflow.md`
8. `07-tool-mcp-internal-interface.md`
9. 나머지 하위 설계서

## 구현 시작 순서
1. Domain 상태 전이와 SQLite Migration
2. Repository 조건부 Update와 Command Receipt
3. Approval Snapshot, Arguments Hash, Claim Token
4. Fake Google Gateway와 Fixture Loader
5. Answer-only → READ-only → 단일 WRITE 승인·실행·GET 검증
6. UNKNOWN_RESULT 복구
7. Tier A LLM Node 5개
8. `SINGLE_BASELINE` → `THREE_STAGE` → `SIX_ROLE_BASELINE`

## 금지
- 6개 Agent와 19개 Prompt를 한 번에 구현하지 않는다.
- LLM이 승인, 정책, 실행 성공, 복구 여부를 최종 결정하게 하지 않는다.
- 승인 이후 Tool·Arguments·대상 Resource를 재생성하지 않는다.
- `UNKNOWN_RESULT`를 자동 재실행하지 않는다.
- 문서에 없는 상태·Enum·비즈니스 규칙을 임의 추가하지 않는다.
