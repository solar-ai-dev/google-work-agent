# Google Work Agent — Project Source Guide

## 목적

이 묶음은 WebGPT 프로젝트가 설계 검토, 구현 질의, 면접 준비, 실험 설계 검토를 수행할 때 사용하는 **R8.4 최신 프로젝트 소스 25개**다.

## 문서 권위·책임 소유 규칙

```text
제품 목표·범위          → 01 PRD
사용자 기능 동작        → 01-A Functional
안전·금지·승인 정책     → 01-B Policy
시스템 경계             → 03 Architecture
영속 사실·상태 전이     → 04 Domain·DB + State Contract + SQL Constraint
Retrieval 계약          → 05
Agent·Workflow 계약     → 06
Tool·MCP·내부 Interface → 07
시퀀스                  → 08
보안                    → 09
환경·배포               → 10
관측성                  → 11
제품 회귀 검증          → 12
후보 비교·실험          → 13
운영                    → 14
Prompt·Failure 정규화   → 15
```

문서 번호가 뒤라고 더 높은 권위를 갖지 않는다. 같은 Concern에서는 해당 소유 계약과 실행 가능한 Domain/SQL Constraint를 우선한다.

## R8.4 핵심 기준

- ClaimContextV2: 승인 Business Hash와 실제 Execution Hash 분리, HMAC-SHA-256, TTL, Service/MCP instance binding, one-time nonce, MCP 실제 arguments 재검증.
- Gmail Attachment: metadata/read/download + Draft/Send attachment. Bytes는 LLM 입력·Evidence·SQLite·Trace에서 제외.
- DB Schema v1.4: `0001_initial.sql` + `0002_action_effect_send_delete.sql` + `0003_action_cancelled.sql`.
- Write 순서: `Approval → Claim Commit → MCP/Google Write → Google re-read Verification`.
- UNKNOWN_RESULT blind resend 금지, MISMATCH 자동 rollback/autofix 금지.

## WebGPT 25개 구성

구현 체크리스트는 사람이 진행 상황을 관리하는 보조 Artifact라 25개 제한에서 제외하고, 실제 DB v1.4 Constraint를 제공하는 `0003_action_cancelled.sql`을 포함한다.

1. `00-CODE-AGENT-START-HERE.md`
2. `00-PROJECT-SOURCE-GUIDE.md`
3. `00-google-work-agent-overview.md`
4. `0001_initial.sql`
5. `0002_action_effect_send_delete.sql`
6. `0003_action_cancelled.sql`
7. `01-requirements-prd.md`
8. `01-a-functional-definition.md`
9. `01-b-policy-definition-v2.7.md`
10. `02-ui-ux-design.md`
11. `03-system-architecture.md`
12. `04-domain-database-design.md`
13. `05-context-retrieval.md`
14. `06-agent-workflow.md`
15. `07-tool-mcp-internal-interface.md`
16. `08-sequence-design.md`
17. `09-security-auth-v2.5.md`
18. `10-infrastructure-environment-v2.7.md`
19. `11-observability-logging-audit.md`
20. `12-test-design.md`
21. `13-evaluation-experiment.md`
22. `14-operations-troubleshooting.md`
23. `15-agent-capability-failure-prompt-contract.md`
24. `state-transition-contract-v1.4.md`
25. `state-transition-test-matrix-v1.4.md`
